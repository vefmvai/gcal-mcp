"""Тонкий async-клиент к Google Calendar API v3.

Только доступ: обновление токена, HTTP, часовой пояс. Вся логика «кнопок» —
в core.py, список кнопок — в tools.py.

Вход по OAuth обычного аккаунта, а не по сервисному: сервисный аккаунт
не видит личный календарь, пока календарь ему не расшарят.

`access_token` живёт около часа, поэтому держится в памяти процесса
и переспрашивается по `refresh_token`, когда протух. Сам `refresh_token`
бессрочный, пока приложение опубликовано (в тестовом режиме Google гасит
его через неделю).

Прокси задаётся явно параметром: из некоторых стран Google недоступен
напрямую, и тогда весь трафик идёт через мост.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"


class CalendarError(RuntimeError):
    """Ошибка обращения к Календарю — с текстом, который можно показать."""


class CalendarClient:
    """Обёртка над httpx. Использовать как async context manager."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        calendar_id: str = "primary",
        tz: str = "Europe/Moscow",
        proxy: str | None = None,
        timeout: float = 40.0,
    ) -> None:
        if not (client_id and client_secret and refresh_token):
            raise CalendarError(
                "Нет доступа к Календарю: нужны client_id, client_secret и refresh_token."
            )
        self._auth = {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        self.calendar_id = calendar_id or "primary"
        self.tz = tz
        self.zone = ZoneInfo(tz)
        self._proxy = proxy
        self._timeout = timeout
        self._token: str | None = None
        self._expiry: float = 0.0

    async def __aenter__(self) -> "CalendarClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def now(self) -> datetime:
        return datetime.now(self.zone)

    async def _access_token(self) -> str:
        if self._token and self._expiry - 60 > time.time():
            return self._token
        async with httpx.AsyncClient(timeout=self._timeout, proxy=self._proxy) as http:
            try:
                response = await http.post(TOKEN_URL, data=self._auth)
                response.raise_for_status()
            except httpx.HTTPStatusError as err:
                raise CalendarError(
                    f"Google не обновил доступ ({err.response.status_code}). "
                    f"Обычно это значит, что refresh_token отозван или протух."
                ) from err
            except httpx.HTTPError as err:
                raise CalendarError(f"Google недоступен: {err}") from err
            data = response.json()
        self._token = data["access_token"]
        self._expiry = time.time() + int(data.get("expires_in", 3600))
        return self._token

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        token = await self._access_token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=self._timeout, proxy=self._proxy,
                                     headers=headers) as http:
            try:
                response = await http.request(method, f"{API}{path}", **kwargs)
                response.raise_for_status()
            except httpx.HTTPStatusError as err:
                body = err.response.text[:300]
                raise CalendarError(
                    f"Календарь {err.response.status_code} на {method} {path}: {body}"
                ) from err
            except httpx.HTTPError as err:
                raise CalendarError(f"Сеть недоступна на {method} {path}: {err}") from err
            if response.status_code == 204 or not response.content:
                return None
            return response.json()

    async def get(self, path: str, **kwargs: Any) -> Any:
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> Any:
        return await self.request("POST", path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", path, **kwargs)
