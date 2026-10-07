from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncAttrs, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import config


class Base(AsyncAttrs, DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(50))
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    applications: Mapped[list["Application"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    tickets: Mapped[list["Ticket"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Application(Base):
    __tablename__ = "applications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    section: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(500))
    abstract: Mapped[str] = mapped_column(Text)
    references: Mapped[str] = mapped_column(Text)
    coauthors: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(50), default="")
    organization: Mapped[str] = mapped_column(String(500), default="")
    position: Mapped[str] = mapped_column(String(255), default="")
    country_city: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moderator_comment: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="applications")
    history: Mapped[list["ApplicationHistory"]] = relationship(back_populates="application", cascade="all, delete-orphan")


class ApplicationHistory(Base):
    __tablename__ = "application_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), index=True)
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="history")


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(100))
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=False)


class Ticket(Base):
    __tablename__ = "tickets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[str] = mapped_column(String(50))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open")
    admin_comment: Mapped[str | None] = mapped_column(Text)
    attachment_file_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped[User] = relationship(back_populates="tickets")


class FAQ(Base):
    __tablename__ = "faq"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(100), index=True)
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str] = mapped_column(Text)
    keywords: Mapped[str] = mapped_column(Text, default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Admin(Base):
    __tablename__ = "admins"
    telegram_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[str] = mapped_column(String(32), default="moderator")


engine = create_async_engine(config.database_url, future=True, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with Session() as session:
        await seed_defaults(session)
        await session.commit()


async def seed_defaults(session: AsyncSession) -> None:
    defaults = {
        "deadline": config.default_deadline,
        "event_start": config.default_event_start,
        "event_end": config.default_event_end,
        "timezone": config.default_timezone,
        "is_open": "true",
        "conference_name": "Научно-практическая конференция «Цифровая наука — 2026»",
    }
    for key, value in defaults.items():
        found = await session.get(Setting, key)
        if found is None:
            session.add(Setting(key=key, value=value))

    existing = await session.scalar(select(FAQ.id).limit(1))
    if existing is None:
        samples = [
            FAQ(category="Участие", question="Кто может подать заявку?", answer="Преподаватели, исследователи, аспиранты и специалисты из организаций-партнёров. Формат участия выбирается при заполнении заявки.", keywords="кто, участник, подать заявку, участие"),
            FAQ(category="Даты", question="Когда заканчивается приём заявок?", answer="По умолчанию приём открыт до 20 ноября 2026 года, 23:59 по Europe/Moscow. Точную дату можно проверить командой /deadline.", keywords="дедлайн, дата, прием, заявки"),
            FAQ(category="Тезисы", question="Какой объём тезисов?", answer="От 1500 до 3000 знаков. Желательная структура: цель, методы, результаты и выводы.", keywords="тезисы, объем, знаки, структура"),
            FAQ(category="Литература", question="Сколько источников нужно?", answer="Не менее трёх источников. Бот проверяет количество позиций и пытается найти DOI/URL.", keywords="литература, источники, doi"),
            FAQ(category="Формат", question="Можно участвовать онлайн?", answer="Да. В заявке доступен формат «Онлайн». Ссылка на подключение будет отправлена участникам после подтверждения программы.", keywords="онлайн, дистанционно, zoom"),
            FAQ(category="Сертификаты", question="Как получить сертификат?", answer="После мероприятия в кабинете участника появляется запрос сертификата. Бот формирует карточку участника и статус выдачи.", keywords="сертификат, свидетельство"),
        ]
        session.add_all(samples)

    for admin_id in config.admin_ids:
        found = await session.get(Admin, admin_id)
        if found is None:
            session.add(Admin(telegram_id=admin_id, role="admin"))


async def get_setting(key: str, default: str | None = None) -> str | None:
    async with Session() as session:
        obj = await session.get(Setting, key)
        return obj.value if obj else default


async def set_setting(key: str, value: str) -> None:
    async with Session() as session:
        obj = await session.get(Setting, key)
        if obj:
            obj.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()
