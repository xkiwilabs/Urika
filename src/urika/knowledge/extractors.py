"""Extract text content from various source types."""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB


def extract_text(path: Path) -> str:
    """Extract content from a text or markdown file."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    content = path.read_text()
    if not content.strip():
        raise ValueError(f"File is empty: {path}")
    return content


def extract_pdf(path: Path) -> str:
    """Extract text content from a PDF file."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    from pypdf import PdfReader

    reader = PdfReader(path)
    if not reader.pages:
        raise ValueError(f"PDF is empty: {path}")
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    if not parts:
        raise ValueError(f"PDF has no extractable text: {path}")
    return "\n".join(parts)


def extract_url(url: str) -> str:
    """Fetch a URL and extract text content from HTML."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https URLs are supported, got: {parsed.scheme}")

    # Block private/internal IP addresses (SSRF protection)
    try:
        hostname = parsed.hostname or ""
        addr_info = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                raise ValueError(
                    f"Access to private/internal addresses is not allowed: {hostname}"
                )
    except socket.gaierror as exc:
        raise ValueError(f"Failed to resolve hostname: {exc}") from exc

    try:
        with urlopen(url, timeout=30) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(raw) > _MAX_RESPONSE_BYTES:
                raise ValueError(f"Response too large (>{_MAX_RESPONSE_BYTES} bytes)")
    except OSError as exc:
        raise ValueError(f"Failed to fetch URL: {exc}") from exc
    if not raw:
        raise ValueError(f"Empty response from URL: {url}")
    html = raw.decode(charset, errors="replace")
    return _strip_html_tags(html)


def _strip_html_tags(html: str) -> str:
    """Remove HTML tags and return plain text."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
