"""HTTP for connectors: one place that decides what is retryable.

Every platform call goes through :func:`request`, so the transient/permanent
split is made once, from the status code, rather than in each connector.
"""

import requests

from .base import PermanentPublishError, TransientPublishError

# Platform calls are made inside a worker holding a claimed row: a hung
# connection would stall the whole tick, so nothing waits forever.
DEFAULT_TIMEOUT = 30
TRANSIENT_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


def request(method, url, *, timeout=DEFAULT_TIMEOUT, **kwargs):
    """Make a call and normalise its failure into the two connector errors.

    A network error is transient by definition: we cannot know whether the
    request landed, so the caller retries and relies on the idempotency key.
    """
    try:
        response = requests.request(method, url, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        raise TransientPublishError(f"{method} {url} failed: {exc}") from exc

    if response.status_code in TRANSIENT_STATUSES:
        raise TransientPublishError(
            f"{method} {url} returned {response.status_code}: {_detail(response)}",
            status_code=response.status_code,
        )
    if response.status_code >= 400:
        raise PermanentPublishError(
            f"{method} {url} returned {response.status_code}: {_detail(response)}",
            status_code=response.status_code,
        )
    return response


def _detail(response):
    """The platform's own error message, when it sends one."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        return str(payload.get("error") or payload.get("message") or payload)[:200]
    return str(payload)[:200]


def fetch_bytes(url):
    """Download an asset so it can be uploaded to a platform."""
    return request("GET", url).content
