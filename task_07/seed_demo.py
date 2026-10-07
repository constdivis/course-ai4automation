"""Добавляет демонстрационную заявку с правдоподобными данными для отладки."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from db import Application, ApplicationHistory, Session, User, init_db


async def main() -> None:
    await init_db()
    async with Session() as session:
        user = await session.scalar(__import__('sqlalchemy').select(User).where(User.telegram_id == 999000111))
        if not user:
            user = User(telegram_id=999000111, username="demo_participant", first_name="Анна", last_name="Соколова", email="anna.sokolova@example.com", phone="+7 916 555-12-34", consent=True)
            session.add(user)
            await session.flush()
        app = Application(
            user_id=user.id, status="under_review", section="Искусственный интеллект", type="Доклад",
            title="Оценка качества генеративных моделей в университетской аналитике",
            abstract=("Цель исследования — оценить практическую эффективность методов интеллектуального анализа данных для мониторинга образовательных процессов в университете. " * 5)[:2250] + "\nВыводы: результаты подтверждают применимость подхода.",
            references="1. Иванов И.И. Цифровая аналитика. М., 2024.\n2. Петров П.П. Машинное обучение. СПб., 2025.\n3. Smith J. Data-driven education. 2023. DOI: 10.1234/example.2023.42",
            coauthors="Петров Алексей Николаевич",
            full_name="Соколова Анна Дмитриевна", email=user.email, phone=user.phone,
            organization="Национальный исследовательский университет «Высшая школа экономики»",
            position="старший научный сотрудник", country_city="Россия, Москва",
            submitted_at=datetime.now(timezone.utc),
        )
        session.add(app)
        await session.flush()
        session.add(ApplicationHistory(application_id=app.id, old_status="draft", new_status="under_review", changed_by=999000111, comment="Демонстрационная запись для отладки"))
        await session.commit()
        print(f"Создана demo-заявка #{app.id} для telegram_id=999000111")


if __name__ == "__main__":
    asyncio.run(main())
