"""Billing seams for the content planner.

These are deliberate no-ops in v1. They mark the boundaries that a future paid
tier would gate, so wiring them now costs a few lines per call site and the
eventual upgrade is a one-line rewrite of the helper body. See the design's
"Paid feature considerations" section.
"""


def has_feature(user, feature_name) -> bool:
    """Whether ``user`` has access to ``feature_name``. Always True in v1."""
    return True


def check_quota(user, quota_kind, current_count) -> None:
    """Raise if ``user`` is over quota for ``quota_kind``. No-op in v1."""
    return None
