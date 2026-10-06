import torch
from torch import nn
from transformers import AutoTokenizer, AutoModelForTokenClassification

def create_anonymizer(model_name: str = "denis-gordeev/rured2-ner-microsoft-mdeberta-v3-base", device: str = None):
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForTokenClassification.from_pretrained(model_name).to(device)
    model.eval()
    
    sigmoid = nn.Sigmoid()
    id_to_label = {int(k): v for k, v in model.config.id2label.items()}
    
    def get_entity_type(labels):
        """Определяет тип сущности по списку предсказанных меток."""
        has_person = any('person' in lbl.lower() for lbl in labels)
        loc_keywords = ['city', 'country', 'gpe', 'location', 'region', 'borough', 'village', 'street']
        has_location = any(any(kw in lbl.lower() for kw in loc_keywords) for lbl in labels)
        
        if has_person:
            return 'person'
        elif has_location:
            return 'location'
        return None

    def mask_person(text_span: str) -> str:
        """Оставляет первую букву каждого слова, остальные заменяет на *"""
        masked = []
        in_word = False
        for char in text_span:
            if char.isalpha():
                if not in_word:
                    masked.append(char)
                    in_word = True
                else:
                    masked.append('*')
            else:
                masked.append(char)
                in_word = False
        return "".join(masked)

    def can_merge(gap_text: str) -> bool:
        """Проверяет, можно ли объединить две части сущности (если между ними только пробелы/пунктуация)"""
        return not any(char.isalnum() for char in gap_text)

    def anonymize(text: str) -> str:
        if not text.strip():
            return text

        tokenized = tokenizer(text, return_offsets_mapping=True, add_special_tokens=True)
        input_ids_list = tokenized["input_ids"]
        offsets_list = tokenized["offset_mapping"]
        
        input_ids = torch.tensor([input_ids_list], dtype=torch.long).to(device)
        attention_mask = torch.tensor([tokenized["attention_mask"]], dtype=torch.long).to(device)
        
        with torch.no_grad():
            preds = model(input_ids=input_ids, attention_mask=attention_mask)
        
        logits = sigmoid(preds.logits)[0] 
        spans_to_replace = []
        
        current_entity_start = None
        current_entity_end = None
        current_entity_type = None
        
        for i in range(len(input_ids_list)):
            token_id = input_ids_list[i]
            offset = offsets_list[i]
            
            if token_id in [tokenizer.cls_token_id, tokenizer.sep_token_id, tokenizer.pad_token_id]:
                continue
            if offset == (0, 0):
                continue
                
            class_ids = (logits[i] > 0.5).nonzero()
            if class_ids.shape[0] >= 1:
                class_names = [id_to_label[int(cl.item())] for cl in class_ids]
            else:
                class_names = [id_to_label[int(logits[i].argmax().item())]]
                
            entity_type = get_entity_type(class_names)
            is_beginning = any(lbl.startswith('B-') for lbl in class_names)
            
            if entity_type:
                if current_entity_type != entity_type or is_beginning:
                    if current_entity_type is not None:
                        spans_to_replace.append((current_entity_start, current_entity_end, current_entity_type))
                    current_entity_start = offset[0]
                    current_entity_end = offset[1]
                    current_entity_type = entity_type
                else:
                    current_entity_end = offset[1]
            else:
                if current_entity_type is not None:
                    spans_to_replace.append((current_entity_start, current_entity_end, current_entity_type))
                    current_entity_type = None
                    
        if current_entity_type is not None:
            spans_to_replace.append((current_entity_start, current_entity_end, current_entity_type))
            
        # 1. Очищаем спаны от захваченных пробелов на границах
        cleaned_spans = []
        for start, end, etype in spans_to_replace:
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end-1].isspace():
                end -= 1
            if start < end:
                cleaned_spans.append((start, end, etype))
                
        # 2. Объединяем разорванные части одной сущности (например, "Великий" и "Новгород")
        cleaned_spans.sort(key=lambda x: x[0])
        merged_spans = []
        for start, end, etype in cleaned_spans:
            if merged_spans and merged_spans[-1][2] == etype:
                prev_start, prev_end, prev_etype = merged_spans[-1]
                gap_text = text[prev_end:start]
                if can_merge(gap_text):
                    merged_spans[-1] = (prev_start, end, etype)
                else:
                    merged_spans.append((start, end, etype))
            else:
                merged_spans.append((start, end, etype))
                
        # 3. Выполняем замены с конца строки
        result_text = text
        for start, end, etype in reversed(merged_spans):
            original_text = text[start:end]
            
            if etype == 'person':
                replacement = mask_person(original_text)
            elif etype == 'location':
                replacement = '<...>'
            else:
                replacement = original_text
                
            result_text = result_text[:start] + replacement + result_text[end:]
            
        return result_text

    return anonymize


# ==============================
# Проверка на ваших примерах
# ==============================
if __name__ == "__main__":
    print("Загрузка модели...")
    anonymizer = create_anonymizer()
    
    test_cases = [
        "Мария родилась в Москве в 1990 году.",
        "Иван Иванов и Петр Петров поехали в Санкт-Петербург и Великий Новгород.",
        "Президент Франции Эмманюэль Макрон встретился с канцлером Германии в Берлине.",
        "Компания 'Ромашка' из города Екатеринбурга, которой руководит Алексей Смирнов, открыла новый завод."
    ]
    
    for text in test_cases:
        print(f"\nОригинал:        {text}")
        print(f"Анонимизировано: {anonymizer(text)}")