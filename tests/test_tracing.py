import builtins
from contextlib import contextmanager

import pytest

from librelinkup_mcp import tracing
from librelinkup_mcp.config import load_settings

CREDS = {"LIBRELINKUP_EMAIL": "me@example.com", "LIBRELINKUP_PASSWORD": "pw"}
LANGFUSE = {"LANGFUSE_PUBLIC_KEY": "pk", "LANGFUSE_SECRET_KEY": "sk"}


class FakeObservation:
    def __init__(self, **kwargs):
        self.start = kwargs
        self.updates = {}

    def update(self, **kwargs):
        self.updates.update(kwargs)


class FakeLangfuse:
    def __init__(self):
        self.observations: list[FakeObservation] = []
        self.shut_down = False

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        observation = FakeObservation(**kwargs)
        self.observations.append(observation)
        yield observation

    def shutdown(self):
        self.shut_down = True


@pytest.fixture(autouse=True)
def reset_tracing():
    yield
    tracing.configure(load_settings(CREDS))


def enable(capture: bool) -> FakeLangfuse:
    fake = FakeLangfuse()
    env = {**CREDS, **LANGFUSE, "LANGFUSE_CAPTURE_DATA": "true" if capture else "false"}
    tracing.configure(load_settings(env), client=fake)
    return fake


@tracing.traced("echo")
async def echo(patient: str | None = None) -> dict:
    return {"patient": patient}


@tracing.traced("boom")
async def boom(patient: str | None = None) -> dict:
    raise ValueError(f"no patient named {patient}")


async def test_disabled_is_passthrough():
    tracing.configure(load_settings(CREDS), client=FakeLangfuse())
    assert await echo(patient="Ann") == {"patient": "Ann"}
    with pytest.raises(ValueError, match="no patient named Ann"):
        await boom(patient="Ann")
    tracing.shutdown()


def test_missing_langfuse_package_disables_tracing(monkeypatch, caplog):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "langfuse":
            raise ImportError("no langfuse")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    tracing.configure(load_settings({**CREDS, **LANGFUSE}))
    assert tracing._client is None
    assert "not installed" in caplog.text


async def test_metadata_only_by_default():
    fake = enable(capture=False)
    assert await echo(patient="Ann") == {"patient": "Ann"}
    [obs] = fake.observations
    assert obs.start["name"] == "echo"
    assert obs.start["as_type"] == "tool"
    assert obs.start["input"] is None
    assert obs.start["metadata"] == {"tool": "echo"}
    assert "output" not in obs.updates


async def test_capture_records_input_and_output():
    fake = enable(capture=True)
    await echo(patient="Ann")
    [obs] = fake.observations
    assert obs.start["input"] == {"patient": "Ann"}
    assert obs.updates["output"] == {"patient": "Ann"}


async def test_error_without_capture_hides_message():
    fake = enable(capture=False)
    with pytest.raises(ValueError, match="no patient named Ann"):
        await boom(patient="Ann")
    [obs] = fake.observations
    assert obs.updates == {"level": "ERROR", "status_message": "ValueError"}


async def test_error_with_capture_includes_message():
    fake = enable(capture=True)
    with pytest.raises(ValueError):
        await boom(patient="Ann")
    assert fake.observations[0].updates["status_message"] == "no patient named Ann"


async def test_span_records_metadata_and_errors():
    fake = enable(capture=False)
    async with tracing.span("librelinkup.graph", {"patient_id": "abc"}):
        pass
    with pytest.raises(RuntimeError):
        async with tracing.span("librelinkup.graph", {"patient_id": "abc"}):
            raise RuntimeError("Ann Lee")
    ok, failed = fake.observations
    assert ok.start["as_type"] == "span"
    assert ok.start["metadata"] == {"patient_id": "abc"}
    assert failed.updates == {"level": "ERROR", "status_message": "RuntimeError"}


def test_shutdown_flushes_client():
    fake = enable(capture=False)
    tracing.shutdown()
    assert fake.shut_down


def test_traced_preserves_signature_for_schema_generation():
    import inspect

    assert list(inspect.signature(echo).parameters) == ["patient"]
    assert echo.__name__ == "echo"
