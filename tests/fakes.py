"""A scriptable stand-in for librelinkup_mcp.core.client.LibreLinkUpClient."""

from __future__ import annotations

import asyncio
from uuid import UUID

from tests.factories import make_current, make_measurement


class FakeLibreClient:
    """Records calls; `fail_next[method]` holds exceptions to raise, one per call."""

    def __init__(self, patients, *, auth_delay: float = 0.0):
        self.patients = list(patients)
        self.auth_delay = auth_delay
        self.calls: list[tuple[str, UUID | None]] = []
        self.fail_next: dict[str, list[Exception]] = {}

    def _record(self, method: str, patient_id: UUID | None = None) -> None:
        self.calls.append((method, patient_id))
        queue = self.fail_next.get(method)
        if queue:
            raise queue.pop(0)

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    async def authenticate(self) -> None:
        if self.auth_delay:
            await asyncio.sleep(self.auth_delay)
        self._record("authenticate")

    async def get_patients(self):
        self._record("get_patients")
        return list(self.patients)

    async def latest(self, patient_id):
        self._record("latest", patient_id)
        return make_current("9/26/2026 7:05:00 AM", 115, trend=3)

    async def graph(self, patient_id):
        self._record("graph", patient_id)
        return [
            make_measurement("9/26/2026 7:00:00 AM", 120),
            make_measurement("9/26/2026 6:45:00 AM", 110),
        ]

    async def logbook(self, patient_id):
        self._record("logbook", patient_id)
        return [make_measurement("9/20/2026 3:00:00 AM", 62)]
