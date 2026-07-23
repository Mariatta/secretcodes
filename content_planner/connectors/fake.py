"""In-memory connector used by M1 and by tests.

It records every call instead of making one, which is what lets the dispatcher,
preflight, retry policy, and the duplicate-suppression constraint be exercised
end to end before a single real API exists.
"""

import itertools

from .base import PermanentPublishError, PlatformLimits, PublishResult

DEFAULT_LIMITS = PlatformLimits(
    max_chars=300,
    max_hashtags=None,
    max_assets=4,
    requires_asset=False,
    allowed_mimes=frozenset({"image/jpeg", "image/png"}),
    max_asset_bytes=1_000_000,
)


class FakeConnector:
    """Records publishes. Set ``raises`` to make the next publish fail."""

    platform = "fake"

    def __init__(self, limits=DEFAULT_LIMITS, raises=None):
        self._limits = limits
        self.raises = raises
        self.calls = []
        self._counter = itertools.count(1)

    def limits(self, account):
        return self._limits

    def authorize_url(self, state, **kwargs):
        return f"https://example.test/authorize?state={state}"

    def exchange(self, code, state, **kwargs):
        raise PermanentPublishError("FakeConnector cannot exchange codes.")

    def refresh(self, account):
        return None

    def publish(self, account, payload, idempotency_key):
        self.calls.append((account.pk, payload, idempotency_key))
        if self.raises is not None:
            raise self.raises
        n = next(self._counter)
        return PublishResult(
            remote_id=f"fake-{n}",
            remote_url=f"https://example.test/{account.handle}/{n}",
            raw={"idempotency_key": idempotency_key},
        )
