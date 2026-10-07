from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def main_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, cb in [
        ("📝 Подать заявку", "menu:apply"),
        ("📄 Требования к тезисам", "menu:materials"),
        ("⏰ Дедлайн", "menu:deadline"),
        ("⏳ Обратный отсчёт", "menu:countdown"),
        ("📋 Статус заявки", "menu:status"),
        ("❓ FAQ", "menu:faq"),
        ("💬 Обратная связь", "menu:feedback"),
        ("ℹ️ Помощь", "menu:help"),
    ]:
        b.button(text=text, callback_data=cb)
    b.adjust(2, 2, 2, 2)
    return b.as_markup()


def consent_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да, согласен", callback_data="consent:yes")
    b.button(text="❌ Нет", callback_data="consent:no")
    b.adjust(2)
    return b.as_markup()


def yes_no() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Да", callback_data="yes")
    b.button(text="❌ Нет", callback_data="no")
    b.adjust(2)
    return b.as_markup()


def formats_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value in ["Доклад", "Слушатель", "Стенд", "Онлайн"]:
        b.button(text=value, callback_data=f"apply:format:{value}")
    b.adjust(2)
    return b.as_markup()


def sections_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value in ["Искусственный интеллект", "Цифровая экономика", "Образование", "Инженерные системы"]:
        b.button(text=value, callback_data=f"apply:section:{value}")
    b.adjust(1)
    return b.as_markup()


def faq_categories(categories: list[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for c in categories:
        b.button(text=c, callback_data=f"faqcat:{c[:50]}")
    b.button(text="🔎 Поиск по FAQ", callback_data="faqsearch")
    b.button(text="💬 Задать вопрос", callback_data="faqask")
    b.button(text="🏠 Главное меню", callback_data="menu:root")
    b.adjust(2, 2, 1)
    return b.as_markup()


def faq_questions(category: str, ids: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for item_id, q in ids[:15]:
        b.button(text=q[:55], callback_data=f"faqq:{item_id}")
    b.button(text="⬅️ Категории", callback_data="faqroot")
    b.button(text="🏠 Главное меню", callback_data="menu:root")
    b.adjust(1)
    return b.as_markup()


def status_admin_keyboard(app_id: int, status: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for value, label in [("under_review", "🔎 На проверке"), ("accepted", "✅ Принять"), ("rejected", "❌ Отклонить"), ("waitlist", "🕒 В лист ожидания")]:
        if value != status:
            b.button(text=label, callback_data=f"astatus:{app_id}:{value}")
    b.button(text="📝 Комментарий", callback_data=f"acomment:{app_id}")
    b.adjust(2, 2, 1)
    return b.as_markup()


def user_status_keyboard(app_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✏️ Запросить изменение", callback_data=f"change_request:{app_id}")
    b.button(text="🏠 Главное меню", callback_data="menu:root")
    b.adjust(1)
    return b.as_markup()


def delete_data_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🗑 Удалить мои данные", callback_data="data:delete")
    return b.as_markup()


def delete_confirm_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Да, удалить", callback_data="data:delete:yes")
    b.button(text="Отмена", callback_data="data:delete:no")
    b.adjust(2)
    return b.as_markup()


def admin_app_filters() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for status, label in [("all", "Все"), ("submitted", "Отправлены"), ("under_review", "На проверке"), ("accepted", "Приняты"), ("rejected", "Отклонены"), ("waitlist", "Лист ожидания")]:
        b.button(text=label, callback_data=f"adminapps:{status}")
    b.adjust(2, 2, 2)
    return b.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for text, cb in [
        ("📋 Заявки", "admin:apps"),
        ("📊 Статистика", "admin:stats"),
        ("📤 CSV", "admin:csv"),
        ("📥 XLSX", "admin:xlsx"),
        ("📣 Рассылка", "admin:broadcast"),
        ("⚙️ Настройки", "admin:settings"),
        ("❓ FAQ", "admin:faq"),
        ("🎫 Тикеты", "admin:tickets"),
    ]:
        b.button(text=text, callback_data=cb)
    b.adjust(2, 2, 2, 2)
    return b.as_markup()
