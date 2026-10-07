# Conference Telegram Bot

MVP Telegram-бота по `tz.md` на Python 3.11+, aiogram 3.x, FSM, SQLAlchemy, SQLite/PostgreSQL и APScheduler.

## Что реализовано

- `/start`, `/help`, `/faq`, `/feedback`, `/apply`, `/status`, `/deadline`, `/countdown`, `/materials`, `/calendar`, `/admin`, `/menu`, `/cancel`, `/support`, `/my_data`.
- FSM из ТЗ: 15 шагов заявки, отмена, валидация email/телефона/тезисов/литературы.
- SQLite по умолчанию, PostgreSQL через `DATABASE_URL`.
- Хранение вложений через Telegram `file_id`.
- Статусы `draft`, `submitted`, `under_review`, `accepted`, `rejected`, `waitlist`.
- История изменений и комментарии модератора.
- Уведомления о подаче, изменении статуса, дедлайнах и мероприятии.
- FAQ с категориями и поиском.
- Тикеты обратной связи с опциональным вложением.
- Админка: заявки, статистика, CSV/XLSX, рассылка, настройки дат, тикеты.
- `.ics` и ссылка Google Calendar.
- Рекомендация секции по ключевым словам и проверка на очевидные проблемы в тезисах.
- `seed_demo.py` для правдоподобной записи заявки.

## Быстрый запуск

1. Установите Python 3.11+.
2. Создайте окружение:

```bash
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows PowerShell
# .venv\\Scripts\\Activate.ps1
```

3. Установите зависимости:

```bash
pip install --upgrade -r requirements.txt
```

4. Создайте `.env` из `.env.example` и впишите реальный токен от @BotFather и свой Telegram ID в `ADMIN_IDS`.

5. Запустите:

```bash
python bot.py
```

При первом старте создастся `conference_bot.db` и тестовые FAQ/настройки.

## Проверка демо-данных

```bash
python seed_demo.py
```

Создастся демонстрационный пользователь с `telegram_id=999000111` и заявка в статусе `На проверке`.

## PostgreSQL

Создайте БД и замените `DATABASE_URL`, например:

```env
DATABASE_URL=postgresql+asyncpg://conference:secret@localhost:5432/conference_bot
```

После этого запускайте `python bot.py` так же. Таблицы будут созданы автоматически.

## Важные замечания перед production

- Включите webhook/HTTPS или используйте polling за reverse proxy.
- Не храните `.env` в Git.
- Для крупных рассылок нужен rate limit/очередь.
- Для нескольких экземпляров бота FSM и scheduler лучше вынести в Redis/отдельный worker.
- Для реального удаления персональных данных добавьте команду удаления, каскадно удаляющую пользователя, заявки и тикеты.
- AI-помощник в этом MVP — локальная эвристическая проверка; подключение внешней LLM не включено.


Примечание по SQLAlchemy asyncio: зависимость `SQLAlchemy[asyncio]` включает `greenlet`. Если окружение уже было установлено по старому архиву, выполните `pip install -U "SQLAlchemy[asyncio]>=2.0,<3"` и затем перезапустите бота.

## Независимый HTML-экспорт БД

Файл `export_html.py` не зависит от Telegram-бота и использует только стандартную библиотеку Python. Он открывает `conference_bot.db` в режиме read-only и создаёт самодостаточный HTML-отчёт с таблицами всех найденных таблиц БД. В отчёте есть поиск по содержимому и сводка по статусам заявок.

Обычный экспорт:

```bash
python export_html.py
```

Результат появится в каталоге `exports/` с именем вида `conference_report_20261007_184500.html`.

Можно указать путь к БД и точное имя файла:

```bash
python export_html.py --db conference_bot.db --output exports/latest.html
```

Для отчёта без email, телефонов и Telegram ID:

```bash
python export_html.py --no-pii
```

Модуль удобно запускать вручную столько раз, сколько требуется: каждый запуск создаёт новый HTML-файл.
