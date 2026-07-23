"""Connector registry.

``settings.CONTENT_PLANNER_CONNECTORS`` maps a platform value to a dotted path.
A platform with no connector is a permanent failure, not a silent skip.
"""

from django.conf import settings
from django.utils.module_loading import import_string

from .base import (
    AssetRef,
    Connector,
    PermanentPublishError,
    PlatformLimits,
    PublishError,
    PublishPayload,
    PublishResult,
    TransientPublishError,
)

__all__ = [
    "AssetRef",
    "Connector",
    "PermanentPublishError",
    "PlatformLimits",
    "PublishError",
    "PublishPayload",
    "PublishResult",
    "TransientPublishError",
    "connector_for",
]


def connector_for(account):
    """Instantiate the connector for ``account``'s platform."""
    path = settings.CONTENT_PLANNER_CONNECTORS.get(account.platform)
    if not path:
        raise PermanentPublishError(
            f"No connector configured for platform '{account.platform}'."
        )
    return import_string(path)()
