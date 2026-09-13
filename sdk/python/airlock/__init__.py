"""Airlock Python SDK -- the prompt-injection and exfiltration guard for AI
agents, as three calls.

    from airlock import Airlock

    guard = Airlock(api_key="alk_...")
    result = guard.scan(untrusted_text)
    if result.blocked:
        ...  # do not let this reach the model

Every call is paid from the key's prepaid credits (1 per scan or egress
check, 2 per proxy fetch, +4 for a deep scan). Every non-200 raises an
AirlockError subclass, so a caller that treats "any exception = block"
fails closed -- exactly what the API's own guidance says. Nothing is
retried automatically: a retried scan is a second charge.

Sync and async clients share one surface. Zero dependencies beyond httpx.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

__all__ = [
    "Airlock",
    "AsyncAirlock",
    "AirlockError",
    "AuthenticationError",
    "InsufficientCredits",
    "RateLimited",
    "FetchRefused",
    "ScanResult",
    "EgressResult",
    "FetchResult",
    "DEFAULT_BASE_URL",
]

__version__ = "0.1.0"

DEFAULT_BASE_URL = "https://postmortem-ai-api.vercel.app"
KEY_HEADER = "X-Airlock-Key"


class AirlockError(Exception):
    """Any non-200 from the API. `status` and `detail` are the API's; the
    `request_id` is what to quote when asking about it."""

    def __init__(self, status: int, detail: str, request_id: str | None = None):
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail
        self.request_id = request_id


class AuthenticationError(AirlockError):
    """401: no key, or an invalid / revoked one."""


class InsufficientCredits(AirlockError):
    """402: the account has no credits left. Nothing was scanned."""


class RateLimited(AirlockError):
    """429: `retry_after` seconds until the window resets."""

    def __init__(self, status: int, detail: str, request_id: str | None, retry_after: int | None):
        super().__init__(status, detail, request_id)
        self.retry_after = retry_after


class FetchRefused(AirlockError):
    """Proxy fetch: the URL will never be fetched (422) or could not be
    reached (502). The verdict is block; the attempt cost one credit."""


@dataclass(frozen=True)
class Match:
    rule_id: str
    family: str
    weight: float
    description: str


@dataclass(frozen=True)
class ScanResult:
    verdict: str
    score: float
    matches: tuple[Match, ...]
    families: tuple[str, ...]
    signals: dict[str, Any]
    content_sha256: str
    content_bytes: int
    latency_ms: int
    credits_remaining: int | None
    credits_charged: int
    semantic: dict[str, Any] | None = None
    sanitized: str | None = None
    policy: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def flagged(self) -> bool:
        return self.verdict == "flag"

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


@dataclass(frozen=True)
class EgressResult:
    verdict: str
    score: float
    reasons: tuple[str, ...]
    secrets_found: tuple[str, ...]
    pii_found: dict[str, int]
    destination: str | None
    destination_checked: bool
    redacted: str | None
    credits_remaining: int | None
    credits_charged: int
    request_id: str | None = None

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


@dataclass(frozen=True)
class FetchResult:
    verdict: str
    score: float
    stage: str
    reasons: tuple[str, ...]
    matches: tuple[Match, ...]
    url: str
    final_url: str | None
    http_status: int | None
    content_type: str | None
    content_bytes: int
    content: str | None
    truncated: bool
    hops: int
    credits_remaining: int | None
    credits_charged: int
    semantic: dict[str, Any] | None = None
    request_id: str | None = None

    @property
    def blocked(self) -> bool:
        return self.verdict == "block"

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


def _matches(raw: list[dict[str, Any]]) -> tuple[Match, ...]:
    return tuple(Match(m["rule_id"], m["family"], float(m["weight"]), m.get("description", "")) for m in raw)


def _scan_result(body: dict[str, Any], request_id: str | None) -> ScanResult:
    return ScanResult(
        verdict=body["verdict"],
        score=float(body["score"]),
        matches=_matches(body.get("matches", [])),
        families=tuple(body.get("families", [])),
        signals=dict(body.get("signals") or {}),
        content_sha256=body["content_sha256"],
        content_bytes=int(body["content_bytes"]),
        latency_ms=int(body["latency_ms"]),
        credits_remaining=body.get("credits_remaining"),
        credits_charged=int(body.get("credits_charged", 0)),
        semantic=body.get("semantic"),
        sanitized=body.get("sanitized"),
        policy=dict(body.get("policy") or {}),
        request_id=request_id,
    )


def _egress_result(body: dict[str, Any], request_id: str | None) -> EgressResult:
    return EgressResult(
        verdict=body["verdict"],
        score=float(body["score"]),
        reasons=tuple(body.get("reasons", [])),
        secrets_found=tuple(body.get("secrets_found", [])),
        pii_found=dict(body.get("pii_found") or {}),
        destination=body.get("destination"),
        destination_checked=bool(body.get("destination_checked")),
        redacted=body.get("redacted"),
        credits_remaining=body.get("credits_remaining"),
        credits_charged=int(body.get("credits_charged", 0)),
        request_id=request_id,
    )


def _fetch_result(body: dict[str, Any], request_id: str | None) -> FetchResult:
    return FetchResult(
        verdict=body["verdict"],
        score=float(body["score"]),
        stage=body["stage"],
        reasons=tuple(body.get("reasons", [])),
        matches=_matches(body.get("matches", [])),
        url=body["url"],
        final_url=body.get("final_url"),
        http_status=body.get("http_status"),
        content_type=body.get("content_type"),
        content_bytes=int(body.get("content_bytes", 0)),
        content=body.get("content"),
        truncated=bool(body.get("truncated")),
        hops=int(body.get("hops", 0)),
        credits_remaining=body.get("credits_remaining"),
        credits_charged=int(body.get("credits_charged", 0)),
        semantic=body.get("semantic"),
        request_id=request_id,
    )


def _raise_for(response: httpx.Response, *, proxy: bool = False) -> None:
    if response.status_code == 200:
        return
    request_id = response.headers.get("x-request-id")
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    if isinstance(detail, list):  # FastAPI validation errors
        detail = "; ".join(f"{'.'.join(map(str, e.get('loc', [])))}: {e.get('msg')}" for e in detail)
    status = response.status_code
    if status == 401:
        raise AuthenticationError(status, detail, request_id)
    if status == 402:
        raise InsufficientCredits(status, detail, request_id)
    if status == 429:
        retry = response.headers.get("retry-after")
        raise RateLimited(status, detail, request_id, int(retry) if retry and retry.isdigit() else None)
    if proxy and status in (422, 502):
        raise FetchRefused(status, detail, request_id)
    raise AirlockError(status, detail, request_id)


class _Base:
    def __init__(self, api_key: str, *, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0):
        if not api_key or not api_key.startswith("alk_"):
            raise ValueError("api_key must be an Airlock key (starts with 'alk_')")
        self._base_url = base_url.rstrip("/")
        self._headers = {KEY_HEADER: api_key, "User-Agent": f"airlock-python/{__version__}"}
        self._timeout = timeout

    @staticmethod
    def _scan_body(content: str, *, source: str | None, deep: bool, sanitize: bool) -> dict[str, Any]:
        return {"content": content, "source": source, "deep": deep, "sanitize": sanitize}

    @staticmethod
    def _egress_body(payload: str, *, destination: str | None, allowlist: list[str] | tuple[str, ...]) -> dict[str, Any]:
        return {"payload": payload, "destination": destination, "allowlist": list(allowlist)}

    @staticmethod
    def _fetch_body(url: str, *, allowlist: list[str] | tuple[str, ...], deep: bool, return_content: bool) -> dict[str, Any]:
        return {"url": url, "allowlist": list(allowlist), "deep": deep, "return_content": return_content}


class Airlock(_Base):
    """Synchronous client. `transport` lets a test route calls in-process."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        super().__init__(api_key, base_url=base_url, timeout=timeout)
        self._http = httpx.Client(base_url=self._base_url, headers=self._headers, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Airlock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def scan(self, content: str, *, source: str | None = None, deep: bool = False, sanitize: bool = False) -> ScanResult:
        """Score untrusted text before it reaches the model. 1 credit; 5 with deep."""
        r = self._http.post("/v1/airlock/scan", json=self._scan_body(content, source=source, deep=deep, sanitize=sanitize))
        _raise_for(r)
        return _scan_result(r.json(), r.headers.get("x-request-id"))

    def egress(self, payload: str, *, destination: str | None = None, allowlist: list[str] | tuple[str, ...] = ()) -> EgressResult:
        """Check an outbound call for credentials, personal data and destination. 1 credit."""
        r = self._http.post("/v1/airlock/egress", json=self._egress_body(payload, destination=destination, allowlist=allowlist))
        _raise_for(r)
        return _egress_result(r.json(), r.headers.get("x-request-id"))

    def fetch(self, url: str, *, allowlist: list[str] | tuple[str, ...] = (), deep: bool = False, return_content: bool = True) -> FetchResult:
        """Have Airlock fetch and screen a URL; the page text comes back only if it passes. 2 credits."""
        r = self._http.post("/v1/airlock/proxy/fetch", json=self._fetch_body(url, allowlist=allowlist, deep=deep, return_content=return_content))
        _raise_for(r, proxy=True)
        return _fetch_result(r.json(), r.headers.get("x-request-id"))

    def policy(self) -> dict[str, Any]:
        r = self._http.get("/v1/airlock/policy")
        _raise_for(r)
        return r.json()

    def usage(self, days: int = 30) -> dict[str, Any]:
        r = self._http.get("/v1/airlock/usage", params={"days": days})
        _raise_for(r)
        return r.json()

    def rules(self) -> dict[str, Any]:
        r = self._http.get("/v1/airlock/rules")
        _raise_for(r)
        return r.json()


class AsyncAirlock(_Base):
    """Asynchronous client with the same surface."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        super().__init__(api_key, base_url=base_url, timeout=timeout)
        self._http = httpx.AsyncClient(base_url=self._base_url, headers=self._headers, timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncAirlock:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def scan(self, content: str, *, source: str | None = None, deep: bool = False, sanitize: bool = False) -> ScanResult:
        r = await self._http.post("/v1/airlock/scan", json=self._scan_body(content, source=source, deep=deep, sanitize=sanitize))
        _raise_for(r)
        return _scan_result(r.json(), r.headers.get("x-request-id"))

    async def egress(self, payload: str, *, destination: str | None = None, allowlist: list[str] | tuple[str, ...] = ()) -> EgressResult:
        r = await self._http.post("/v1/airlock/egress", json=self._egress_body(payload, destination=destination, allowlist=allowlist))
        _raise_for(r)
        return _egress_result(r.json(), r.headers.get("x-request-id"))

    async def fetch(self, url: str, *, allowlist: list[str] | tuple[str, ...] = (), deep: bool = False, return_content: bool = True) -> FetchResult:
        r = await self._http.post("/v1/airlock/proxy/fetch", json=self._fetch_body(url, allowlist=allowlist, deep=deep, return_content=return_content))
        _raise_for(r, proxy=True)
        return _fetch_result(r.json(), r.headers.get("x-request-id"))

    async def policy(self) -> dict[str, Any]:
        r = await self._http.get("/v1/airlock/policy")
        _raise_for(r)
        return r.json()

    async def usage(self, days: int = 30) -> dict[str, Any]:
        r = await self._http.get("/v1/airlock/usage", params={"days": days})
        _raise_for(r)
        return r.json()

    async def rules(self) -> dict[str, Any]:
        r = await self._http.get("/v1/airlock/rules")
        _raise_for(r)
        return r.json()
