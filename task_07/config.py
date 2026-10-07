from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _parse_ids(value: str | None) -> set[int]:
    result: set[int] = set()
    for raw in (value or "").split(","):
        raw = raw.strip()
        if raw:
            result.add(int(raw))
    return result


@dataclass(frozen=True)
class Config:
    bot_token: str
    admin_ids: set[int]
    database_url: str
    default_timezone: str
    default_deadline: str
    default_event_start: str
    default_event_end: str
    support_username: str
    support_email: str
    export_dir: Path = Path("exports")
    log_dir: Path = Path("logs")


config = Config(
    bot_token=os.getenv("BOT_TOKEN", ""),
    admin_ids=_parse_ids(os.getenv("ADMIN_IDS")),
    database_url=os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./conference_bot.db"),
    default_timezone=os.getenv("DEFAULT_TIMEZONE", "Europe/Moscow"),
    default_deadline=os.getenv("DEFAULT_DEADLINE", "2026-11-20T23:59:00+03:00"),
    default_event_start=os.getenv("DEFAULT_EVENT_START", "2026-12-05T09:30:00+03:00"),
    default_event_end=os.getenv("DEFAULT_EVENT_END", "2026-12-06T18:00:00+03:00"),
    support_username=os.getenv("SUPPORT_USERNAME", "@conference_support"),
    support_email=os.getenv("SUPPORT_EMAIL", "org@example.org"),
)
