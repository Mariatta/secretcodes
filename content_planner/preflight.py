"""Why a publication cannot go out.

``preflight`` is a pure function of already-persisted state: same publication
plus same limits gives the same blockers, whether it is called from the queue
view, the nightly sweep, or the moment before the HTTP call. It writes nothing.
"""

from dataclasses import dataclass

import regex

from .models import Post, PublishingAccount
from .payloads import mime_for, render_text


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str

    def as_dict(self):
        return {"code": self.code, "message": self.message}


def grapheme_len(text):
    """User-perceived character count.

    ``len()`` is wrong for the platforms that matter: an emoji with a skin-tone
    modifier is several code points but one character to Bluesky.
    """
    return len(regex.findall(r"\X", text))


def preflight(publication, limits):
    """Return every reason ``publication`` cannot be delivered, in order."""
    blockers = []
    post = publication.post
    account = publication.account

    if post.status != Post.Status.SCHEDULED:
        blockers.append(
            Blocker(
                "not_scheduled",
                f"Post is {post.get_status_display().lower()}, not scheduled.",
            )
        )
    if account.status != PublishingAccount.Status.ACTIVE:
        blockers.append(Blocker("account", f"{account.handle} needs reconnecting."))
    if account.expires_at and account.expires_at <= publication.scheduled_for:
        blockers.append(
            Blocker("token_expiry", "Token expires before the scheduled time.")
        )

    assets = list(post.assets.all())
    if limits.requires_asset and not assets:
        blockers.append(Blocker("no_asset", "This platform requires an image."))
    if len(assets) > limits.max_assets:
        blockers.append(
            Blocker(
                "too_many_assets",
                f"{len(assets)} assets, max {limits.max_assets}.",
            )
        )
    for asset in assets:
        if not asset.caption:
            blockers.append(Blocker("alt_text", f"{asset.name} has no alt text."))
        if not asset.media_url:
            blockers.append(Blocker("missing_file", f"{asset.name} has no file."))
        elif mime_for(asset) not in limits.allowed_mimes:
            blockers.append(
                Blocker(
                    "mime", f"{asset.name} is {mime_for(asset) or 'an unknown type'}."
                )
            )
        elif asset.file and asset.file.size > limits.max_asset_bytes:
            blockers.append(
                Blocker(
                    "asset_too_large",
                    f"{asset.name} is {asset.file.size} bytes, "
                    f"max {limits.max_asset_bytes}.",
                )
            )

    rendered = render_text(post)
    length = grapheme_len(rendered)
    if length > limits.max_chars:
        blockers.append(Blocker("too_long", f"{length}/{limits.max_chars} characters."))
    if limits.max_hashtags is not None and len(post.hashtag_list) > limits.max_hashtags:
        blockers.append(
            Blocker(
                "hashtags",
                f"{len(post.hashtag_list)} hashtags, max {limits.max_hashtags}.",
            )
        )
    return blockers
