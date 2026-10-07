from __future__ import annotations

import asyncio
import io
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, func, select

from config import config
from db import Admin, Application, ApplicationHistory, FAQ, Session, Setting, Ticket, User, get_setting, init_db
from keyboards import (
    admin_app_filters, admin_menu, consent_keyboard, delete_confirm_keyboard, delete_data_keyboard,
    faq_categories, faq_questions, formats_keyboard, main_menu, sections_keyboard, status_admin_keyboard, user_status_keyboard, yes_no,
)
from services import (
    FORMATS, SECTIONS, STATUS_RU, application_rows, export_csv_bytes, export_xlsx_bytes,
    google_calendar_url, make_ics, recommend_section, save_status_change,
    validate_abstract, validate_email, validate_phone, validate_references,
)
from states import AdminStates, ApplyStates, FeedbackStates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("conference_bot")

router = Router()
scheduler = AsyncIOScheduler()

DEMO_ABSTRACT = (
    "Цель исследования — оценить практическую эффективность методов интеллектуального анализа данных "
    "для мониторинга образовательных процессов в университете. Методы включают сравнительный анализ, "
    "кластеризацию и экспертную оценку качества прогнозов. Результаты показывают, что комбинирование "
    "автоматических признаков и экспертной верификации повышает устойчивость модели к неполному вводу данных. "
    "Выводы: предложенный подход может использоваться как вспомогательный инструмент аналитика и преподавателя, "
    "при этом критически важные решения должны подтверждаться специалистом."
)
DEMO_REFS = "1. Иванов И.И. Цифровая аналитика. М.: Наука, 2024.\n2. Петров П.П. Машинное обучение. СПб.: Питер, 2025.\n3. Smith J. Data-driven education. 2023. DOI: 10.1234/example.2023.42"


def is_admin(user_id: int) -> bool:
    return user_id in config.admin_ids


def parse_dt(text: str, fallback_tz: str) -> datetime | None:
    try:
        value = datetime.fromisoformat(text.strip())
        if value.tzinfo is None:
            value = value.replace(tzinfo=ZoneInfo(fallback_tz))
        return value
    except ValueError:
        return None


async def current_settings() -> tuple[datetime, datetime, str, bool]:
    tz_name = await get_setting("timezone", config.default_timezone) or config.default_timezone
    deadline_raw = await get_setting("deadline", config.default_deadline) or config.default_deadline
    event_raw = await get_setting("event_start", config.default_event_start) or config.default_event_start
    is_open = (await get_setting("is_open", "true") or "true").lower() == "true"
    tz = ZoneInfo(tz_name)
    deadline = parse_dt(deadline_raw, tz_name) or datetime.fromisoformat(config.default_deadline)
    event = parse_dt(event_raw, tz_name) or datetime.fromisoformat(config.default_event_start)
    return deadline.astimezone(tz), event.astimezone(tz), tz_name, is_open


async def get_or_create_user(message: Message) -> User:
    async with Session() as session:
        obj = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        if not obj:
            obj = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
            )
            session.add(obj)
            await session.commit()
            await session.refresh(obj)
        else:
            obj.username = message.from_user.username
            obj.first_name = message.from_user.first_name
            obj.last_name = message.from_user.last_name
            await session.commit()
        return obj


async def notify_admins(bot: Bot, text: str, reply_markup=None) -> None:
    for admin_id in config.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except (TelegramForbiddenError, TelegramBadRequest):
            log.warning("Cannot notify admin %s", admin_id)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    user = await get_or_create_user(message)
    if not user.consent:
        await message.answer(
            "Здравствуйте! Это бот конференции «Цифровая наука — 2026».\n\n"
            "Перед началом работы подтвердите согласие на обработку персональных данных.",
            reply_markup=consent_keyboard(),
        )
        return
    await message.answer(
        f"С возвращением, {message.from_user.first_name or 'участник'}!\n\n"
        "Выберите нужный раздел:", reply_markup=main_menu()
    )


@router.callback_query(F.data == "consent:yes")
async def consent_yes(call: CallbackQuery) -> None:
    async with Session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
        if user:
            user.consent = True
            await session.commit()
    await call.answer("Согласие сохранено")
    await call.message.edit_text("Спасибо! Данные сохраняются только для обработки заявки и коммуникации с организаторами.")
    await call.message.answer("Главное меню:", reply_markup=main_menu())


