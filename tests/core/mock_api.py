"""A scriptable stand-in for the LibreLinkUp HTTP API, served through httpx2.MockTransport."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx2

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text())


class MockAPI:
    """Route (method, path) to a canned reply; records every request it sees."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self._routes: dict[tuple[str, str], dict[str, Any]] = {}

    def on(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        json_body: Any = None,
        text: str | None = None,
        headers: dict[str, str] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._routes[(method, path)] = {
            "status": status,
            "json_body": json_body,
            "text": text,
            "headers": headers or {},
            "raises": raises,
        }

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        route = self._routes[(request.method, request.url.path)]
        if route["raises"] is not None:
            raise route["raises"]
        if route["text"] is not None:
            return httpx2.Response(route["status"], text=route["text"], headers=route["headers"])
        return httpx2.Response(route["status"], json=route["json_body"], headers=route["headers"])
