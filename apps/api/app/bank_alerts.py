"""Parses a real bank credit-alert email (UPI/NEFT/IMPS/RTGS/wire) and
extracts the reference number and amount, so a matching pending payment
claim can be auto-approved without a human click -- the actual proof a
payment happened is the bank's own alert text, not a founder's memory of
having checked their banking app.

IMPORTANT -- built without a real sample: these patterns are a best-effort
covering common Indian bank alert phrasing (Axis, HDFC, ICICI, SBI, and
generic NEFT/RTGS/SWIFT wire credit templates all use close variants of
this wording), not verified against an actual Axis Bank email. The first
time a real alert comes through unmatched, check bank_alerts.py's patterns
against apps/api/tests/test_bank_alerts.py's fixtures and extend them --
this is expected to need at least one real-world adjustment.
"""

import re

# Reference: bank alerts label this "UPI Ref No", "UTR", "UTR No",
# "Ref No", "Reference Number", etc., immediately followed by an
# alphanumeric token. Tried in order; first match wins.
_REFERENCE_PATTERNS = [
    re.compile(r"UPI\s*Ref(?:erence)?\.?\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Za-z0-9]{6,})", re.IGNORECASE),
    re.compile(r"UTR\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Za-z0-9]{6,})", re.IGNORECASE),
    re.compile(r"Ref(?:erence)?\.?\s*(?:No\.?|Number)?\s*[:\-]?\s*([A-Za-z0-9]{6,})", re.IGNORECASE),
    re.compile(r"\bMT103\s*[:\-]?\s*([A-Za-z0-9]{6,})", re.IGNORECASE),
]

# Amount: "Rs.999.00", "INR 999", "Rs 999/-", "$15.00", etc. Captures the
# integer part only -- this app's claim amounts are always whole numbers
# (see api/v1/billing.py's _wire_currency_details / subscription_price_*).
_AMOUNT_PATTERN = re.compile(r"(?:Rs\.?|INR|USD|GBP|EUR|[$₹£€])\s*([\d,]+)(?:\.\d{1,2})?", re.IGNORECASE)


def extract_reference(text: str) -> str | None:
    for pattern in _REFERENCE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip()
    return None


def extract_amount(text: str) -> int | None:
    match = _AMOUNT_PATTERN.search(text)
    if not match:
        return None
    digits = match.group(1).replace(",", "")
    return int(digits) if digits.isdigit() else None


def looks_like_a_credit(text: str) -> bool:
    """A debit alert (money leaving the account) must never be treated as
    proof of an incoming client payment -- this is the one check that, if
    wrong, would be actively dangerous (auto-approving off a payment going
    the wrong direction), so it's deliberately conservative: requires an
    explicit credit/received word AND absence of an explicit debit word."""
    lowered = text.lower()
    credit_words = ("credited", "received", "credit of", "has been credited")
    debit_words = ("debited", "debit of", "has been debited", "withdrawn")
    return any(word in lowered for word in credit_words) and not any(word in lowered for word in debit_words)
