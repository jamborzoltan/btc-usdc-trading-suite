from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class RemoteStateError(RuntimeError):
    """A webtárhelyes, közös robotállapot nem érhető el vagy hibás."""


@dataclass(frozen=True)
class StateSnapshot:
    portfolio: dict[str, Any]
    revision: int


class StateConflict(RemoteStateError):
    def __init__(self, current: StateSnapshot):
        super().__init__("Az állapotot időközben a webapp módosította.")
        self.current = current


class RemoteStateStore:
    """Kizárólag a webapp PHP API-ján keresztül kezeli a közös MySQL-állapotot.

    Így a mini PC-nek nem kell nyílt MySQL-kapcsolat, az SQL műveletek pedig a
    tárhelyen maradnak prepared mysqli lekérdezések mögött.
    """

    def __init__(
        self,
        url: str,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.headers = {"Accept": "application/json", "User-Agent": "BTC-USDC-Robot/0.1"}
        if username and password:
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            self.headers["Authorization"] = f"Basic {token}"

    def load(self) -> StateSnapshot | None:
        status, payload = self._request("GET")
        if status != 200:
            raise RemoteStateError(f"A közös állapot olvasása HTTP {status} hibával tért vissza.")
        if payload.get("portfolio") is None:
            return None
        return self._snapshot_from_payload(payload)

    def save(self, snapshot: StateSnapshot) -> int:
        status, payload = self._request(
            "POST",
            {"portfolio": snapshot.portfolio, "revision": snapshot.revision},
        )
        if status == 409:
            raise StateConflict(self._snapshot_from_payload(payload))
        if status != 200 or not payload.get("ok"):
            message = str(payload.get("error") or f"HTTP {status}")
            raise RemoteStateError(f"A közös állapot mentése sikertelen: {message}")
        revision = payload.get("revision")
        if not isinstance(revision, int) or revision < 1:
            raise RemoteStateError("A közös állapot mentése érvénytelen verziót adott vissza.")
        return revision

    def _request(self, method: str, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        headers = dict(self.headers)
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                status = response.status
        except HTTPError as error:
            raw = error.read()
            status = error.code
        except URLError as error:
            if isinstance(error.reason, socket.gaierror):
                raise RemoteStateError(
                    "A webapp címe nem található. Ellenőrizd a robot.cfg "
                    "[web_state] url értékét: a feltöltött webapp pontos, publikus HTTPS-címe kell."
                ) from error
            raise RemoteStateError(f"A webtárhely nem érhető el: {error}") from error
        except OSError as error:
            raise RemoteStateError(f"A webtárhely nem érhető el: {error}") from error

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RemoteStateError("A webtárhely nem JSON választ adott.") from error
        if not isinstance(payload, dict):
            raise RemoteStateError("A webtárhely válasza nem objektum.")
        return status, payload

    @staticmethod
    def _snapshot_from_payload(payload: dict[str, Any]) -> StateSnapshot:
        portfolio = payload.get("portfolio")
        revision = payload.get("revision")
        if not isinstance(portfolio, dict) or not isinstance(revision, int) or revision < 0:
            raise RemoteStateError("A webtárhely hibás közös állapotot adott vissza.")
        return StateSnapshot(portfolio=portfolio, revision=revision)


class RemoteRuntimeStore:
    """A külön folyamat futási állapotát külön rekordban tárolja.

    Ez szándékosan nem írja a webapp vezérlőállapotát, így egy szívverés nem
    írhatja vissza az Automatikus mód kapcsoló régebbi értékét.
    """

    def __init__(
        self,
        url: str,
        runtime_token: str,
        username: str | None = None,
        password: str | None = None,
        timeout_seconds: float = 10,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "BTC-USDC-Robot/0.2",
            "X-Robot-Token": runtime_token,
        }
        if username and password:
            token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
            self.headers["Authorization"] = f"Basic {token}"

    def save(self, runtime: dict[str, Any]) -> None:
        headers = {**self.headers, "Content-Type": "application/json"}
        data = json.dumps({"runtime": runtime}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request = Request(self.url, data=data, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read()
                status = response.status
        except HTTPError as error:
            raw = error.read()
            status = error.code
        except URLError as error:
            raise RemoteStateError(f"A külön robot státusz-API nem érhető el: {error}") from error
        except OSError as error:
            raise RemoteStateError(f"A külön robot státusz-API nem érhető el: {error}") from error

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RemoteStateError("A külön robot státusz-API nem JSON választ adott.") from error
        if status != 200 or not isinstance(payload, dict) or not payload.get("ok"):
            message = payload.get("error") if isinstance(payload, dict) else f"HTTP {status}"
            raise RemoteStateError(f"A külön robot státusz mentése sikertelen: {message}")
