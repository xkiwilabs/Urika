import pytest

from urika.core.netguard import BlockedHostError, assert_public_host


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5",
        "http://192.168.1.1",
        "http://[::1]/",
    ],
)
def test_private_hosts_blocked(url):
    # Literal-IP cases (and localhost, which resolves to loopback reliably)
    # need no network: getaddrinfo on a literal IP returns it directly.
    with pytest.raises(BlockedHostError):
        assert_public_host(url)


def test_public_host_allowed(monkeypatch):
    """A public IP must not raise. Monkeypatch getaddrinfo so the test is
    hermetic and never depends on real DNS / network."""
    import socket

    def fake_getaddrinfo(host, *args, **kwargs):
        # Return a public IPv4 address regardless of the host queried.
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    assert_public_host("https://api.anthropic.com/v1/models")  # must not raise


def test_url_without_host_blocked():
    with pytest.raises(BlockedHostError):
        assert_public_host("not-a-url")


def test_unresolvable_host_blocked(monkeypatch):
    import socket

    def boom(host, *args, **kwargs):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(BlockedHostError):
        assert_public_host("https://does-not-exist.invalid/")


def test_blocks_when_any_record_is_private(monkeypatch):
    """DNS-rebind defense: if ANY resolved address is non-public, block."""
    import socket

    def mixed(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed)
    with pytest.raises(BlockedHostError):
        assert_public_host("https://rebind.example.com/")
