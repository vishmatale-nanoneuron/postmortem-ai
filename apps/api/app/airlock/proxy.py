"""Proxy fetch: Airlock retrieves the URL itself, so the check cannot be
skipped. The agent never touches the page; it gets back a verdict and, when
the verdict allows it, the page's text.

This module is the part that must be right: a service that fetches URLs on
request is a server-side request forgery gadget unless it refuses to reach
anything but the public internet. Three rules, each with a test:

1. The hostname is RESOLVED and every address it resolves to is checked
   before a connection is made. Loopback, private, link-local (the cloud
   metadata address lives there), carrier-grade NAT, reserved, multicast,
   unspecified, documentation ranges, IPv4-mapped and NAT64-embedded IPv6
   are all refused. Checking the string alone is not a guard: "localhost",
   a decimal IP, or a hostname that resolves to 10.0.0.1 all pass a string
   check.

2. The connection is made TO THE ADDRESS THAT WAS CHECKED, with the
   original hostname carried as the Host header and as the TLS server name
   (httpcore's `sni_hostname` extension), so the certificate is still
   verified against the real hostname. Without this, a DNS record that
   changes between the check and the connect (rebinding) lands the request
   on an internal address that was never checked.

3. Redirects are followed by hand, each hop re-resolved and re-checked
   under the same rules, at most MAX_REDIRECTS times. A public URL that
   302s to http://169.254.169.254/ is the oldest trick in the book.

Nothing the caller sends is forwarded: no headers, no cookies, no body.
The fetch is a bare GET with Airlock's own User-Agent. Responses are read
to a byte cap and must be a text type; anything else is refused before it
is scanned, and the refusal is a client error the route refunds.
"""

import asyncio
import html
import ipaddress
import re
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

# Credits per proxy fetch: one for the fetch (our bandwidth, our IP), one
# for the scan. A deep scan adds DEEP_SCAN_EXTRA_CREDITS on top, like any
# other scan. Pinned by the web pricing test.
PROXY_FETCH_CREDITS = 2

MAX_REDIRECTS = 3
FETCH_TIMEOUT_S = 10.0
# Read cap on the body. A page that matters to an agent is well under this;
# a page over it is truncated, scanned as far as it goes, and flagged as
# truncated in the response.
MAX_BODY_BYTES = 1_000_000
# The scanner sees more than the API's 50k-character scan cap because a
# page's injection is often past the fold; the engine is linear in the
# input and this is still a few tens of milliseconds.
MAX_PROXY_SCAN_CHARS = 200_000
# What is handed back to the agent, after tag stripping.
MAX_RETURNED_CHARS = 50_000

ALLOWED_SCHEMES = frozenset({"http", "https"})
TEXT_TYPES = (
    "text/",
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/xhtml+xml",
    "application/rss+xml",
    "application/atom+xml",
    "application/x-yaml",
    "application/yaml",
)
USER_AGENT = "Airlock/1.0 (+https://www.nanoneuron.ai/airlock)"

_NAT64_PREFIX = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL_PREFIX = ipaddress.ip_network("64:ff9b:1::/48")


class ProxyRefused(Exception):
    """The fetch was not made, or not completed, for a reason the caller
    should hear. `status_code` is what the route answers with: 422 for a
    URL that will never be fetched (scheme, private address, content
    type), 502 for a public URL that could not be reached this time."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def is_public_address(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True only for an address on the public internet. Python's `is_global`
    does most of the work (private, loopback, link-local, CGNAT, reserved,
    documentation, unspecified, IPv4-mapped); multicast and NAT64-embedded
    IPv4 are added by hand because `is_global` calls them global."""
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return is_public_address(mapped)
        if ip in _NAT64_PREFIX or ip in _NAT64_LOCAL_PREFIX:
            embedded = ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
            return is_public_address(embedded)
    if ip.is_multicast or ip.is_unspecified or ip.is_loopback or ip.is_link_local or ip.is_private:
        return False
    return bool(ip.is_global)


def _ip_literal(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """The address a host string names directly, if it names one at all --
    including the forms `ipaddress` rejects but resolvers accept: decimal
    (`2130706433`), hex (`0x7f000001`) and short dotted (`127.1`) IPv4.
    Those must be recognised here, before DNS, or a guard that relies on
    the resolver's answer is only as strict as the resolver."""
    bare = host.strip("[]")
    try:
        return ipaddress.ip_address(bare)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_ntoa(socket.inet_aton(bare)))
    except (OSError, ValueError):
        return None


Resolver = Callable[[str], Awaitable[list[str]]]


async def resolve_addresses(host: str) -> list[str]:
    """Every address the host resolves to, v4 and v6. In a thread: the
    resolver call blocks, and the event loop serves other scans."""
    try:
        infos = await asyncio.get_running_loop().run_in_executor(
            None, lambda: socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        )
    except socket.gaierror as error:
        raise ProxyRefused(502, f"Could not resolve {host}") from error
    addresses = []
    for info in infos:
        address = info[4][0]
        if address not in addresses:
            addresses.append(address)
    return addresses


