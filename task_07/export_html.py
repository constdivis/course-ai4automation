#!/usr/bin/env python3
"""Standalone export of conference_bot.db to a self-contained HTML report.

This module deliberately uses only Python's standard library and does not import
or depend on the Telegram bot code. It can be run manually or from cron/Task
Scheduler while the bot is stopped or running; SQLite is opened read-only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import sqlite3
from pathlib import Path
from typing import Iterable, Sequence

STATUS_LABELS = {
    "draft": "Черновик",
    "submitted": "Отправлена",
    "under_review": "На проверке",
    "accepted": "Принята",
    "rejected": "Отклонена",
    "waitlist": "Лист ожидания",
}

TABLE_ORDER = [
    "applications",
    "users",
    "application_history",
    "tickets",
    "notifications",
    "faq",
    "settings",
    "admins",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Экспорт conference_bot.db в HTML")
    parser.add_argument(
        "--db",
        default="conference_bot.db",
        help="Путь к SQLite БД (по умолчанию: conference_bot.db)",
    )
    parser.add_argument(
        "--output-dir",
        default="exports",
        help="Каталог для HTML-файлов (по умолчанию: exports)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Точное имя/путь выходного HTML вместо автоматического имени",
    )
    parser.add_argument(
        "--no-pii",
        action="store_true",
        help="Скрыть email, телефон и Telegram ID в отчёте",
    )
    return parser.parse_args()


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def display_value(column: str, value: object, mask_pii: bool = False) -> str:
    if value is None:
        return "<span class=\"muted\">—</span>"

    text = str(value)

    if mask_pii and column in {"telegram_id", "email", "phone"}:
        if column == "email" and "@" in text:
            local, domain = text.split("@", 1)
            text = (local[:1] + "***@" + domain) if local else "***@" + domain
        elif column == "phone":
            digits = "".join(ch for ch in text if ch.isdigit())
            text = "***" + digits[-4:] if len(digits) >= 4 else "***"
        else:
            text = "***" + text[-4:]

    if column == "status":
        label = STATUS_LABELS.get(text, text)
        return f'<span class="status status-{html.escape(text, quote=True)}">{html.escape(label)}</span>'

    # Readable multiline cells without changing data.
    return html.escape(text).replace("\n", "<br>")


def fetch_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    names = [r[0] for r in rows]
    ordered = [name for name in TABLE_ORDER if name in names]
    ordered.extend(name for name in names if name not in ordered)
    return ordered


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({quote_identifier(table)})").fetchall()
    return [r[1] for r in rows]


def table_rows(conn: sqlite3.Connection, table: str, columns: Sequence[str]) -> list[tuple]:
    order = ""
    for candidate in ("created_at", "submitted_at", "updated_at", "send_at", "id"):
        if candidate in columns:
            order = f" ORDER BY {quote_identifier(candidate)} DESC"
            break
    return conn.execute(
        f"SELECT * FROM {quote_identifier(table)}{order}"
    ).fetchall()


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0])


def applications_stats(conn: sqlite3.Connection) -> tuple[int, list[tuple[str, int]]]:
    if "applications" not in fetch_tables(conn):
        return 0, []
    total = count_rows(conn, "applications")
    rows = conn.execute(
        "SELECT COALESCE(status, ''), COUNT(*) FROM applications GROUP BY status ORDER BY COUNT(*) DESC"
    ).fetchall()
    return total, rows


def render_table(conn: sqlite3.Connection, table: str, mask_pii: bool) -> str:
    columns = table_columns(conn, table)
    rows = table_rows(conn, table, columns)

    head = "".join(f"<th>{html.escape(col)}</th>" for col in columns)
    body_parts: list[str] = []
    for row in rows:
        cells = "".join(
            f"<td data-label=\"{html.escape(col, quote=True)}\">{display_value(col, value, mask_pii)}</td>"
            for col, value in zip(columns, row)
        )
        body_parts.append(f"<tr>{cells}</tr>")

    body = "\n".join(body_parts) or f'<tr><td colspan="{max(1, len(columns))}" class="empty">Нет записей</td></tr>'
    return f"""
    <section class=\"table-section\" id=\"table-{html.escape(table)}\">
      <div class=\"section-title\">
        <h2>{html.escape(table)}</h2>
        <span class=\"count\">{len(rows)} записей</span>
      </div>
      <div class=\"table-wrap\">
        <table class=\"data-table\">
          <thead><tr>{head}</tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def render_html(db_path: Path, mask_pii: bool = False) -> str:
    # mode=ro prevents accidental modifications by this module.
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = None
    try:
        tables = fetch_tables(conn)
        total_apps, statuses = applications_stats(conn)
        generated = dt.datetime.now().astimezone().strftime("%d.%m.%Y %H:%M:%S %Z")
        db_mtime = dt.datetime.fromtimestamp(db_path.stat().st_mtime).astimezone().strftime("%d.%m.%Y %H:%M:%S %Z")

        status_cards = "".join(
            f'<div class="status-card"><b>{html.escape(STATUS_LABELS.get(status, status or "Без статуса"))}</b><span>{count}</span></div>'
            for status, count in statuses
        )
        sections = "\n".join(render_table(conn, table, mask_pii) for table in tables)

        nav = "".join(
            f'<a href="#table-{html.escape(table)}">{html.escape(table)}</a>' for table in tables
        )

        return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Conference Bot — экспорт данных</title>
