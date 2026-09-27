"""Errors raised by LibreLinkUpClient. Messages never contain names or readings."""

from __future__ import annotations


class LibreLinkUpError(Exception):
    """Base class for every client error."""


class AuthenticationError(LibreLinkUpError):
    """Credentials rejected, session expired, or no login yet."""


class RedirectError(LibreLinkUpError):
    """The account lives in another region; `region` is its upper-cased name."""

    def __init__(self, region: str) -> None:
        self.region = region
        super().__init__(f"Account belongs to region {region}")


class TermsOfUseError(LibreLinkUpError):
    """The account must accept updated terms of use in the app."""


class PrivacyPolicyError(LibreLinkUpError):
    """The account must accept an updated privacy policy in the app."""


class EmailVerificationError(LibreLinkUpError):
    """The account's email address is not verified."""


class RateLimitError(LibreLinkUpError):
    def __init__(self, retry_after: int | None) -> None:
        self.retry_after = retry_after
        super().__init__(f"Rate limited (retry after {retry_after})")


class PatientNotFoundError(LibreLinkUpError):
    """The API could not load the requested patient."""


class APIError(LibreLinkUpError):
    """Unexpected HTTP status, or a non-zero `status` in the response body."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"LibreLinkUp API error {status}")


class NetworkError(LibreLinkUpError):
    """Connection failure or timeout; `kind` is the transport error class name."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        super().__init__(f"Network error: {kind}")


class ResponseShapeError(LibreLinkUpError):
    """A response did not have the expected shape; `call` names the client method."""

    def __init__(self, call: str) -> None:
        self.call = call
        super().__init__(f"Unexpected response shape from {call}")
