"""LibreLinkUp regional API hosts."""

from __future__ import annotations

from enum import StrEnum


class Region(StrEnum):
    US = "https://api.libreview.io"
    EU = "https://api-eu.libreview.io"
    EU2 = "https://api-eu2.libreview.io"
    AE = "https://api-ae.libreview.io"
    AP = "https://api-ap.libreview.io"
    AU = "https://api-au.libreview.io"
    CA = "https://api-ca.libreview.io"
    DE = "https://api-de.libreview.io"
    FR = "https://api-fr.libreview.io"
    JP = "https://api-jp.libreview.io"
    LA = "https://api-la.libreview.io"
    RU = "https://api.libreview.ru"

    @classmethod
    def from_name(cls, name: str) -> Region:
        """Look up a region by member name, ignoring case and surrounding whitespace."""
        try:
            return cls[name.strip().upper()]
        except KeyError:
            raise ValueError(f"Unknown LibreLinkUp region {name!r}") from None
