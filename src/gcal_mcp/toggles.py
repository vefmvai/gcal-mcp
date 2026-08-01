"""Тумблеры: какие кнопки грузить в сессию, а какие не надо.

Зачем. Описание каждой кнопки уезжает в контекст модели при каждом запуске.
Одноразовой сессии это ничего не стоит, а агенту с длинной памятью — стоит,
и платит он этим местом всегда. Поэтому набор выбирает тот, кто платит.

Формат — YAML-словарь «имя кнопки → вкл/выкл»:

    tools:
      list_events: on
      free_slots: on
      find_events: off

Два правила:

1. **Кнопки нет в файле — она включена.** Обновились, приехала новая
   возможность — она работает. «Молча пропала после обновления» ищут
   неделями, лишнюю кнопку выключают за десять секунд.
2. **Выключенная кнопка не объявляется вообще** — то есть не стоит ни байта.

---

**Осознанный дубль.** Этот файл почти совпадает с таким же у соседнего
сервера задач, и это нарушение правила «у факта один дом» — принятое
с открытыми глазами 01.08.2026.

Альтернативы были хуже: общий пакет ради тридцати строк чтения YAML — это
третий репозиторий, третья установка и третья версия у каждого, кто ставит
себе один сервер из двух. Зависимость одного сервиса от другого — ещё хуже:
календарь не имеет отношения к задачам.

Дублируется здесь **механика**, а не факт: список кнопок у каждого сервера
свой, и разъехаться ему не с чем. Формат файла общий намеренно, и он часть
договора, а не совпадение.

Признак, по которому дубль пора убирать: **третий сервис**. На двух общий
пакет дороже дубля, на трёх — дешевле.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_PATH = "~/.config/gcal-mcp/tools.yaml"


def path_from_env(var: str = "GCAL_TOOLS_FILE", default: str = DEFAULT_PATH) -> Path:
    return Path(os.environ.get(var) or default).expanduser()


def parse(data: Any) -> dict[str, bool]:
    """Достать словарь тумблеров: принимается и {tools: {...}}, и просто {...}."""
    if not isinstance(data, dict):
        return {}
    section = data.get("tools") if isinstance(data.get("tools"), dict) else data
    return {str(k): bool(v) for k, v in section.items() if isinstance(v, bool)}


def load(path: Path | str | None = None) -> dict[str, bool]:
    """Прочитать тумблеры. Файла нет или он сломан — все кнопки включены.

    Молчаливое «включено всё» правильнее строгости: пустой набор кнопок
    из-за опечатки в необязательном файле — это агент, который внезапно
    ничего не умеет и не говорит почему.
    """
    file = Path(path).expanduser() if path else path_from_env()
    try:
        import yaml
    except ImportError:
        return {}
    try:
        return parse(yaml.safe_load(file.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}
    except Exception:  # сломанный YAML
        return {}


def is_on(name: str, toggles: dict[str, bool] | None) -> bool:
    """Включена ли кнопка. Не упомянута — включена (правило 1)."""
    if not toggles:
        return True
    return toggles.get(name, True)
