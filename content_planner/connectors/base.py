"""The contract every platform connector implements.

Platform strings do not appear outside this package. Everything above it
(preflight, dispatcher, UI) works in terms of ``PlatformLimits``, a
``PublishPayload``, and the two error types below.
"""

from dataclasses import dataclass, field
from typing import NamedTuple, Protocol


@dataclass(frozen=True)
class AssetRef:
    """One asset, resolved to something a connector can upload."""

    url: str
    mime: str
    alt: str = ""
    byte_size: int = 0
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class PublishPayload:
    """Rendered content, ready to send. No model objects cross this line."""

    text: str
    assets: list[AssetRef] = field(default_factory=list)
    link: str | None = None
    reply_to: str | None = None


@dataclass(frozen=True)
class PublishResult:
    remote_id: str
    remote_url: str
    raw: dict = field(default_factory=dict)


class PlatformLimits(NamedTuple):
    """What a platform accepts. Instance-specific, hence per-account."""

    max_chars: int
    max_hashtags: int | None
    max_assets: int
    requires_asset: bool
    allowed_mimes: frozenset[str]
    max_asset_bytes: int


class PublishError(Exception):
    """Base for delivery failures.

    ``status_code`` is carried so callers can react to specific rejections
    (a 401 means the account needs reconnecting, not that the post is bad)
    without re-parsing the message.
    """

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


class TransientPublishError(PublishError):
    """Retry with backoff: 5xx, 429, network."""


class PermanentPublishError(PublishError):
    """Do not retry: 4xx validation, revoked token, content rejected."""


class Connector(Protocol):  # pragma: no cover - structural type, never called
    """Structural interface. Implementations live one module per platform."""

    platform: str

    def limits(self, account) -> PlatformLimits: ...

    def authorize_url(self, state: str, **kwargs) -> str: ...

    def exchange(self, code: str, state: str, **kwargs): ...

    def refresh(self, account) -> None: ...

    def publish(
        self, account, payload: PublishPayload, idempotency_key: str
    ) -> PublishResult: ...
