"""Guard for vendored browser assets in secretcodes/static/vendor/."""

import re
from pathlib import Path

from django.conf import settings

_SOURCEMAP = re.compile(r"sourceMappingURL=(\S+)")


def test_vendored_assets_reference_no_missing_sourcemaps():
    """A vendored JS/CSS file must not point at a sourcemap we don't ship.

    WhiteNoise's manifest storage fails `collectstatic` (and the deploy) when
    a file references a `.map` that isn't present, so catch it in CI instead.
    """
    vendor = Path(settings.BASE_DIR) / "secretcodes" / "static" / "vendor"
    checked = 0
    for path in sorted(vendor.rglob("*.js")) + sorted(vendor.rglob("*.css")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for ref in _SOURCEMAP.findall(text):
            ref = ref.strip("\"'*/ ")
            if ref.startswith("data:"):  # pragma: no cover - none vendored
                continue  # inline sourcemap, nothing to resolve
            assert (
                path.parent / ref
            ).exists(), f"{path.name} references missing sourcemap {ref}"
            checked += 1
    assert checked, "expected at least one vendored sourcemap reference to check"