async def public_address_for(host: str, resolve: Resolver = resolve_addresses) -> str:
    """The one address the connection will be made to, after every address
    the host has was checked. ANY non-public address refuses the host: a
    name that resolves to both 93.184.216.34 and 10.0.0.1 is not a host we
    can safely pick one address of."""
    literal = _ip_literal(host)
    if literal is not None:
        if not is_public_address(literal):
            raise ProxyRefused(422, f"{host} is not a public address")
        return str(literal)
    if host.lower() in {"localhost", "localhost.localdomain"} or host.lower().endswith((".localhost", ".local", ".internal")):
        raise ProxyRefused(422, f"{host} is not a public host")
    addresses = await resolve(host)
    if not addresses:
        raise ProxyRefused(502, f"Could not resolve {host}")
    for address in addresses:
        if not is_public_address(ipaddress.ip_address(address)):
            raise ProxyRefused(422, f"{host} resolves to a non-public address")
    # Prefer IPv4 when both exist: the serverless egress path is v4.
    for address in addresses:
        if ":" not in address:
            return address
    return addresses[0]


@dataclass(frozen=True)
class Fetched:
    url: str
    final_url: str
    http_status: int
    content_type: str
    # Decoded text of the body, capped at MAX_BODY_BYTES before decoding.
    text: str
    content_bytes: int
    truncated: bool
    hops: int
    fetch_ms: int


def _split(url: str) -> tuple[str, str, str, str, str]:
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise ProxyRefused(422, "Only http and https URLs can be fetched")
    if not parts.hostname:
        raise ProxyRefused(422, "The URL has no host")
    if parts.username or parts.password:
        raise ProxyRefused(422, "Credentials in the URL are not sent; remove them")
    return parts.scheme.lower(), parts.hostname, parts.netloc, parts.path or "/", parts.query


def _is_text(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(lowered.startswith(prefix) for prefix in TEXT_TYPES)


async def fetch_url(
    url: str,
    *,
    resolve: Resolver = resolve_addresses,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Fetched:
    """GET the URL under the rules in the module docstring. `resolve` and
    `transport` are injectable so the guard can be tested without DNS or a
    network -- the test's transport sees exactly the request a real one
    would: connected to the checked IP, Host and SNI set to the hostname."""
    started = time.perf_counter()
    current = url.strip()
    if len(current) > 2048:
        raise ProxyRefused(422, "URL too long")
    hops = 0
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html, text/plain, application/json;q=0.9, application/xml;q=0.8, */*;q=0.1",
        "Accept-Language": "en",
    }
    async with httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        timeout=httpx.Timeout(FETCH_TIMEOUT_S),
        headers=headers,
        trust_env=False,
    ) as client:
        while True:
            scheme, host, _netloc, path, query = _split(current)
            address = await public_address_for(host, resolve)
            parts = urlsplit(current)
            port = parts.port
            # Connect to the checked address. The hostname travels as the
            # Host header and, for https, as the TLS server name, so the
            # certificate is verified against the name the caller gave us.
            pinned_host = f"[{address}]" if ":" in address else address
            pinned = urlunsplit((scheme, f"{pinned_host}:{port}" if port else pinned_host, path, query, ""))
            host_header = f"{host}:{port}" if port else host
            request = client.build_request(
                "GET",
                pinned,
                headers={"Host": host_header},
                extensions={"sni_hostname": host} if scheme == "https" else {},
            )
            try:
                response = await client.send(request, stream=True)
            except httpx.TimeoutException as error:
                raise ProxyRefused(502, f"{host} did not answer within {int(FETCH_TIMEOUT_S)} seconds") from error
            except httpx.HTTPError as error:
                raise ProxyRefused(502, f"Could not fetch from {host}: {error.__class__.__name__}") from error

            try:
                if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                    hops += 1
                    if hops > MAX_REDIRECTS:
                        raise ProxyRefused(422, f"More than {MAX_REDIRECTS} redirects")
                    current = urljoin(current, response.headers["location"])
                    continue

                content_type = response.headers.get("content-type", "").split(";")[0].strip() or "application/octet-stream"
                if not _is_text(content_type):
                    raise ProxyRefused(422, f"{content_type} is not a text type Airlock scans")

                chunks: list[bytes] = []
                size = 0
                truncated = False
                async for chunk in response.aiter_bytes():
                    room = MAX_BODY_BYTES - size
                    if len(chunk) > room:
                        chunks.append(chunk[:room])
                        size += room
                        truncated = True
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                body = b"".join(chunks)
            finally:
                await response.aclose()

            encoding = response.charset_encoding or "utf-8"
            try:
                text = body.decode(encoding, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return Fetched(
                url=url.strip(),
                final_url=current,
                http_status=response.status_code,
                content_type=content_type,
                text=text,
                content_bytes=size,
                truncated=truncated,
                hops=hops,
                fetch_ms=int((time.perf_counter() - started) * 1000),
            )


_SCRIPT_STYLE = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
_BLOCK_TAG = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|td|th|table|section|article|header|footer|blockquote|pre)\b[^>]*>", re.I)


def prepare_for_scan(text: str, content_type: str) -> str:
    """What the detector sees. For HTML: script, style and noscript blocks
    removed (bulk that is not content), everything else kept -- comments
    and hidden elements included, because the detector's normaliser is
    what finds instructions hidden in them. Capped at MAX_PROXY_SCAN_CHARS."""
    if "html" in content_type.lower():
        text = _SCRIPT_STYLE.sub(" ", text)
    return text[:MAX_PROXY_SCAN_CHARS]


def visible_text(text: str, content_type: str) -> str:
    """What the agent gets: for HTML, the text a reader would see, with
    block boundaries kept as newlines; other types as they are. Capped at
    MAX_RETURNED_CHARS."""
    if "html" in content_type.lower():
        text = _SCRIPT_STYLE.sub(" ", text)
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
        text = _BLOCK_TAG.sub("\n", text)
        text = _TAG.sub(" ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t\r\f\v]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{2,}", "\n", text).strip()
    return text[:MAX_RETURNED_CHARS]
