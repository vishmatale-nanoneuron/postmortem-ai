"""Airlock's detection engine, running inside this FastAPI backend.

The engine modules (rules, detector, egress) are pure stdlib and hold no
database or framework imports on purpose: they are the part that has to be
testable, reviewable and portable on its own. Everything that touches
Postgres lives in cqrs/airlock_scan.py, and everything that touches HTTP
lives in api/v1/airlock.py.
"""

from .detector import Detection, Detector, Match, normalize, sanitize
from .egress import EgressVerdict, check_egress, redact_payload
from .rules import RULES, RULES_BY_ID, Rule

__all__ = [
    "RULES",
    "RULES_BY_ID",
    "Detection",
    "Detector",
    "EgressVerdict",
    "Match",
    "Rule",
    "check_egress",
    "normalize",
    "redact_payload",
    "sanitize",
]
