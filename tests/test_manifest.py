"""Проверки манифеста и тумблеров — без сети и без доступа к Google.

Здесь проверяется, что кнопки правильно ОБЪЯВЛЕНЫ: список один, выключенное
не грузится, схемы собираются из полей. Плюс счёт свободных окон — единственная
арифметика в этом сервере, а значит единственное место, где можно молча
ошибиться на час.

Запуск: python -m pytest tests/ -q
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from mcp.server.fastmcp import FastMCP

from gcal_mcp import core, server, table, toggles, tools

ZONE = ZoneInfo("Europe/Moscow")


class FakeClient:
    """Клиент, который не ходит в сеть: отдаёт заранее заданные ответы."""

    def __init__(self, answers: dict[str, object]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []
        self.zone = ZONE
        self.tz = "Europe/Moscow"
        self.calendar_id = "primary"

    def now(self) -> datetime:
        return datetime(2026, 8, 1, 10, 0, tzinfo=ZONE)

    async def get(self, path: str, **kw):
        self.calls.append(("GET", path))
        return self.answers.get(path, {})

    async def post(self, path: str, **kw):
        self.calls.append(("POST", path))
        return self.answers.get(path, {})


# ── один дом ──────────────────────────────────────────────────────────────────

def test_имена_кнопок_не_повторяются():
    names = [t.name for t in tools.TOOLS]
    assert len(names) == len(set(names))


def test_у_каждой_кнопки_есть_описание_и_строчка_для_человека():
    for t in tools.TOOLS:
        assert t.summary and t.description and t.run is not None, t.name


def test_поля_объявлены_известными_типами():
    for t in tools.TOOLS:
        for f in t.fields:
            assert f.kind in tools.KINDS, (t.name, f.name, f.kind)


# ── тумблеры ──────────────────────────────────────────────────────────────────

def test_кнопки_нет_в_файле_значит_включена():
    assert toggles.is_on("list_events", {"free_slots": False}) is True


def test_выключенная_кнопка_не_объявляется():
    chosen = {t.name for t in tools.selected({"delete_event": False})}
    assert "delete_event" not in chosen and "list_events" in chosen


def test_сломанный_файл_не_оставляет_агента_без_кнопок(tmp_path: Path):
    file = tmp_path / "tools.yaml"
    file.write_text("tools: [сломано\n", encoding="utf-8")
    assert toggles.load(file) == {}
    assert len(tools.selected(toggles.load(file))) == len(tools.TOOLS)


# ── сборка сервера ────────────────────────────────────────────────────────────

def _weigh(switches: dict[str, bool]) -> tuple[int, int]:
    mcp = FastMCP("t")
    names = server.register(mcp, switches)
    listed = asyncio.run(mcp.list_tools())
    payload = [{"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
               for t in listed]
    return len(names), len(json.dumps(payload, ensure_ascii=False).encode())


def test_выключенная_кнопка_перестаёт_весить():
    all_count, all_bytes = _weigh({})
    less_count, less_bytes = _weigh({"list_calendars": False, "find_events": False})
    assert less_count == all_count - 2 and less_bytes < all_bytes


def test_схема_собирается_из_полей_манифеста():
    mcp = FastMCP("t")
    server.register(mcp, {})
    listed = {t.name: t for t in asyncio.run(mcp.list_tools())}
    schema = listed["create_event"].inputSchema
    assert schema["required"] == ["summary", "start"]
    assert schema["properties"]["summary"]["description"]


def test_обработчик_получает_настоящую_сигнатуру():
    handler = server._make_handler(tools.by_name()["delete_event"])
    assert list(inspect.signature(handler).parameters) == ["event_id", "calendar_id"]


def test_таблица_показывает_все_кнопки():
    text = table.render({})
    for t in tools.TOOLS:
        assert t.name in text and t.summary in text


# ── время и окна ──────────────────────────────────────────────────────────────

def test_только_дата_значит_событие_на_весь_день():
    c = FakeClient({})
    assert core.to_google_time(c, "2026-08-05") == {"date": "2026-08-05"}


def test_время_без_пояса_получает_рабочий_пояс():
    c = FakeClient({})
    out = core.to_google_time(c, "2026-08-05T10:00")
    assert out["timeZone"] == "Europe/Moscow" and "+03:00" in out["dateTime"]


def test_период_словом_считается_от_сегодня():
    c = FakeClient({})
    lo, hi, label = core.resolve_range(c, "tomorrow")
    assert label == "завтра" and lo.startswith("2026-08-02") and hi.startswith("2026-08-03")


def test_свободные_окна_считаются_между_занятым():
    """Занято 11:00–12:00 и 15:00–16:30 → свободно до, между и после."""
    c = FakeClient({"/freeBusy": {"calendars": {"primary": {"busy": [
        {"start": "2026-08-01T08:00:00Z", "end": "2026-08-01T09:00:00Z"},    # 11–12 МСК
        {"start": "2026-08-01T12:00:00Z", "end": "2026-08-01T13:30:00Z"},    # 15–16:30 МСК
    ]}}}})
    out = asyncio.run(core.free_slots(c, date_from="2026-08-01", date_to="2026-08-02",
                                      min_minutes=30))
    assert "09:00–11:00" in out and "12:00–15:00" in out and "16:30–21:00" in out


def test_короткие_щели_отсекаются():
    c = FakeClient({"/freeBusy": {"calendars": {"primary": {"busy": [
        {"start": "2026-08-01T06:00:00Z", "end": "2026-08-01T07:20:00Z"},   # 09:00–10:20
        {"start": "2026-08-01T07:30:00Z", "end": "2026-08-01T18:00:00Z"},   # 10:30–21:00
    ]}}}})
    out = asyncio.run(core.free_slots(c, date_from="2026-08-01", date_to="2026-08-02",
                                      min_minutes=30))
    assert "10:20–10:30" not in out  # щель в 10 минут — не окно
    assert "нет" in out.lower() or "10:20" not in out


def test_окна_считаются_по_нескольким_календарям_сразу():
    """Занятость складывается: спортзал и работа в разных календарях."""
    c = FakeClient({"/freeBusy": {"calendars": {
        "work": {"busy": [{"start": "2026-08-01T08:00:00Z", "end": "2026-08-01T09:00:00Z"}]},
        "gym": {"busy": [{"start": "2026-08-01T14:00:00Z", "end": "2026-08-01T15:00:00Z"}]},
    }}})
    out = asyncio.run(core.free_slots(c, date_from="2026-08-01", date_to="2026-08-02",
                                      calendars="work, gym", min_minutes=30))
    assert "12:00–17:00" in out and "18:00–21:00" in out


def test_несколько_календарей_разбираются_из_строки():
    assert core._ids("a, b ,c", "x") == ["a", "b", "c"]
    assert core._ids("", "основной") == ["основной"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