<style>
:root {{ color-scheme: light; --border:#d9e1ea; --text:#1d2733; --muted:#687585; --bg:#f5f7fa; --card:#fff; --accent:#2463eb; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--text); background:var(--bg); line-height:1.45; }}
header {{ background:#173b78; color:#fff; padding:28px 24px; }}
main {{ max-width:1600px; margin:0 auto; padding:24px; }}
h1 {{ margin:0 0 8px; font-size:30px; }}
.meta {{ opacity:.9; font-size:14px; }}
.toolbar {{ position:sticky; top:0; z-index:10; background:rgba(245,247,250,.96); padding:12px 0; backdrop-filter:blur(8px); }}
input {{ width:100%; padding:11px 13px; border:1px solid var(--border); border-radius:10px; font-size:15px; }}
nav {{ display:flex; flex-wrap:wrap; gap:8px; margin:10px 0 22px; }}
nav a {{ color:var(--accent); background:var(--card); padding:7px 10px; border:1px solid var(--border); border-radius:8px; text-decoration:none; font-size:13px; }}
.summary {{ display:flex; flex-wrap:wrap; gap:10px; margin-bottom:18px; }}
.kpi,.status-card {{ background:var(--card); border:1px solid var(--border); border-radius:12px; padding:13px 16px; }}
.kpi span,.status-card span {{ display:block; font-size:24px; font-weight:700; margin-top:2px; }}
.kpi small,.status-card b {{ color:var(--muted); font-size:12px; }}
.table-section {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:16px; margin:16px 0; }}
.section-title {{ display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:12px; }}
.section-title h2 {{ margin:0; font-size:19px; }}
.count {{ color:var(--muted); font-size:13px; }}
.table-wrap {{ overflow:auto; border:1px solid var(--border); border-radius:10px; }}
table {{ border-collapse:collapse; width:100%; min-width:700px; font-size:13px; }}
th,td {{ padding:9px 10px; border-bottom:1px solid var(--border); border-right:1px solid var(--border); vertical-align:top; text-align:left; }}
th:last-child,td:last-child {{ border-right:0; }}
thead th {{ position:sticky; top:58px; background:#eef3f8; z-index:2; white-space:nowrap; }}
tbody tr:last-child td {{ border-bottom:0; }}
tbody tr:hover {{ background:#fafcff; }}
.empty,.muted {{ color:var(--muted); }}
.status {{ display:inline-block; padding:3px 8px; border-radius:999px; font-weight:600; white-space:nowrap; background:#edf1f5; }}
.status-accepted {{ background:#dff6e7; }} .status-rejected {{ background:#fde3e3; }} .status-under_review {{ background:#fff1c9; }}
.status-submitted {{ background:#e0edff; }} .status-waitlist {{ background:#efe4ff; }} .status-draft {{ background:#edf1f5; }}
footer {{ color:var(--muted); font-size:12px; padding:8px 0 30px; }}
@media (max-width:760px) {{ main {{ padding:12px; }} header {{ padding:20px 14px; }} h1 {{ font-size:24px; }} table {{ min-width:0; }} thead {{ display:none; }} table,tbody,tr,td {{ display:block; width:100%; }} tr {{ border-bottom:1px solid var(--border); padding:8px 0; }} td {{ border:0; padding:7px 10px; }} td::before {{ content:attr(data-label); display:block; font-weight:700; color:var(--muted); margin-bottom:2px; }} }}
</style>
</head>
<body>
<header>
  <main style="padding:0;">
    <h1>Экспорт данных конференционного Telegram-бота</h1>
    <div class="meta">База: {html.escape(str(db_path))} · Сформировано: {html.escape(generated)} · Изменение БД: {html.escape(db_mtime)}</div>
  </main>
</header>
<main>
  <div class="toolbar"><input id="filter" placeholder="Фильтр по текущему отчёту…" oninput="filterTables(this.value)"></div>
  <nav>{nav}</nav>
  <div class="summary">
    <div class="kpi"><small>Заявок</small><span>{total_apps}</span></div>
    <div class="kpi"><small>Таблиц</small><span>{len(tables)}</span></div>
    {status_cards}
  </div>
  {sections}
  <footer>Отчёт сформирован независимым модулем export_html.py. Для записи в БД доступ не требуется.</footer>
</main>
<script>
function filterTables(query) {{
  const q = query.trim().toLowerCase();
  document.querySelectorAll('.data-table tbody tr').forEach(row => {{
    row.style.display = !q || row.innerText.toLowerCase().includes(q) ? '' : 'none';
  }});
}}
</script>
</body>
</html>
"""
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"База данных не найдена: {db_path.resolve()}")
    if not db_path.is_file():
        raise SystemExit(f"Указанный путь не является файлом: {db_path.resolve()}")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.output:
        output_path = Path(args.output)
        if output_path.parent != Path('.'):
            output_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        stamp = dt.datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"conference_report_{stamp}.html"

    content = render_html(db_path, mask_pii=args.no_pii)
    output_path.write_text(content, encoding="utf-8")

    print(f"HTML-отчёт сохранён: {output_path.resolve()}")


if __name__ == "__main__":
    main()
