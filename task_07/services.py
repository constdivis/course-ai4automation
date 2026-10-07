from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from openpyxl import Workbook

from db import Application, ApplicationHistory, Session, User

STATUS_RU = {
    "draft": "черновик",
    "submitted": "отправлена",
    "under_review": "на проверке",
    "accepted": "принята",
    "rejected": "отклонена",
    "waitlist": "лист ожидания",
}

FORMATS = {"Доклад", "Слушатель", "Стенд", "Онлайн"}
SECTIONS = ["Искусственный интеллект", "Цифровая экономика", "Образование", "Инженерные системы"]

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def clean_text(value: str) -> str:
    return value.strip()


def validate_email(value: str) -> str | None:
    value = clean_text(value)
    return None if EMAIL_RE.fullmatch(value) else "Введите корректный email, например: ivan.petrov@example.com."


def validate_phone(value: str) -> str | None:
    digits = re.sub(r"\D", "", value)
    if len(digits) < 10:
        return "Телефон должен содержать минимум 10 цифр. Например: +7 916 555-12-34."
    return None


def validate_abstract(text: str) -> list[str]:
    errors: list[str] = []
    length = len(text.strip())
    if length < 1500 or length > 3000:
        errors.append(f"Объём тезисов сейчас {length} знаков, а требуется 1500–3000.")
    lower = text.lower()
    for part in ("цель", "метод", "результат", "вывод"):
        if part not in lower:
            errors.append(f"Не найден раздел/упоминание «{part}». Добавьте его в текст.")
    return errors


def reference_count(text: str) -> int:
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    numbered = sum(bool(re.match(r"^(?:\[?\d+\]?|\d+[.)])\s", x)) for x in lines)
    return max(numbered, len(lines))


def validate_references(text: str) -> list[str]:
    errors: list[str] = []
    count = reference_count(text)
    if count < 3:
        errors.append(f"Найдено источников: {count}. Нужно минимум 3.")
    if not re.search(r"(?:doi\.org/|DOI\s*[:]?\s*10\.\d{4,9}/)", text, re.I):
        errors.append("DOI не найден — это не блокирующая ошибка, но для публикации желательно указать DOI/URL там, где он есть.")
    return errors


def recommend_section(title: str, abstract: str) -> str:
    text = f"{title} {abstract}".lower()
    rules = {
        "Искусственный интеллект": ("нейросет", "llm", "машинн", "ai", "искусственн", "модель"),
        "Цифровая экономика": ("рынок", "финанс", "эконом", "бизнес", "платформ"),
        "Образование": ("образован", "обучен", "студент", "университет", "педагог"),
        "Инженерные системы": ("энерг", "робот", "датчик", "оборудован", "система", "инженер"),
    }
    scores = {section: sum(token in text for token in tokens) for section, tokens in rules.items()}
    return max(scores, key=scores.get) if max(scores.values()) else "Искусственный интеллект"


def google_calendar_url(title: str, start: datetime, end: datetime, description: str) -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    s = start.astimezone(timezone.utc).strftime(fmt)
    e = end.astimezone(timezone.utc).strftime(fmt)
    return (
        "https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(title)}&dates={s}/{e}&details={quote(description)}"
    )


def make_ics(title: str, start: datetime, end: datetime, description: str) -> bytes:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    s = start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    e = end.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Conference Bot//RU\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:conference-{stamp}@bot\r\nDTSTAMP:{stamp}\r\nDTSTART:{s}\r\nDTEND:{e}\r\n"
        f"SUMMARY:{title.replace(chr(10), ' ')}\r\nDESCRIPTION:{description.replace(chr(10), ' ')}\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    return text.encode("utf-8")


def export_csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    fields = list(rows[0].keys()) if rows else ["id", "full_name", "email", "status", "section", "title"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def export_xlsx_bytes(rows: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Applications"
    fields = list(rows[0].keys()) if rows else ["id", "full_name", "email", "status", "section", "title"]
    ws.append(fields)
    for row in rows:
        ws.append([row.get(field, "") for field in fields])
    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


async def save_status_change(application_id: int, old: str | None, new: str, changed_by: int, comment: str | None = None) -> None:
    async with Session() as session:
        session.add(ApplicationHistory(
            application_id=application_id,
            old_status=old,
            new_status=new,
            changed_by=changed_by,
            comment=comment,
        ))
        await session.commit()


async def application_rows() -> list[dict]:
    async with Session() as session:
        result = await session.execute(
            __import__('sqlalchemy').select(Application, User).join(User, Application.user_id == User.id).order_by(Application.id.desc())
        )
        rows = []
        for app, user in result.all():
            rows.append({
                "id": app.id,
                "full_name": app.full_name,
                "email": app.email,
                "phone": app.phone,
                "organization": app.organization,
                "position": app.position,
                "country_city": app.country_city,
                "format": app.type,
                "section": app.section,
                "title": app.title,
                "abstract": app.abstract,
                "references": app.references,
                "coauthors": app.coauthors,
                "status": STATUS_RU.get(app.status, app.status),
                "telegram_id": user.telegram_id,
                "created_at": app.created_at.isoformat() if app.created_at else "",
            })
        return rows
