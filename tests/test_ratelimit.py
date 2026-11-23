import pytest
from django.urls import reverse

from secretcodes.ratelimit import client_ip

PROXY = "169.254.129.1"


def _request(rf, forwarded=None):
    extra = {"REMOTE_ADDR": PROXY}
    if forwarded is not None:
        extra["HTTP_X_FORWARDED_FOR"] = forwarded
    return rf.get("/", **extra)


@pytest.mark.parametrize(
    "forwarded, expected",
    [
        ("203.0.113.7", "203.0.113.7"),
        ("203.0.113.7:51234", "203.0.113.7"),
        ("2001:db8::1", "2001:db8::1"),
        ("[2001:db8::1]:51234", "2001:db8::1"),
        ("198.51.100.9, 203.0.113.7:51234", "203.0.113.7"),
    ],
)
def test_client_ip_reads_the_entry_the_proxy_added(rf, forwarded, expected):
    assert client_ip(_request(rf, forwarded)) == expected


@pytest.mark.parametrize("forwarded", [None, "", "not an address", "1.2.3.4, junk"])
def test_client_ip_falls_back_to_remote_addr(rf, forwarded):
    assert client_ip(_request(rf, forwarded)) == PROXY


@pytest.mark.django_db
def test_visitors_behind_one_proxy_get_separate_rate_limits(client, settings):
    settings.AVAILABILITY_API_RATE_LIMIT = "1/m"
    url = reverse("availability:week_grid")

    def visit(address):
        return client.get(
            url, REMOTE_ADDR=PROXY, HTTP_X_FORWARDED_FOR=f"{address}:51234"
        )

    assert visit("203.0.113.7").status_code == 200
    assert visit("203.0.113.8").status_code == 200
    assert visit("203.0.113.7").status_code == 429