@router.callback_query(F.data == "consent:no")
async def consent_no(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.edit_text("Без согласия на обработку персональных данных подача заявки недоступна.")


@router.callback_query(F.data == "menu:root")
async def menu_root(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.answer("🏠 Главное меню:\n\nВыберите нужный раздел:", reply_markup=main_menu())
    await call.answer()


@router.callback_query(F.data == "menu:apply")
async def menu_apply(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await apply_start(call.message, state)
    await call.answer()


@router.callback_query(F.data == "menu:materials")
async def menu_materials(call: CallbackQuery) -> None:
    await materials(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:deadline")
async def menu_deadline(call: CallbackQuery) -> None:
    await deadline(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:countdown")
async def menu_countdown(call: CallbackQuery) -> None:
    await countdown(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:status")
async def menu_status(call: CallbackQuery) -> None:
    await status(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:faq")
async def menu_faq(call: CallbackQuery) -> None:
    await faq(call.message)
    await call.answer()


@router.callback_query(F.data == "menu:feedback")
async def menu_feedback(call: CallbackQuery, state: FSMContext) -> None:
    await feedback(call.message, state)
    await call.answer()


@router.callback_query(F.data == "menu:help")
async def menu_help(call: CallbackQuery) -> None:
    await help_text(call.message)
    await call.answer()


@router.message(Command("menu"))
@router.message(F.text == "Помощь")
async def show_help_or_menu(message: Message) -> None:
    if message.text == "Помощь":
        await help_text(message)
    else:
        await message.answer("Главное меню:", reply_markup=main_menu())


@router.message(Command("help"))
async def help_text(message: Message) -> None:
    await message.answer(
        "<b>Помощь</b>\n\n"
        "/start — запуск и согласие\n/menu — главное меню\n/apply — новая заявка\n/status — статус заявки\n"
        "/deadline — дедлайн\n/countdown — отсчёт до мероприятия\n/materials — требования\n/calendar — календарь\n"
        "/faq — FAQ\n/feedback — обращение\n/support — контакты поддержки\n/my_data — мои данные\n/cancel — отменить действие\n/admin — админ-панель\n\n"
        "Частые ошибки: слишком короткие тезисы, меньше трёх источников, неверный email или телефон."
    )


@router.message(Command("materials"))
@router.message(F.text == "Требования к тезисам")
async def materials(message: Message) -> None:
    await message.answer(
        "<b>Требования к тезисам</b>\n\n"
        "• 1500–3000 знаков.\n• Структура: цель, методы, результаты, выводы.\n"
        "• Список литературы: минимум 3 источника.\n• Рекомендуется указывать DOI/URL.\n"
        "• Стиль оформления: ГОСТ / APA / IEEE — зависит от настроек конференции.\n\n"
        "Перед отправкой бот автоматически проверит объём, структуру и количество источников."
    )


@router.message(Command("deadline"))
@router.message(F.text == "Дедлайн")
async def deadline(message: Message) -> None:
    dl, _, tz_name, is_open = await current_settings()
    now = datetime.now(dl.tzinfo)
    delta = dl - now
    if delta.total_seconds() > 0:
        days, rem = divmod(int(delta.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        mins, _ = divmod(rem, 60)
        remaining = f"{days} дн. {hours} ч. {mins} мин."
    else:
        remaining = "срок уже истёк"
    await message.answer(
        f"<b>Дедлайн</b>\nДата: {dl:%d.%m.%Y %H:%M}\nЧасовой пояс: {tz_name}\n"
        f"Приём: {'открыт' if is_open and delta.total_seconds() > 0 else 'закрыт'}\nОсталось: {remaining}"
    )


@router.message(Command("countdown"))
@router.message(F.text == "Обратный отсчёт")
async def countdown(message: Message) -> None:
    _, event, _, _ = await current_settings()
    now = datetime.now(event.tzinfo)
    delta = event - now
    if delta.total_seconds() <= 0:
        text = "Мероприятие уже началось или завершилось."
    else:
        days, rem = divmod(int(delta.total_seconds()), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        text = f"До начала: <b>{days} дней, {hours} часов, {minutes} минут</b>."
    await message.answer(text, reply_markup=None)


@router.message(Command("calendar"))
async def calendar(message: Message) -> None:
    _, event, tz_name, _ = await current_settings()
    end_raw = await get_setting("event_end", config.default_event_end) or config.default_event_end
    end = parse_dt(end_raw, tz_name) or event + timedelta(hours=8)
    description = "Конференция «Цифровая наука — 2026». Место/ссылка уточняются организаторами."
    ics = make_ics("Цифровая наука — 2026", event, end, description)
    google = google_calendar_url("Цифровая наука — 2026", event, end, description)
    await message.answer_document(BufferedInputFile(ics, filename="conference.ics"))
    await message.answer(f"Google Calendar:\n{google}")


@router.message(Command("faq"))
@router.message(F.text == "FAQ")
async def faq(message: Message) -> None:
    async with Session() as session:
        cats = [x[0] for x in (await session.execute(select(FAQ.category).distinct().order_by(FAQ.category))).all()]
    await message.answer("<b>Частые вопросы</b>\nВыберите категорию:", reply_markup=faq_categories(cats))


@router.callback_query(F.data == "faqroot")
async def faq_root(call: CallbackQuery) -> None:
    await faq(call.message)
    await call.answer()


@router.callback_query(F.data.startswith("faqcat:"))
async def faq_cat(call: CallbackQuery) -> None:
    cat = call.data.split(":", 1)[1]
    async with Session() as session:
        rows = (await session.execute(select(FAQ.id, FAQ.question).where(FAQ.category == cat).order_by(FAQ.id))).all()
    await call.message.edit_text(f"<b>{cat}</b>\nВыберите вопрос:", reply_markup=faq_questions(cat, list(rows)))
    await call.answer()


@router.callback_query(F.data.startswith("faqq:"))
async def faq_question(call: CallbackQuery) -> None:
    faq_id = int(call.data.split(":", 1)[1])
    async with Session() as session:
        row = await session.get(FAQ, faq_id)
    if not row:
        await call.answer("Вопрос не найден", show_alert=True)
        return
    await call.message.edit_text(f"<b>{row.question}</b>\n\n{row.answer}", reply_markup=faq_questions(row.category, [(row.id, "⬅️ К вопросам")]))
    await call.answer()


@router.callback_query(F.data == "faqsearch")
async def faq_search(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(faq_search=True)
    await call.message.answer("Введите ключевое слово для поиска по FAQ:")
    await call.answer()


@router.message(lambda m: m.text and len(m.text) > 0 and False)
async def _never(message: Message) -> None:
    pass


async def handle_faq_search_message(message: Message, state: FSMContext) -> bool:
    data = await state.get_data()
    if not data.get("faq_search"):
        return False
    term = message.text.strip()
    async with Session() as session:
        rows = (await session.execute(select(FAQ).where((FAQ.question.ilike(f"%{term}%")) | (FAQ.answer.ilike(f"%{term}%")) | (FAQ.keywords.ilike(f"%{term}%"))))).scalars().all()
    await state.clear()
    if not rows:
        await message.answer("Совпадений нет. Нажмите «Обратная связь», чтобы задать вопрос.", reply_markup=main_menu())
    else:
        for row in rows[:8]:
            await message.answer(f"<b>{row.question}</b>\n{row.answer}")
    return True


@router.message(Command("feedback"))
@router.message(F.text == "Обратная связь")
async def feedback(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(FeedbackStates.TYPE)
    await message.answer("Тип обращения: вопрос, ошибка, предложение или жалоба?")


@router.message(FeedbackStates.TYPE)
async def feedback_type(message: Message, state: FSMContext) -> None:
    value = message.text.strip().lower()
    allowed = {"вопрос", "ошибка", "предложение", "жалоба", "изменение заявки"}
    if value not in allowed:
        await message.answer("Введите одно из значений: вопрос, ошибка, предложение, жалоба.")
        return
    await state.update_data(type=value)
    await state.set_state(FeedbackStates.TEXT)
    await message.answer("Опишите обращение:")


@router.message(FeedbackStates.TEXT)
async def feedback_text(message: Message, state: FSMContext) -> None:
    await state.update_data(text=message.text.strip())
    await state.set_state(FeedbackStates.FILE)
    await message.answer("Пришлите файл/скриншот или напишите «нет».")


@router.message(FeedbackStates.FILE)
async def feedback_file(message: Message, state: FSMContext, bot: Bot) -> None:
    file_id = None
    if message.text and message.text.lower() == "нет":
        pass
    elif message.document:
        file_id = message.document.file_id
    elif message.photo:
        file_id = message.photo[-1].file_id
    else:
        await message.answer("Пришлите документ/фото или напишите «нет».")
        return
    data = await state.get_data()
    async with Session() as session:
        ticket = Ticket(user_id=(await session.scalar(select(User.id).where(User.telegram_id == message.from_user.id))), type=data["type"], text=data["text"], attachment_file_id=file_id)
        session.add(ticket)
        await session.commit()
        await session.refresh(ticket)
        ticket_id = ticket.id
    await state.clear()
    await message.answer(f"Обращение №{ticket_id} создано. Ответ придёт сюда.", reply_markup=main_menu())
    await notify_admins(bot, f"🎫 Новое обращение #{ticket_id}\nТип: {data['type']}\nОт: {message.from_user.full_name}\n\n{data['text']}")


@router.message(Command("apply"))
@router.message(F.text == "Подать заявку")
async def apply_start(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message)
    if not user.consent:
        await message.answer("Сначала подтвердите согласие через /start.")
        return
    _, _, _, is_open = await current_settings()
    dl, _, _, _ = await current_settings()
    if not is_open or datetime.now(dl.tzinfo) >= dl:
        await message.answer("Приём заявок закрыт. Новые заявки не принимаются.")
        return
    await state.clear()
    await state.set_state(ApplyStates.ASK_NAME)
    await message.answer("<b>Шаг 1/15.</b> Введите ФИО.\n\nДля отладки можно использовать: «Иванов Иван Сергеевич».")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Текущее действие отменено.", reply_markup=main_menu())


@router.message(ApplyStates.ASK_NAME)
async def apply_name(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    if len(value.split()) < 2:
        await message.answer("Укажите хотя бы имя и фамилию.")
        return
    await state.update_data(full_name=value)
    await state.set_state(ApplyStates.ASK_EMAIL)
    await message.answer("<b>Шаг 2/15.</b> Email\nПример для отладки: ivan.petrov@example.com")


@router.message(ApplyStates.ASK_EMAIL)
async def apply_email(message: Message, state: FSMContext) -> None:
    error = validate_email(message.text)
    if error:
        await message.answer(error)
        return
    await state.update_data(email=message.text.strip())
    await state.set_state(ApplyStates.ASK_PHONE)
    await message.answer("<b>Шаг 3/15.</b> Телефон\nПример: +7 916 555-12-34")


@router.message(ApplyStates.ASK_PHONE)
async def apply_phone(message: Message, state: FSMContext) -> None:
    error = validate_phone(message.text)
    if error:
        await message.answer(error)
        return
    await state.update_data(phone=message.text.strip())
    await state.set_state(ApplyStates.ASK_ORG)
    await message.answer("<b>Шаг 4/15.</b> Организация\nПример: Национальный исследовательский университет «Высшая школа экономики»")


@router.message(ApplyStates.ASK_ORG)
async def apply_org(message: Message, state: FSMContext) -> None:
    await state.update_data(organization=message.text.strip())
    await state.set_state(ApplyStates.ASK_POSITION)
    await message.answer("<b>Шаг 5/15.</b> Должность\nПример: старший научный сотрудник")


@router.message(ApplyStates.ASK_POSITION)
async def apply_position(message: Message, state: FSMContext) -> None:
    await state.update_data(position=message.text.strip())
    await state.set_state(ApplyStates.ASK_COUNTRY_CITY)
    await message.answer("<b>Шаг 6/15.</b> Страна / город\nПример: Россия, Москва")


@router.message(ApplyStates.ASK_COUNTRY_CITY)
async def apply_country(message: Message, state: FSMContext) -> None:
    await state.update_data(country_city=message.text.strip())
    await state.set_state(ApplyStates.ASK_FORMAT)
    await message.answer("<b>Шаг 7/15.</b> Формат участия", reply_markup=formats_keyboard())


@router.message(ApplyStates.ASK_FORMAT)
async def apply_format(message: Message, state: FSMContext) -> None:
    if message.text not in FORMATS:
        await message.answer("Выберите вариант именно кнопкой ниже: Доклад / Слушатель / Стенд / Онлайн.", reply_markup=formats_keyboard())
        return
    await _save_format_and_show_section(message, state, message.text)


@router.callback_query(ApplyStates.ASK_FORMAT, F.data.startswith("apply:format:"))
async def apply_format_callback(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":", 2)[2]
    if value not in FORMATS:
        await call.answer("Неизвестный формат", show_alert=True)
        return
    await _save_format_and_show_section(call.message, state, value)
    await call.answer("Формат выбран")


async def _save_format_and_show_section(message: Message, state: FSMContext, value: str) -> None:
    await state.update_data(type=value)
    await state.set_state(ApplyStates.ASK_SECTION)
    await message.answer("<b>Шаг 8/15.</b> Секция\n\nВыберите секцию кнопкой ниже:", reply_markup=sections_keyboard())


@router.message(ApplyStates.ASK_SECTION)
async def apply_section(message: Message, state: FSMContext) -> None:
    if message.text not in SECTIONS:
        await message.answer("Выберите секцию именно кнопкой ниже.", reply_markup=sections_keyboard())
        return
    await _save_section_and_continue(message, state, message.text)


@router.callback_query(ApplyStates.ASK_SECTION, F.data.startswith("apply:section:"))
async def apply_section_callback(call: CallbackQuery, state: FSMContext) -> None:
    value = call.data.split(":", 2)[2]
    if value not in SECTIONS:
        await call.answer("Неизвестная секция", show_alert=True)
        return
    await _save_section_and_continue(call.message, state, value)
    await call.answer("Секция выбрана")


async def _save_section_and_continue(message: Message, state: FSMContext, value: str) -> None:
    await state.update_data(section=value)
    await state.set_state(ApplyStates.ASK_TITLE)
    await message.answer("<b>Шаг 9/15.</b> Тема доклада\nПример: «Оценка качества генеративных моделей в университетской аналитике»")


@router.message(ApplyStates.ASK_TITLE)
async def apply_title(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if len(title) < 10:
        await message.answer("Тема слишком короткая. Укажите содержательную формулировку.")
        return
    await state.update_data(title=title)
    await state.set_state(ApplyStates.ASK_ABSTRACT)
    await message.answer("<b>Шаг 10/15.</b> Вставьте тезисы (1500–3000 знаков).\n\nТестовый пример начинается с «Цель исследования…» и занимает достаточно текста.")


@router.message(ApplyStates.ASK_ABSTRACT)
async def apply_abstract(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    errors = validate_abstract(text)
    hard = [e for e in errors if "объём" in e or "Не найден" in e]
    if hard:
        await message.answer("Тезисы пока не проходят проверку:\n• " + "\n• ".join(errors))
        return
    recommendation = recommend_section((await state.get_data()).get("title", ""), text)
    await state.update_data(abstract=text)
    await state.set_state(ApplyStates.ASK_REFERENCES)
    await message.answer(f"Проверка тезисов пройдена. Рекомендованная секция по ключевым словам: <b>{recommendation}</b>.\n\n<b>Шаг 11/15.</b> Список литературы, не менее 3 источников.")


@router.message(ApplyStates.ASK_REFERENCES)
async def apply_references(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    errors = validate_references(text)
    if any("Найдено источников" in e for e in errors):
        await message.answer("Список литературы не проходит проверку:\n• " + "\n• ".join(errors))
        return
    await state.update_data(references=text)
    await state.set_state(ApplyStates.ASK_COAUTHORS)
    await message.answer("<b>Шаг 12/15.</b> Соавторы. Если их нет, напишите «нет». ")


@router.message(ApplyStates.ASK_COAUTHORS)
async def apply_coauthors(message: Message, state: FSMContext) -> None:
    value = message.text.strip()
    await state.update_data(coauthors="" if value.lower() == "нет" else value)
    await state.set_state(ApplyStates.ASK_FILE)
    await message.answer("<b>Шаг 13/15.</b> Файл презентации/тезисов — пришлите документ или напишите «нет».")


@router.message(ApplyStates.ASK_FILE)
async def apply_file(message: Message, state: FSMContext) -> None:
    if message.text and message.text.lower() == "нет":
        await state.update_data(file_id=None)
    elif message.document:
        await state.update_data(file_id=message.document.file_id)
    else:
        await message.answer("Нужен документ или слово «нет».")
        return
    await state.set_state(ApplyStates.ASK_CONSENT)
    await message.answer("<b>Шаг 14/15.</b> Подтвердите согласие на обработку персональных данных.", reply_markup=consent_keyboard())


@router.callback_query(ApplyStates.ASK_CONSENT, F.data == "consent:yes")
async def apply_consent_yes(call: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(consent=True)
    await state.set_state(ApplyStates.CONFIRM)
    data = await state.get_data()
    await call.message.answer(
        "<b>Шаг 15/15. Проверьте заявку:</b>\n\n"
        f"ФИО: {data['full_name']}\nEmail: {data['email']}\nТелефон: {data['phone']}\nОрганизация: {data['organization']}\n"
        f"Должность: {data['position']}\nГород: {data['country_city']}\nФормат: {data['type']}\nСекция: {data['section']}\n"
        f"Тема: {data['title']}\nСоавторы: {data.get('coauthors') or 'нет'}\nФайл: {'да' if data.get('file_id') else 'нет'}\n\n"
        "Отправить заявку? Напишите «да» или «нет»."
    )
    await call.answer()


@router.callback_query(ApplyStates.ASK_CONSENT, F.data == "consent:no")
async def apply_consent_no(call: CallbackQuery) -> None:
    await call.answer()
    await call.message.answer("Без согласия заявка не может быть отправлена. Ввод можно продолжить позже через /apply.")


@router.message(ApplyStates.CONFIRM)
async def apply_confirm(message: Message, state: FSMContext, bot: Bot) -> None:
    if message.text.strip().lower() not in {"да", "нет"}:
        await message.answer("Напишите «да» или «нет».")
        return
    if message.text.strip().lower() == "нет":
        await state.clear()
        await message.answer("Заявка не отправлена.", reply_markup=main_menu())
        return
    data = await state.get_data()
    dl, _, _, is_open = await current_settings()
    if not is_open or datetime.now(dl.tzinfo) >= dl:
        await state.clear()
        await message.answer("Пока вы заполняли форму, дедлайн закончился. Заявка не отправлена.")
        return
    async with Session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        duplicate = await session.scalar(select(Application.id).where(Application.title.ilike(data["title"].strip())).limit(1))
        if duplicate:
            await message.answer(f"⚠️ Тема очень похожа на уже зарегистрированную заявку #{duplicate}. Заявка всё равно может быть отправлена — при необходимости уточните формулировку.")
        app = Application(
            user_id=user.id, status="submitted", section=data["section"], type=data["type"], title=data["title"],
            abstract=data["abstract"], references=data["references"], coauthors=data.get("coauthors", ""), file_id=data.get("file_id"),
            full_name=data["full_name"], email=data["email"], phone=data["phone"], organization=data["organization"],
            position=data["position"], country_city=data["country_city"], submitted_at=datetime.now(timezone.utc),
        )
        session.add(app)
        await session.flush()
        session.add(ApplicationHistory(application_id=app.id, old_status="draft", new_status="submitted", changed_by=message.from_user.id))
        user.email = data["email"]
        user.phone = data["phone"]
        user.consent = True
        await session.commit()
        app_id = app.id
    await state.clear()
    await message.answer(f"✅ Заявка <b>#{app_id}</b> отправлена. Статус: <b>отправлена</b>.", reply_markup=main_menu())
    await notify_admins(bot, f"🆕 Новая заявка #{app_id}\n{data['full_name']}\n{data['section']}\n{data['title']}", status_admin_keyboard(app_id, "submitted"))


@router.message(Command("status"))
@router.message(F.text == "Статус заявки")
async def status(message: Message) -> None:
    async with Session() as session:
        apps = (await session.execute(select(Application).join(User).where(User.telegram_id == message.from_user.id).order_by(Application.id.desc()))).scalars().all()
    if not apps:
        await message.answer("Заявок пока нет. Подать новую можно через /apply.")
        return
    chunks = []
    for app in apps[:5]:
        async with Session() as history_session:
            history = (await history_session.execute(select(ApplicationHistory).where(ApplicationHistory.application_id == app.id).order_by(ApplicationHistory.id.desc()).limit(5))).scalars().all()
        history_text = ", ".join(STATUS_RU.get(x.new_status, x.new_status) for x in reversed(history)) or STATUS_RU.get(app.status, app.status)
        chunks.append(f"<b>#{app.id}</b> — {STATUS_RU.get(app.status, app.status)}\nСекция: {app.section}\nТема: {app.title}\nИстория: {history_text}\nКомментарий: {app.moderator_comment or '—'}")
    await message.answer("\n\n".join(chunks))
    await message.answer("Для запроса изменения выберите последнюю заявку:", reply_markup=user_status_keyboard(apps[0].id))


@router.callback_query(F.data.startswith("change_request:"))
async def request_change(call: CallbackQuery, state: FSMContext) -> None:
    app_id = int(call.data.split(":", 1)[1])
    async with Session() as session:
        app = await session.get(Application, app_id)
        user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
        if not app or not user or app.user_id != user.id:
            await call.answer("Заявка не найдена", show_alert=True)
            return
    await state.clear()
    await state.update_data(type="изменение заявки", related_application_id=app_id)
    await state.set_state(FeedbackStates.TEXT)
    await call.message.answer(f"Опишите, что нужно изменить в заявке #{app_id}:")
    await call.answer()


@router.message(Command("support"))
async def support(message: Message) -> None:
    await message.answer(f"Поддержка: {config.support_username}\nEmail: {config.support_email}\nТакже можно создать тикет через /feedback.")


@router.message(Command("my_data"))
async def my_data(message: Message) -> None:
    async with Session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == message.from_user.id))
        apps = (await session.execute(select(Application).where(Application.user_id == user.id).order_by(Application.id.desc()))).scalars().all() if user else []
    if not user:
        await message.answer("Данных пока нет.")
        return
    await message.answer(
        f"<b>Ваши данные</b>\nФИО: {user.first_name or ''} {user.last_name or ''}\nEmail: {user.email or '—'}\nТелефон: {user.phone or '—'}\n"
        f"Согласие: {'да' if user.consent else 'нет'}\nЗаявок: {len(apps)}\n\nПри удалении будут удалены профиль, заявки и обращения." ,
        reply_markup=delete_data_keyboard(),
    )


@router.callback_query(F.data == "data:delete")
async def delete_data_ask(call: CallbackQuery) -> None:
    await call.message.answer("Удалить все сохранённые данные, заявки и тикеты?", reply_markup=delete_confirm_keyboard())
    await call.answer()


@router.callback_query(F.data == "data:delete:no")
async def delete_data_no(call: CallbackQuery) -> None:
    await call.answer("Данные не удалены")
    await call.message.answer("Удаление отменено.")


@router.callback_query(F.data == "data:delete:yes")
async def delete_data_yes(call: CallbackQuery) -> None:
    async with Session() as session:
        user = await session.scalar(select(User).where(User.telegram_id == call.from_user.id))
        if not user:
            await call.answer("Данных нет")
            return
        await session.execute(delete(__import__('db').Notification).where(__import__('db').Notification.user_id == user.id))
        await session.delete(user)
        await session.commit()
    await call.answer("Удалено")
    await call.message.answer("Ваши данные удалены из базы бота. Для новой подачи заявки потребуется повторное согласие через /start.")


@router.message(Command("admin"))
async def admin_cmd(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer("Доступ запрещён.")
        return
    await message.answer("<b>Админ-панель</b>", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:apps")
async def admin_apps(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await call.message.answer("Фильтр заявок:", reply_markup=admin_app_filters())
    await call.answer()


@router.callback_query(F.data.startswith("adminapps:"))
async def admin_apps_filtered(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    status_filter = call.data.split(":", 1)[1]
    async with Session() as session:
        query = select(Application).order_by(Application.id.desc()).limit(30)
        if status_filter != "all":
            query = query.where(Application.status == status_filter)
        apps = (await session.execute(query)).scalars().all()
    if not apps:
        await call.message.answer("Заявок по фильтру нет."); await call.answer(); return
    for app in apps:
        await call.message.answer(
            f"<b>#{app.id}</b> — {STATUS_RU.get(app.status, app.status)}\n{app.full_name}\n{app.section}\n<b>{app.title}</b>\n"
            f"Email: {app.email}\nОрганизация: {app.organization}", reply_markup=status_admin_keyboard(app.id, app.status)
        )
    await call.answer()


@router.callback_query(F.data == "admin:stats")
async def admin_stats(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    async with Session() as session:
        total = await session.scalar(select(func.count(Application.id))) or 0
        stats = (await session.execute(select(Application.status, func.count(Application.id)).group_by(Application.status))).all()
    lines = [f"Всего заявок: {total}"] + [f"{STATUS_RU.get(status, status)}: {count}" for status, count in stats]
    await call.message.answer("📊 <b>Статистика</b>\n" + "\n".join(lines)); await call.answer()


@router.callback_query(F.data.in_({"admin:csv", "admin:xlsx"}))
async def admin_export(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    rows = await application_rows()
    if call.data.endswith("csv"):
        await call.message.answer_document(BufferedInputFile(export_csv_bytes(rows), filename="applications.csv"))
    else:
        await call.message.answer_document(BufferedInputFile(export_xlsx_bytes(rows), filename="applications.xlsx"))
    await call.answer("Готово")


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await state.set_state(AdminStates.BROADCAST)
    await call.message.answer("Введите текст рассылки. Сообщение уйдёт всем зарегистрированным пользователям.")
    await call.answer()


@router.message(AdminStates.BROADCAST)
async def admin_broadcast_send(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    text = message.text.strip()
    async with Session() as session:
        ids = [x[0] for x in (await session.execute(select(User.telegram_id).where(User.consent == True))).all()]  # noqa: E712
    ok = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text)
            ok += 1
        except TelegramForbiddenError:
            pass
        except TelegramBadRequest:
            pass
    await state.clear()
    await message.answer(f"Рассылка завершена. Успешно: {ok}/{len(ids)}.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:settings")
async def admin_settings(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    deadline_v = await get_setting("deadline")
    event_v = await get_setting("event_start")
    tz_v = await get_setting("timezone")
    open_v = await get_setting("is_open")
    await call.message.answer(f"⚙️ Дедлайн: {deadline_v}\nМероприятие: {event_v}\nЧасовой пояс: {tz_v}\nПриём: {open_v}\n\nДля изменения используй команду:\n/settings_deadline\n/settings_event")
    await call.answer()


@router.message(Command("settings_deadline"))
async def settings_deadline(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        return
    await state.set_state(AdminStates.SET_DEADLINE)
    await message.answer("Введите новую дату ISO 8601, например: 2026-11-20T23:59:00+03:00")


@router.message(AdminStates.SET_DEADLINE)
async def settings_deadline_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    tz = await get_setting("timezone", config.default_timezone) or config.default_timezone
    if not parse_dt(message.text, tz):
        await message.answer("Не удалось распознать дату. Пример: 2026-11-20T23:59:00+03:00")
        return
    await __import__('db').set_setting("deadline", message.text.strip())
    await state.clear()
    await message.answer("Дедлайн обновлён.", reply_markup=admin_menu())


@router.message(Command("settings_event"))
async def settings_event(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    await state.set_state(AdminStates.SET_EVENT)
    await message.answer("Введите начало мероприятия ISO 8601, например: 2026-12-05T09:30:00+03:00")


@router.message(AdminStates.SET_EVENT)
async def settings_event_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    tz = await get_setting("timezone", config.default_timezone) or config.default_timezone
    if not parse_dt(message.text, tz):
        await message.answer("Не удалось распознать дату.")
        return
    await __import__('db').set_setting("event_start", message.text.strip())
    await state.clear()
    await message.answer("Дата мероприятия обновлена.", reply_markup=admin_menu())


@router.message(Command("settings_open"))
async def settings_open(message: Message) -> None:
    if not is_admin(message.from_user.id): return
    value = message.text.split(maxsplit=1)[1].strip().lower() if len(message.text.split(maxsplit=1)) > 1 else ""
    if value not in {"on", "off", "true", "false"}:
        await message.answer("Использование: /settings_open on или /settings_open off")
        return
    await __import__('db').set_setting("is_open", "true" if value in {"on", "true"} else "false")
    await message.answer("Статус приёма заявок обновлён.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:faq")
async def admin_faq(call: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    await state.set_state(AdminStates.ADD_FAQ)
    await call.message.answer("Добавление FAQ. Введите одной строкой: Категория | Вопрос")
    await call.answer()


@router.message(AdminStates.ADD_FAQ)
async def admin_faq_question(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    parts = [x.strip() for x in message.text.split("|", 1)]
    if len(parts) != 2 or not all(parts):
        await message.answer("Формат: Категория | Вопрос")
        return
    await state.update_data(faq_category=parts[0], faq_question=parts[1])
    await state.set_state(AdminStates.FAQ_ANSWER)
    await message.answer("Введите ответ и, при желании, ключевые слова через запятую:")


@router.message(AdminStates.FAQ_ANSWER)
async def admin_faq_answer(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    parts = [x.strip() for x in message.text.split("|", 1)]
    answer = parts[0]
    keywords = parts[1] if len(parts) > 1 else ""
    data = await state.get_data()
    async with Session() as session:
        session.add(FAQ(category=data["faq_category"], question=data["faq_question"], answer=answer, keywords=keywords))
        await session.commit()
    await state.clear()
    await message.answer("FAQ добавлен.", reply_markup=admin_menu())


@router.callback_query(F.data == "admin:tickets")
async def admin_tickets(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    async with Session() as session:
        tickets = (await session.execute(select(Ticket).order_by(Ticket.id.desc()).limit(15))).scalars().all()
    if not tickets:
        await call.message.answer("Тикетов нет.")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    for t in tickets:
        kb = InlineKeyboardBuilder()
        kb.button(text="✉️ Ответить", callback_data=f"ticketreply:{t.id}")
        kb.button(text="✅ Закрыть", callback_data=f"ticketclose:{t.id}")
        kb.adjust(2)
        await call.message.answer(f"🎫 #{t.id} [{t.status}] {t.type}\n{t.text}", reply_markup=kb.as_markup())
    await call.answer()


@router.callback_query(F.data.startswith("ticketreply:"))
async def ticket_reply_start(call: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    ticket_id = int(call.data.split(":", 1)[1])
    await state.update_data(ticket_id=ticket_id)
    await state.set_state(AdminStates.TICKET_REPLY)
    await call.message.answer(f"Введите ответ для тикета #{ticket_id}:")
    await call.answer()


@router.message(AdminStates.TICKET_REPLY)
async def ticket_reply_save(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    async with Session() as session:
        ticket = await session.get(Ticket, int(data["ticket_id"]))
        if not ticket:
            await state.clear(); await message.answer("Тикет не найден."); return
        user = await session.get(User, ticket.user_id)
        ticket.admin_comment = message.text.strip()
        ticket.status = "answered"
        target_id = user.telegram_id
        await session.commit()
    await state.clear()
    try:
        await bot.send_message(target_id, f"Ответ по обращению <b>#{data['ticket_id']}</b>:\n{message.text.strip()}")
    except Exception:
        await notify_admins(bot, f"⚠️ Не удалось доставить ответ по тикету #{data['ticket_id']} пользователю {target_id}.")
    await message.answer("Ответ отправлен.", reply_markup=admin_menu())


@router.callback_query(F.data.startswith("ticketclose:"))
async def ticket_close(call: CallbackQuery) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    ticket_id = int(call.data.split(":", 1)[1])
    async with Session() as session:
        ticket = await session.get(Ticket, ticket_id)
        if ticket:
            ticket.status = "closed"
            await session.commit()
    await call.answer("Тикет закрыт")


@router.callback_query(F.data.startswith("astatus:"))
async def admin_status_change(call: CallbackQuery, bot: Bot) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    _, app_id, new_status = call.data.split(":")
    async with Session() as session:
        app = await session.get(Application, int(app_id))
        if not app:
            await call.answer("Заявка не найдена", show_alert=True); return
        old = app.status
        app.status = new_status
        app.updated_at = datetime.now(timezone.utc)
        session.add(ApplicationHistory(application_id=app.id, old_status=old, new_status=new_status, changed_by=call.from_user.id))
        user = await session.get(User, app.user_id)
        await session.commit()
        target_id = user.telegram_id
    try:
        await bot.send_message(target_id, f"Статус заявки <b>#{app_id}</b> изменён: <b>{STATUS_RU[new_status]}</b>.")
    except Exception:
        log.exception("Status notification failed for %s", target_id)
        await notify_admins(bot, f"⚠️ Не удалось отправить уведомление пользователю {target_id} по заявке #{app_id}.")
    await call.message.answer(f"Заявка #{app_id}: {STATUS_RU[new_status]}")
    await call.answer()


@router.callback_query(F.data.startswith("acomment:"))
async def admin_comment_start(call: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True); return
    app_id = int(call.data.split(":", 1)[1])
    await state.update_data(comment_app_id=app_id)
    await state.set_state(AdminStates.COMMENT)
    await call.message.answer(f"Введите комментарий для заявки #{app_id}.")
    await call.answer()


@router.message(AdminStates.COMMENT)
async def admin_comment_save(message: Message, state: FSMContext, bot: Bot) -> None:
    if not is_admin(message.from_user.id): return
    data = await state.get_data(); app_id = data.get("comment_app_id")
    async with Session() as session:
        app = await session.get(Application, app_id)
        if not app:
            await state.clear(); await message.answer("Заявка не найдена."); return
        app.moderator_comment = message.text.strip()
        user = await session.get(User, app.user_id)
        await session.commit()
        target_id = user.telegram_id
    await state.clear()
    try:
        await bot.send_message(target_id, f"Комментарий к заявке <b>#{app_id}</b>:\n{message.text.strip()}")
    except Exception:
        await notify_admins(bot, f"⚠️ Ошибка уведомления по комментарию заявки #{app_id}.")
    await message.answer("Комментарий сохранён.", reply_markup=admin_menu())


@router.message()
async def catch_all(message: Message, state: FSMContext) -> None:
    if await handle_faq_search_message(message, state):
        return
    if message.text and message.text.lower() in {"данные", "мои данные"}:
        await my_data(message)
        return
    await message.answer("Не понял команду. Используйте /help или кнопки главного меню.", reply_markup=main_menu())


async def reminder_job(bot: Bot) -> None:
    now_utc = datetime.now(timezone.utc)
    deadline_raw = await get_setting("deadline")
    event_raw = await get_setting("event_start")
    tz_name = await get_setting("timezone", config.default_timezone) or config.default_timezone
    if not deadline_raw or not event_raw:
        return
    deadline = parse_dt(deadline_raw, tz_name)
    event = parse_dt(event_raw, tz_name)
    if not deadline or not event:
        return
    for label, delta in [("7d", timedelta(days=7)), ("3d", timedelta(days=3)), ("1d", timedelta(days=1)), ("3h", timedelta(hours=3))]:
        target = deadline.astimezone(timezone.utc) - delta
        if abs((target - now_utc).total_seconds()) < 30:
            async with Session() as session:
                ids = [x[0] for x in (await session.execute(select(User.telegram_id).where(User.consent == True))).all()]  # noqa: E712
            for uid in ids:
                try:
                    await bot.send_message(uid, f"⏰ Напоминание: до дедлайна подачи заявки осталось {label}.")
                except Exception:
                    log.exception("Deadline reminder failed for %s", uid)
            await notify_admins(bot, f"⏰ Дедлайн через {label}: {deadline.astimezone(ZoneInfo(tz_name)):%d.%m.%Y %H:%M} ({tz_name}).")
    for label, delta in [("7d", timedelta(days=7)), ("3d", timedelta(days=3)), ("1d", timedelta(days=1))]:
        target = event.astimezone(timezone.utc) - delta
        if abs((target - now_utc).total_seconds()) < 30:
            async with Session() as session:
                ids = [x[0] for x in (await session.execute(select(User.telegram_id).where(User.consent == True))).all()]  # noqa: E712
            for uid in ids:
                try:
                    await bot.send_message(uid, f"📅 До конференции осталось {label}.")
                except Exception:
                    log.exception("Event reminder failed for %s", uid)
            await notify_admins(bot, f"📅 Мероприятие через {label}: {event.astimezone(ZoneInfo(tz_name)):%d.%m.%Y %H:%M} ({tz_name}).")


async def main() -> None:
    if not config.bot_token or "REPLACE_WITH_REAL_TOKEN" in config.bot_token:
        raise RuntimeError("Заполните BOT_TOKEN в .env")
    await init_db()
    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    scheduler.add_job(reminder_job, "interval", seconds=30, args=[bot], id="reminders", replace_existing=True)
    scheduler.start()
    log.info("Bot started")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
