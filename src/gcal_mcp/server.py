"""MCP-сервер Календаря (FastMCP, транспорт stdio) — обёртка над манифестом.

Здесь не объявлено ни одной кнопки: список живёт в `tools.py`, логика —
в `core.py`. Этот файл разворачивает манифест в инструменты MCP и не знает
о календарях ничего.

Доступ задаётся окружением:
    GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN — обязательны
    GOOGLE_CALENDAR_ID  — основной календарь, по умолчанию primary
    COACH_TZ            — часовой пояс вывода, по умолчанию Europe/Moscow
    HTTPS_PROXY         — если Google недоступен напрямую
"""

from __future__ import annotations

import inspect
import os
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field as PydanticField

from . import toggles, tools
from .client import CalendarClient, CalendarError

mcp = FastMCP("calendar")

_client: CalendarClient | None = None

_PYTHON_TYPES: dict[str, Any] = {"str": str, "int": int, "bool": bool}


def client_from_env() -> CalendarClient:
    return CalendarClient(
        client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        refresh_token=os.environ.get("GOOGLE_REFRESH_TOKEN", ""),
        calendar_id=os.environ.get("GOOGLE_CALENDAR_ID", "primary"),
        tz=os.environ.get("COACH_TZ", "Europe/Moscow"),
        proxy=os.environ.get("HTTPS_PROXY") or None,
    )


def _calendar() -> CalendarClient:
    global _client
    if _client is None:
        _client = client_from_env()
    return _client


def _make_handler(tool: tools.Tool):
    """Собрать обработчик с настоящей сигнатурой из полей манифеста.

    Сигнатура подменяется, а не пишется руками: FastMCP строит схему
    по `inspect.signature`, и подменённая для него неотличима от обычной.
    """

    async def handler(**kwargs: Any) -> str:
        try:
            return await tool.run(_calendar(), kwargs)
        except CalendarError as err:
            # Ошибку отдаём словами: модель должна её увидеть и объяснить.
            return f"Не получилось (Календарь): {err}"

    parameters = []
    annotations: dict[str, Any] = {"return": str}
    for f in tool.fields:
        annotation = Annotated[
            _PYTHON_TYPES.get(f.kind, str),
            PydanticField(description=f.description or None),
        ]
        parameters.append(inspect.Parameter(
            f.name, inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if f.required else f.default,
            annotation=annotation,
        ))
        annotations[f.name] = annotation

    handler.__signature__ = inspect.Signature(parameters, return_annotation=str)
    handler.__annotations__ = annotations
    handler.__name__ = tool.name
    handler.__doc__ = tool.description
    return handler


def register(server: FastMCP, switches: dict[str, bool] | None) -> list[str]:
    """Объявить движку включённые кнопки."""
    registered: list[str] = []
    for tool in tools.selected(switches):
        server.add_tool(_make_handler(tool), name=tool.name, description=tool.description)
        registered.append(tool.name)
    return registered


def main() -> None:
    register(mcp, toggles.load())
    mcp.run()


if __name__ == "__main__":
    main()
