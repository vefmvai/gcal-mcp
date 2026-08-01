"""Функции-«кнопки» Календаря — чистая логика поверх CalendarClient, без MCP.

Каждая функция принимает клиент и возвращает готовый человекочитаемый текст:
и MCP-сервер, и встроенная обёртка агента просто оборачивают этот текст.

Событие ≠ задача. Событие занимает слот времени (встреча, эфир, тренировка);
дело без жёсткого слота живёт в списке задач, а не здесь.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .client import CalendarClient

# ── время: приём от модели и вывод человеку ──────────────────────────────────


def to_google_time(client: CalendarClient, value: str) -> dict[str, str]:
    """Строка от модели → поле start/end Google.

    «2026-07-29» (только дата) → событие на весь день.
    «2026-07-29T10:00» → привязка ко времени; без пояса подставляем рабочий.
    """
    value = str(value).strip()
    if len(value) == 10 and value[4] == "-" and value[7] == "-":
        return {"date": value}
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=client.zone)
    return {"dateTime": dt.isoformat(), "timeZone": client.tz}


def human_when(client: CalendarClient, event: dict[str, Any]) -> str:
    start = event.get("start", {})
    end = event.get("end", {})
    if start.get("date"):
        return f"{start['date']} (весь день)"
    try:
        sd = datetime.fromisoformat(start["dateTime"]).astimezone(client.zone)
        out = sd.strftime("%d.%m %H:%M")
        if end.get("dateTime"):
            ed = datetime.fromisoformat(end["dateTime"]).astimezone(client.zone)
            out += "–" + ed.strftime("%H:%M")
        return out
    except (KeyError, ValueError):
        return start.get("dateTime", "?")


def brief(client: CalendarClient, event: dict[str, Any]) -> str:
    summary = event.get("summary") or "(без названия)"
    location = f" @ {event['location']}" if event.get("location") else ""
    return f"[{event['id']}] {human_when(client, event)} — {summary}{location}"


def resolve_range(client: CalendarClient, preset: str = "", date_from: str = "",
                  date_to: str = "") -> tuple[str, str, str]:
    """Вернуть (timeMin, timeMax, подпись) из слова или пары дат."""
    word = (preset or "").strip().lower()
    today = client.now().replace(hour=0, minute=0, second=0, microsecond=0)
    if word in ("today", "сегодня"):
        return today.isoformat(), (today + timedelta(days=1)).isoformat(), "сегодня"
    if word in ("tomorrow", "завтра"):
        start = today + timedelta(days=1)
        return start.isoformat(), (start + timedelta(days=1)).isoformat(), "завтра"
    if word in ("week", "неделя", "7 days", "") and not (date_from or date_to):
        return today.isoformat(), (today + timedelta(days=7)).isoformat(), "неделя"

    def edge(value: str, default: datetime) -> datetime:
        if not value:
            return default
        g = to_google_time(client, value)
        if "date" in g:
            return datetime.fromisoformat(g["date"]).replace(tzinfo=client.zone)
        return datetime.fromisoformat(g["dateTime"])

    start = edge(date_from, today)
    end = edge(date_to, start + timedelta(days=1))
    return start.isoformat(), end.isoformat(), f"{start.date()}…{end.date()}"


def _ids(calendars: str, default: str) -> list[str]:
    """«a, b» → ['a','b']; пусто → календарь по умолчанию."""
    parts = [p.strip() for p in str(calendars or "").split(",") if p.strip()]
    return parts or [default]


# ── чтение ───────────────────────────────────────────────────────────────────

async def list_calendars(client: CalendarClient) -> str:
    """Все календари, к которым есть доступ, с их id."""
    data = await client.get("/users/me/calendarList")
    items = (data or {}).get("items", [])
    if not items:
        return "Календарей не видно."
    lines = [f"Календари ({len(items)}):"]
    for c in items:
        mark = " ← основной" if c.get("primary") else ""
        access = c.get("accessRole", "")
        lines.append(f"  [{c.get('id')}] {c.get('summary')}{mark} ({access})")
    lines.append("id нужен, чтобы смотреть или заводить события не только в основном.")
    return "\n".join(lines)


async def list_events(client: CalendarClient, range: str = "", date_from: str = "",
                      date_to: str = "", limit: int = 50, calendars: str = "") -> str:
    """События за период. По умолчанию — неделя вперёд в основном календаре."""
    time_min, time_max, label = resolve_range(client, range, date_from, date_to)
    limit = min(int(limit or 50), 250)
    lines: list[str] = []
    total = 0
    targets = _ids(calendars, client.calendar_id)
    for calendar_id in targets:
        data = await client.get(
            f"/calendars/{calendar_id}/events",
            params={"timeMin": time_min, "timeMax": time_max, "singleEvents": "true",
                    "orderBy": "startTime", "maxResults": limit},
        )
        items = (data or {}).get("items", [])
        total += len(items)
        if len(targets) > 1 and items:
            lines.append(f"— {calendar_id}:")
        lines += [("  " if len(targets) > 1 else "") + brief(client, e) for e in items]
    if not total:
        return f"На «{label}» событий нет."
    return f"События ({label}, {total}):\n" + "\n".join(lines)


async def find_events(client: CalendarClient, query: str, days_ahead: int = 180,
                      days_back: int = 30, limit: int = 20, calendars: str = "") -> str:
    """Найти событие по словам в названии или описании — когда id неизвестен."""
    if not query:
        return "Не сказано, что искать."
    now = client.now()
    time_min = (now - timedelta(days=int(days_back or 30))).isoformat()
    time_max = (now + timedelta(days=int(days_ahead or 180))).isoformat()
    found: list[str] = []
    for calendar_id in _ids(calendars, client.calendar_id):
        data = await client.get(
            f"/calendars/{calendar_id}/events",
            params={"q": query, "timeMin": time_min, "timeMax": time_max,
                    "singleEvents": "true", "orderBy": "startTime",
                    "maxResults": min(int(limit or 20), 100)},
        )
        found += [brief(client, e) for e in (data or {}).get("items", [])]
    if not found:
        return f"По запросу «{query}» событий не нашлось."
    return f"Найдено ({len(found)}) по запросу «{query}»:\n" + "\n".join(found)


async def free_windows(client: CalendarClient, range: str = "", date_from: str = "",
                       date_to: str = "", calendars: str = "",
                       min_minutes: int = 30, day_start: str = "09:00",
                       day_end: str = "21:00"
                       ) -> tuple[str, dict[str, list[tuple[datetime, datetime]]]]:
    """Свободные окна числами: день (`ГГГГ-ММ-ДД`) → список интервалов.

    Отделено от `free_slots` не для красоты. Свободные часы нужны не только
    человеку глазами: по ним считается перегруз дня — «дел на шесть часов,
    а свободно два». Считать это разбором готовой строки значит завести
    второй дом у одной арифметики; строку рисует `free_slots` вот из этого.
    """
    time_min, time_max, label = resolve_range(client, range, date_from, date_to)
    targets = _ids(calendars, client.calendar_id)
    data = await client.post(
        "/freeBusy",
        json={"timeMin": time_min, "timeMax": time_max,
              "items": [{"id": c} for c in targets]},
    )
    busy: list[tuple[datetime, datetime]] = []
    for info in (data or {}).get("calendars", {}).values():
        for slot in info.get("busy", []):
            busy.append((
                datetime.fromisoformat(slot["start"].replace("Z", "+00:00")).astimezone(client.zone),
                datetime.fromisoformat(slot["end"].replace("Z", "+00:00")).astimezone(client.zone),
            ))
    busy.sort()

    start_h, start_m = (int(x) for x in str(day_start or "09:00").split(":"))
    end_h, end_m = (int(x) for x in str(day_end or "21:00").split(":"))
    begin = datetime.fromisoformat(time_min)
    finish = datetime.fromisoformat(time_max)
    min_minutes = max(int(min_minutes or 30), 1)

    windows: dict[str, list[tuple[datetime, datetime]]] = {}
    day = begin.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < finish:
        window_start = max(day.replace(hour=start_h, minute=start_m), begin)
        window_end = min(day.replace(hour=end_h, minute=end_m), finish)
        cursor = window_start
        free_today: list[tuple[datetime, datetime]] = []
        for slot_start, slot_end in busy:
            if slot_end <= cursor or slot_start >= window_end:
                continue
            if slot_start - cursor >= timedelta(minutes=min_minutes):
                free_today.append((cursor, slot_start))
            cursor = max(cursor, slot_end)
        if window_end - cursor >= timedelta(minutes=min_minutes):
            free_today.append((cursor, window_end))
        if free_today and window_end > window_start:
            windows[f"{day:%Y-%m-%d}"] = free_today
        day += timedelta(days=1)
    return label, windows


async def free_slots(client: CalendarClient, range: str = "", date_from: str = "",
                     date_to: str = "", calendars: str = "",
                     min_minutes: int = 30, day_start: str = "09:00",
                     day_end: str = "21:00") -> str:
    """Свободные окна: что НЕ занято по всем указанным календарям.

    Планировать день по списку занятого — значит считать в уме. Здесь Google
    отдаёт занятость сразу по нескольким календарям, а окна между ней
    считаются тут же.
    """
    label, windows = await free_windows(
        client, range, date_from, date_to, calendars, min_minutes, day_start, day_end
    )
    lines = [
        f"  {datetime.fromisoformat(day):%d.%m}: "
        + ", ".join(f"{начало:%H:%M}–{конец:%H:%M}" for начало, конец in окна)
        for day, окна in windows.items()
    ]
    if not lines:
        return f"Свободных окон от {min_minutes} мин на «{label}» нет."
    header = f"Свободные окна ({label}, от {min_minutes} мин, {day_start}–{day_end}):"
    return header + "\n" + "\n".join(lines)


# ── запись ───────────────────────────────────────────────────────────────────

async def create_event(client: CalendarClient, summary: str, start: str, end: str = "",
                       description: str = "", location: str = "",
                       calendar_id: str = "") -> str:
    """Создать событие. Без end — час от начала (или сутки для «весь день»)."""
    begin = to_google_time(client, start)
    if end:
        finish = to_google_time(client, end)
    elif "date" in begin:
        nxt = datetime.fromisoformat(begin["date"]) + timedelta(days=1)
        finish = {"date": nxt.date().isoformat()}
    else:
        ed = datetime.fromisoformat(begin["dateTime"]) + timedelta(hours=1)
        finish = {"dateTime": ed.isoformat(), "timeZone": client.tz}
    payload: dict[str, Any] = {"summary": summary, "start": begin, "end": finish}
    if description:
        payload["description"] = description
    if location:
        payload["location"] = location
    target = calendar_id or client.calendar_id
    event = await client.post(f"/calendars/{target}/events", json=payload)
    return f"Создано событие {brief(client, event)}"


async def update_event(client: CalendarClient, event_id: str, summary: str = "",
                       start: str = "", end: str = "", description: str = "",
                       location: str = "", calendar_id: str = "") -> str:
    """Перенести или изменить событие. Меняются только переданные поля."""
    payload: dict[str, Any] = {}
    if start:
        payload["start"] = to_google_time(client, start)
    if end:
        payload["end"] = to_google_time(client, end)
    for key, value in (("summary", summary), ("description", description),
                       ("location", location)):
        if value:
            payload[key] = value
    if not payload:
        return "Нечего менять — не передано ни одного поля."
    target = calendar_id or client.calendar_id
    event = await client.patch(f"/calendars/{target}/events/{event_id}", json=payload)
    return f"Обновлено: {brief(client, event)}"


async def delete_event(client: CalendarClient, event_id: str, calendar_id: str = "") -> str:
    """Убрать событие из календаря."""
    target = calendar_id or client.calendar_id
    await client.delete(f"/calendars/{target}/events/{event_id}")
    return f"Событие {event_id} удалено."
