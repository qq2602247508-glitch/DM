from __future__ import annotations

import posixpath
from dataclasses import dataclass
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)


class UrlRejected(ValueError):
    pass


@dataclass(frozen=True)
class UrlPolicy:
    base_url: str
    allowed_hosts: frozenset[str]
    allowed_ports: frozenset[int] = frozenset()

    def canonicalize(self, candidate: str, *, keep_fragment: bool = True) -> str:
        raw = candidate.strip()
        if not raw:
            raise UrlRejected("empty URL")
        if raw == "#" or raw.lower().startswith(("javascript:", "data:", "file:")):
            raise UrlRejected("placeholder or forbidden URL scheme")

        joined = urljoin(self.base_url, raw)
        parts = urlsplit(joined)
        if parts.scheme.lower() not in {"http", "https"}:
            raise UrlRejected("only HTTP(S) URLs are allowed")
        if parts.username is not None or parts.password is not None:
            raise UrlRejected("URL credentials are forbidden")
        host = (parts.hostname or "").lower().rstrip(".")
        if host not in self.allowed_hosts:
            raise UrlRejected(f"host is not allow-listed: {host or '<missing>'}")
        try:
            port = parts.port
        except ValueError as exc:
            raise UrlRejected("invalid port") from exc
        default_port = 80 if parts.scheme.lower() == "http" else 443
        if port is not None and port != default_port and port not in self.allowed_ports:
            raise UrlRejected(f"non-default port is forbidden: {port}")

        decoded_path = unquote(parts.path or "/")
        if any(segment == ".." for segment in decoded_path.replace("\\", "/").split("/")):
            raise UrlRejected("path traversal is forbidden")
        normalized_path = posixpath.normpath(decoded_path)
        if not normalized_path.startswith("/"):
            normalized_path = f"/{normalized_path}"
        if decoded_path.endswith("/") and not normalized_path.endswith("/"):
            normalized_path += "/"
        safe_path = quote(normalized_path, safe="/:@!$&'()*+,;=-._~")

        query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
        fragment = quote(unquote(parts.fragment), safe="-._~") if keep_fragment else ""
        netloc = host
        if port is not None and port != default_port:
            netloc = f"{host}:{port}"
        return urlunsplit((parts.scheme.lower(), netloc, safe_path, query, fragment))

    def without_fragment(self, url: str) -> str:
        canonical = self.canonicalize(url)
        parts = urlsplit(canonical)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
