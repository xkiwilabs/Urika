"""Block SSRF to private/loopback/link-local/reserved addresses."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class BlockedHostError(ValueError):
    """Raised when a URL resolves to a non-public address."""


def _is_blocked_ip(ip) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def assert_public_host(url: str) -> None:
    """Raise BlockedHostError if the URL's host resolves to a non-public IP.

    Resolves ALL A/AAAA records and blocks if ANY is non-public (defeats
    DNS-rebind-to-localhost). Callers that legitimately need private
    endpoints (the privacy preflight for user-declared private LLMs)
    must opt out explicitly rather than calling this."""
    host = urlparse(url).hostname
    if not host:
        raise BlockedHostError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise BlockedHostError(f"cannot resolve host: {exc}") from exc
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr.split("%")[0])
        except ValueError:
            continue
        if _is_blocked_ip(ip):
            raise BlockedHostError(f"host resolves to non-public address {ip}")
