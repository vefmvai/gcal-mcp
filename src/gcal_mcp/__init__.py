"""gcal-mcp — MCP-сервер к Google Календарю: события, поиск, свободные окна.

Ядро (`client` + `core` + `tools`) отделено от адаптеров: тот же список кнопок
обслуживает и отдельный процесс-сервер, и агента, который встраивает его в себя.
"""

from .client import CalendarClient, CalendarError

__all__ = ["CalendarClient", "CalendarError"]
__version__ = "0.1.0"
