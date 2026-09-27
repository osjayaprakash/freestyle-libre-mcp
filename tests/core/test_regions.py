import pytest

from librelinkup_mcp.core import Region


@pytest.mark.parametrize("name", ["eu2", "EU2", " Eu2 "])
def test_from_name_ignores_case_and_whitespace(name):
    assert Region.from_name(name) is Region.EU2


def test_from_name_rejects_unknown():
    with pytest.raises(ValueError, match="'mars'"):
        Region.from_name("mars")


def test_values_are_base_urls():
    assert Region.US == "https://api.libreview.io"
    assert Region.RU == "https://api.libreview.ru"
    assert len(Region) == 12
