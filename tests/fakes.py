"""A scriptable stand-in for pylibrelinkup.PyLibreLinkUp."""

from __future__ import annotations

import threading
import time
from uuid import UUID

import requests

from tests.factories import make_current, make_measurement


def http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} error", response=response)


class FakeLibreClient:
    """Records calls; `fail_next[method]` holds exceptions to raise, one per call."""

    def __init__(self, patients, *, auth_delay: float = 0.0):
        self.patients = list(patients)
        self.auth_delay = auth_delay
        self.calls: list[tuple[str, UUID | None]] = []
        self.fail_next: dict[str, list[Exception]] = {}
        self._lock = threading.Lock()

    def _record(self, method: str, patient_id: UUID | None = None) -> None:
        with self._lock:
            self.calls.append((method, patient_id))
            queue = self.fail_next.get(method)
            error = queue.pop(0) if queue else None
        if error is not None:
            raise error

    def count(self, method: str) -> int:
        return sum(1 for name, _ in self.calls if name == method)

    def authenticate(self) -> None:
        if self.auth_delay:
            time.sleep(self.auth_delay)
        self._record("authenticate")

    def get_patients(self):
        self._record("get_patients")
        return list(self.patients)

    def latest(self, patient_identifier):
        self._record("latest", patient_identifier)
        return make_current("9/26/2026 7:05:00 AM", 115, trend=3)

    def graph(self, patient_identifier):
        self._record("graph", patient_identifier)
        return [
            make_measurement("9/26/2026 7:00:00 AM", 120),
            make_measurement("9/26/2026 6:45:00 AM", 110),
        ]

    def logbook(self, patient_identifier):
        self._record("logbook", patient_identifier)
        return [make_measurement("9/20/2026 3:00:00 AM", 62)]
