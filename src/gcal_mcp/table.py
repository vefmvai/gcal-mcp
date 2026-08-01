"""Таблица кнопок: что умеет сервер и что из этого сейчас грузится.

Печатается из манифеста, а не пишется руками: рукописный список кнопок
разошёлся бы с настоящим — ровно так, как расходятся объявления, которых
две штуки.

Запуск: `python -m gcal_mcp.table`
"""

from __future__ import annotations

from . import toggles, tools

CHECK = "✔"
CROSS = "—"


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - len(text))


def render(switches: dict[str, bool]) -> str:
    name_width = max(len(t.name) for t in tools.TOOLS) + 2
    summary_width = max(len(t.summary) for t in tools.TOOLS) + 2
    header = _pad("кнопка", name_width) + _pad("что делает", summary_width) + "грузится"
    lines = [header, "─" * len(header)]
    for tool in tools.TOOLS:
        on = toggles.is_on(tool.name, switches)
        lines.append(_pad(tool.name, name_width) + _pad(tool.summary, summary_width)
                     + (CHECK if on else CROSS))
    shown = tools.selected(switches)
    lines.append("")
    lines.append(f"Грузится кнопок: {len(shown)} из {len(tools.TOOLS)}.")
    if len(shown) < len(tools.TOOLS):
        off = [t.name for t in tools.TOOLS if t not in shown]
        lines.append("Не грузится: " + ", ".join(off))
    lines.append("")
    lines.append("Все возможности Календаря бесплатны — платных тарифов у него нет.")
    return "\n".join(lines)


def main() -> None:
    print(render(toggles.load()))


if __name__ == "__main__":
    main()
