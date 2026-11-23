"""Find the visitor's address for IP-keyed rate limits.

Behind a reverse proxy every request reaches gunicorn from the proxy's own
address, so ``REMOTE_ADDR`` is the same for all visitors and they would
share one rate limit. The proxy records the real address in
``X-Forwarded-For``.
"""

import ipaddress


def _address_from(entry):
    """Pull a valid IP out of one ``X-Forwarded-For`` entry, or return None.

    An entry may carry a port: "203.0.113.7:51234" or "[2001:db8::1]:51234".
    """
    entry = entry.strip()
    if entry.startswith("["):
        entry = entry[1:].split("]", 1)[0]
    elif entry.count(":") == 1:
        entry = entry.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(entry))
    except ValueError:
        return None


def client_ip(request):
    """Return the visitor's IP address for django-ratelimit.

    Uses the last ``X-Forwarded-For`` entry, the one the proxy in front of
    the app added itself. Earlier entries come from the visitor and can be
    faked to dodge the limit. Falls back to ``REMOTE_ADDR`` when the header
    is missing or unreadable, as in local development.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    address = _address_from(forwarded.rsplit(",", 1)[-1]) if forwarded else None
    return address or request.META["REMOTE_ADDR"]
