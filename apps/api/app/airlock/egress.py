"""Egress guard.

Ingress scanning stops the instruction arriving. Egress guarding stops the
data leaving. You need both: an injection that never lands still matters if
the agent was already tricked, and most real-world damage is the outbound leg.

Checks, in order of cost:
  1. destination against the tenant allowlist
  2. secret material in the payload (keys, tokens, private keys)
  3. PII density
  4. entropy of URL parameters (encoded payloads hiding in query strings)
"""

import math
import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

SECRET_PATTERNS = [
    ("aws_access_key", r"AKIA[0-9A-Z]{16}"),
    ("aws_secret", r"(?i)aws.{0,20}secret.{0,20}['\"][0-9a-zA-Z/+]{40}['\"]"),
    ("anthropic_key", r"sk-ant-[a-zA-Z0-9\-_]{20,}"),
    ("openai_key", r"sk-(proj-)?[a-zA-Z0-9]{32,}"),
    ("github_token", r"gh[pousr]_[A-Za-z0-9]{36,}"),
    ("slack_token", r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    ("google_key", r"AIza[0-9A-Za-z\-_]{35}"),
    ("stripe_key", r"(sk|rk)_live_[0-9a-zA-Z]{24,}"),
    ("private_key", r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ("jwt", r"eyJ[A-Za-z0-9\-_]{10,}\.eyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}"),
    ("bearer", r"(?i)authorization\s*:\s*bearer\s+[A-Za-z0-9\-._~+/]{20,}"),
]

PII_PATTERNS = [
    ("email", r"[\w.+-]+@[\w-]+\.[\w.]{2,}"),
    ("phone_e164", r"\+\d{1,3}[\s-]?\d{6,14}"),
    ("credit_card", r"\b(?:\d[ -]*?){13,16}\b"),
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("aadhaar", r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    ("pan_in", r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    ("iban", r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b"),
]

# Not all personal data is equally bad to leak, and the original scoring
# treated it as if it were: the only thresholds were on the TOTAL count, so
# four credit-card numbers left an agent with score 0.00 and verdict
# "allow", exactly like four email addresses in a mailing list. An email in
# an outbound payload is ordinary; a card number, SSN, Aadhaar, PAN or IBAN
# is not ordinary at any count. These are scored separately below.
HIGH_SENSITIVITY_PII = frozenset({"credit_card", "ssn", "aadhaar", "pan_in", "iban"})

_SECRETS = [(n, re.compile(p)) for n, p in SECRET_PATTERNS]
_PII = [(n, re.compile(p)) for n, p in PII_PATTERNS]


@dataclass
class EgressVerdict:
    verdict: str  # allow | flag | block
    score: float
    reasons: list[str] = field(default_factory=list)
    secrets_found: list[str] = field(default_factory=list)
    pii_found: dict = field(default_factory=dict)
    destination: str | None = None
    redacted: str | None = None


def _entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def _host_allowed(host: str, allowlist: list[str]) -> bool:
    host = host.lower().lstrip(".")
    for entry in allowlist:
        e = entry.lower().lstrip(".")
        if host == e or host.endswith("." + e):
            return True
    return False


def check_egress(
    payload: str,
    destination: str | None,
    allowlist: list[str],
    redact: bool = True,
) -> EgressVerdict:
    reasons: list[str] = []
    score = 0.0
    host = None

    if destination:
        parsed = urlparse(destination if "//" in destination else f"//{destination}")
        host = parsed.hostname or destination
        if allowlist and not _host_allowed(host, allowlist):
            score = max(score, 0.90)
            reasons.append(f"destination {host} is not on the allowlist")

        qs = parsed.query or ""
        if len(qs) > 120 and _entropy(qs) > 4.2:
            score = max(score, 0.65)
            reasons.append("high-entropy query string — possible encoded payload")

    secrets = [name for name, rx in _SECRETS if rx.search(payload)]
    if secrets:
        score = max(score, 0.95)
        reasons.append(f"credential material in payload: {', '.join(secrets)}")

    pii: dict[str, int] = {}
    for name, rx in _PII:
        hits = len(rx.findall(payload))
        if hits:
            pii[name] = hits
    total_pii = sum(pii.values())
    # Volume, regardless of type: a big enough pile of anything personal is
    # a bulk export.
    if total_pii >= 20:
        score = max(score, 0.80)
        reasons.append(f"bulk PII in payload ({total_pii} values)")
    elif total_pii >= 5:
        score = max(score, 0.50)
        reasons.append(f"PII in payload ({total_pii} values)")

    # Sensitivity, regardless of volume. One card number leaving is worth
    # surfacing even to an allowlisted destination -- the allowlist answers
    # "where", never "what", which is the same reasoning that blocks an AWS
    # key to an allowlisted host. Deliberately a flag rather than a block at
    # low counts: a payments integration really does send a card to its
    # processor, and a guard that blocks that outright gets switched off.
    # Several of them at once is no longer an integration, it is an export.
    sensitive = {name: count for name, count in pii.items() if name in HIGH_SENSITIVITY_PII}
    sensitive_total = sum(sensitive.values())
    if sensitive_total >= 3:
        score = max(score, 0.80)
        reasons.append(f"multiple high-sensitivity identifiers in payload: {', '.join(sorted(sensitive))}")
    elif sensitive_total >= 1:
        score = max(score, 0.50)
        reasons.append(f"high-sensitivity identifier in payload: {', '.join(sorted(sensitive))}")

    verdict = "allow"
    if score >= 0.75:
        verdict = "block"
    elif score >= 0.40:
        verdict = "flag"

    redacted = redact_payload(payload) if (redact and (secrets or pii)) else None

    return EgressVerdict(
        verdict=verdict,
        score=round(score, 3),
        reasons=reasons,
        secrets_found=secrets,
        pii_found=pii,
        destination=host,
        redacted=redacted,
    )


def redact_payload(payload: str) -> str:
    out = payload
    for name, rx in _SECRETS:
        out = rx.sub(f"[redacted:{name}]", out)
    for name, rx in _PII:
        out = rx.sub(f"[redacted:{name}]", out)
    return out
