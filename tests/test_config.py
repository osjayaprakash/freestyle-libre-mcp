import pytest
from pylibrelinkup import APIUrl

from librelinkup_mcp.config import ConfigError, load_settings

CREDS = {"LIBRELINKUP_EMAIL": "me@example.com", "LIBRELINKUP_PASSWORD": "s3cret"}


def test_minimal_env_uses_defaults():
    settings = load_settings(CREDS)
    assert settings.email == "me@example.com"
    assert settings.password == "s3cret"
    assert settings.region is APIUrl.US
    assert settings.langfuse_enabled is False
    assert settings.langfuse_capture_data is False


def test_password_not_in_repr():
    assert "s3cret" not in repr(load_settings(CREDS))


@pytest.mark.parametrize("missing", ["LIBRELINKUP_EMAIL", "LIBRELINKUP_PASSWORD"])
def test_missing_credential_raises(missing):
    env = {k: v for k, v in CREDS.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        load_settings(env)


def test_password_is_used_verbatim():
    assert load_settings({**CREDS, "LIBRELINKUP_PASSWORD": " pass word "}).password == " pass word "


def test_blank_email_counts_as_missing():
    with pytest.raises(ConfigError, match="LIBRELINKUP_EMAIL"):
        load_settings({**CREDS, "LIBRELINKUP_EMAIL": "   "})


@pytest.mark.parametrize(
    "raw, expected", [("eu", APIUrl.EU), (" EU2 ", APIUrl.EU2), ("", APIUrl.US)]
)
def test_region_is_case_insensitive_and_defaults_to_us(raw, expected):
    assert load_settings({**CREDS, "LIBRELINKUP_REGION": raw}).region is expected


def test_invalid_region_lists_valid_regions():
    with pytest.raises(ConfigError) as info:
        load_settings({**CREDS, "LIBRELINKUP_REGION": "mars"})
    assert "'mars'" in str(info.value)
    assert "US" in str(info.value) and "EU2" in str(info.value)


@pytest.mark.parametrize(
    "public, secret, enabled",
    [("pk", "sk", True), ("pk", "", False), ("", "sk", False), ("", "", False)],
)
def test_langfuse_enabled_only_with_both_keys(public, secret, enabled):
    env = {**CREDS, "LANGFUSE_PUBLIC_KEY": public, "LANGFUSE_SECRET_KEY": secret}
    assert load_settings(env).langfuse_enabled is enabled


@pytest.mark.parametrize(
    "raw, expected",
    [("true", True), ("1", True), ("YES", True), ("false", False), ("0", False), ("", False)],
)
def test_capture_flag_parsing(raw, expected):
    env = {**CREDS, "LANGFUSE_CAPTURE_DATA": raw}
    assert load_settings(env).langfuse_capture_data is expected
