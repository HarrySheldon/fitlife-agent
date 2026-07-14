from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import SplitResult, urlsplit, urlunsplit

from backend.domain.errors import invalid_model_endpoint_error


AddressResolver = Callable[..., list[tuple]]


class ModelEndpointPolicy:
    def __init__(self, *, resolver: AddressResolver = socket.getaddrinfo) -> None:
        self.resolver = resolver

    def validate_base_url(self, url: str) -> str:
        parsed = self._parse(url, allow_query=False)
        self._validate_addresses(parsed)
        path = parsed.path.rstrip("/")
        return urlunsplit(("https", _normalized_netloc(parsed), path, "", ""))

    def validate_request_url(self, url: str) -> None:
        parsed = self._parse(url, allow_query=True)
        self._validate_addresses(parsed)

    def _parse(self, url: str, *, allow_query: bool) -> SplitResult:
        try:
            parsed = urlsplit(url.strip())
            port = parsed.port
        except ValueError:
            raise invalid_model_endpoint_error() from None
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise invalid_model_endpoint_error()
        if parsed.username is not None or parsed.password is not None:
            raise invalid_model_endpoint_error()
        if (parsed.query and not allow_query) or parsed.fragment:
            raise invalid_model_endpoint_error()
        if port is not None and not 1 <= port <= 65535:
            raise invalid_model_endpoint_error()
        return parsed

    def _validate_addresses(self, parsed: SplitResult) -> None:
        host = parsed.hostname
        if host is None:
            raise invalid_model_endpoint_error()
        if host.lower() == "localhost" or host.lower().endswith(".localhost"):
            raise invalid_model_endpoint_error()

        literal = _ip_address(host)
        if literal is not None:
            _require_public_address(literal)
            return

        try:
            addresses = self.resolver(host, parsed.port or 443, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror):
            raise invalid_model_endpoint_error() from None
        if not addresses:
            raise invalid_model_endpoint_error()
        for address in addresses:
            try:
                resolved = ipaddress.ip_address(address[4][0].split("%", 1)[0])
            except (ValueError, IndexError, TypeError):
                raise invalid_model_endpoint_error() from None
            _require_public_address(resolved)


def _ip_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return None


def _require_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    mapped = getattr(address, "ipv4_mapped", None)
    if not address.is_global or (mapped is not None and not mapped.is_global):
        raise invalid_model_endpoint_error()


def _normalized_netloc(parsed: SplitResult) -> str:
    host = (parsed.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    if parsed.port is not None and parsed.port != 443:
        return f"{host}:{parsed.port}"
    return host
