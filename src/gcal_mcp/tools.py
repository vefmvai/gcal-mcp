"""Манифест кнопок Календаря — единственное место, где объявлен их список.

Форма та же, что у соседнего сервера задач, и по той же причине: обёрток
две (отдельный процесс для внешнего мира и встроенная для агента), а список
кнопок обязан быть один. Разъезжаются именно списки, объявленные дважды.

У каждой кнопки есть `summary` — строчка для человека. Из неё печатается
таблица (`table.py`), и печатается, а не пишется руками: рукописная копия
списка разошлась бы с настоящим.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import core, toggles
from .client import CalendarClient

KINDS = ("str", "int", "bool")


@dataclass(frozen=True)
class Field:
    name: str
    kind: str = "str"
    description: str = ""
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class Tool:
    name: str
    summary: str
    description: str
    run: Callable[[CalendarClient, dict[str, Any]], Awaitable[str]]
    fields: tuple[Field, ...] = ()


def _text(args: dict[str, Any], name: str, default: str = "") -> str:
    value = args.get(name)
    return str(value) if value not in (None, "") else default


def _int(args: dict[str, Any], name: str, default: int) -> int:
    try:
        return int(args.get(name) or default)
    except (TypeError, ValueError):
        return default


_RANGE = Field("range", description="today / tomorrow / week — быстрый период")
_FROM = Field("date_from", description="Начало периода: «2026-08-05» или «2026-08-05T10:00»")
_TO = Field("date_to", description="Конец периода в том же формате")
_CALENDARS = Field("calendars", description="id календарей через запятую; пусто — основной")

TOOLS: tuple[Tool, ...] = (
    Tool(
        name="list_calendars",
        summary="Показать все доступные календари и их id",
        description=(
            "Все календари, к которым есть доступ: свои, общие и расшаренные, "
            "с их id и уровнем доступа. Нужен, чтобы смотреть занятость не только "
            "в основном календаре — тренировки, семейный, рабочий часто лежат в своих."
        ),
        run=lambda c, a: core.list_calendars(c),
    ),
    Tool(
        name="list_events",
        summary="Показать события за период",
        description=(
            "События календаря на период: range = today / tomorrow / week "
            "(по умолчанию неделя вперёд) либо произвольный отрезок через date_from "
            "и date_to. Это способ узнать, что уже занято по времени."
        ),
        fields=(_RANGE, _FROM, _TO,
                Field("limit", "int", "Сколько событий вернуть", default=50), _CALENDARS),
        run=lambda c, a: core.list_events(
            c, _text(a, "range"), _text(a, "date_from"), _text(a, "date_to"),
            _int(a, "limit", 50), _text(a, "calendars"),
        ),
    ),
    Tool(
        name="find_events",
        summary="Найти событие по словам в названии",
        description=(
            "Поиск события по словам, когда id неизвестен, а листать период долго: "
            "«когда у меня был эфир с Зоей». Ищет и назад, и вперёд по времени."
        ),
        fields=(
            Field("query", required=True, description="Слова из названия или описания"),
            Field("days_ahead", "int", "На сколько дней смотреть вперёд", default=180),
            Field("days_back", "int", "На сколько дней смотреть назад", default=30),
            Field("limit", "int", "Сколько событий вернуть", default=20),
            _CALENDARS,
        ),
        run=lambda c, a: core.find_events(
            c, _text(a, "query"), _int(a, "days_ahead", 180), _int(a, "days_back", 30),
            _int(a, "limit", 20), _text(a, "calendars"),
        ),
    ),
    Tool(
        name="free_slots",
        summary="Найти свободные окна в дне",
        description=(
            "Свободные промежутки: что НЕ занято, сразу по нескольким календарям. "
            "Для планирования дня это прямой ответ, а не список занятого, который "
            "надо вычитать в уме. min_minutes отсекает щели короче нужного."
        ),
        fields=(
            _RANGE, _FROM, _TO, _CALENDARS,
            Field("min_minutes", "int", "Минимальная длина окна в минутах", default=30),
            Field("day_start", description="С какого часа считать день, «09:00»", default="09:00"),
            Field("day_end", description="До какого часа считать день, «21:00»", default="21:00"),
        ),
        run=lambda c, a: core.free_slots(
            c, _text(a, "range"), _text(a, "date_from"), _text(a, "date_to"),
            _text(a, "calendars"), _int(a, "min_minutes", 30),
            _text(a, "day_start", "09:00"), _text(a, "day_end", "21:00"),
        ),
    ),
    Tool(
        name="create_event",
        summary="Создать событие",
        description=(
            "Создать то, что привязано ко времени: встреча, эфир, тренировка, блок "
            "«не трогать». Дело без жёсткого слота — в список задач, а не сюда. "
            "start и end — «2026-08-05T10:00» (часовой пояс подставится сам) либо "
            "только дата «2026-08-05» для события на весь день. Без end — час от начала."
        ),
        fields=(
            Field("summary", required=True, description="Название события"),
            Field("start", required=True, description="Начало"),
            Field("end", description="Конец; без него — час от начала"),
            Field("description", description="Описание"),
            Field("location", description="Место"),
            Field("calendar_id", description="В какой календарь; пусто — основной"),
        ),
        run=lambda c, a: core.create_event(
            c, _text(a, "summary"), _text(a, "start"), _text(a, "end"),
            _text(a, "description"), _text(a, "location"), _text(a, "calendar_id"),
        ),
    ),
    Tool(
        name="update_event",
        summary="Перенести или изменить событие",
        description=(
            "Изменить существующее событие по id (берётся из list_events или "
            "find_events). Меняются только переданные поля: start/end — перенос, "
            "summary — название, description, location."
        ),
        fields=(
            Field("event_id", required=True, description="id события"),
            Field("summary", description="Новое название"),
            Field("start", description="Новое начало"),
            Field("end", description="Новый конец"),
            Field("description", description="Новое описание"),
            Field("location", description="Новое место"),
            Field("calendar_id", description="В каком календаре лежит; пусто — основной"),
        ),
        run=lambda c, a: core.update_event(
            c, _text(a, "event_id"), _text(a, "summary"), _text(a, "start"),
            _text(a, "end"), _text(a, "description"), _text(a, "location"),
            _text(a, "calendar_id"),
        ),
    ),
    Tool(
        name="delete_event",
        summary="Удалить событие",
        description=(
            "Убрать событие по id. Отменённая встреча или ошибочный слот не должны "
            "висеть в календаре и врать про занятость."
        ),
        fields=(
            Field("event_id", required=True, description="id события"),
            Field("calendar_id", description="В каком календаре лежит; пусто — основной"),
        ),
        run=lambda c, a: core.delete_event(
            c, _text(a, "event_id"), _text(a, "calendar_id")),
    ),
)


def by_name() -> dict[str, Tool]:
    return {tool.name: tool for tool in TOOLS}


def selected(switches: dict[str, bool] | None = None) -> list[Tool]:
    """Кнопки, которые действительно объявляются: включённые человеком."""
    return [tool for tool in TOOLS if toggles.is_on(tool.name, switches)]
