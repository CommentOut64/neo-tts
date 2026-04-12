from __future__ import annotations

import requests


class OwnerControlClient:
    def __init__(
        self,
        *,
        origin: str | None,
        token: str | None,
        session_id: str | None,
    ) -> None:
        self._origin = origin.rstrip("/") if origin else None
        self._token = token
        self._session_id = session_id

    def request_shutdown(self, *, source: str) -> bool:
        if not self._origin:
            return False

        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._session_id:
            headers["X-Neo-TTS-Session-ID"] = self._session_id

        response = requests.post(
            f"{self._origin}/v1/control/shutdown",
            headers=headers,
            json={"source": source},
            timeout=2,
        )
        response.raise_for_status()
        return True
