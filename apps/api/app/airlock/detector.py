"""Detection pipeline.

Stage 1  normalize   strip obfuscation so patterns can't hide behind unicode
Stage 2  match       weighted regex over the seed corpus + tenant corpus
Stage 3  structure   invisible chars, tag-block payloads, HTML-hidden text
Stage 4  aggregate   combine into a score, decide verdict
Stage 5  classify    optional LLM pass, only when the score is ambiguous

Stages 1-4 are pure CPU and run in ~1-3ms on a 50KB document. Stage 5 costs
money and latency, so it fires only in the uncertain band. That split is what
makes per-scan pricing work at a profit.
"""

import hashlib
import re
import time
import unicodedata
from dataclasses import dataclass, field

from .rules import INVISIBLE_CHARS, RULES, TAG_BLOCK, Rule


@dataclass
class Match:
    rule_id: str
    family: str
    weight: float
    excerpt: str
    offset: int


@dataclass
class Detection:
    score: float
    verdict: str  # allow | flag | block
    matches: list[Match] = field(default_factory=list)
    families: list[str] = field(default_factory=list)
    signals: dict = field(default_factory=dict)
    classifier_used: bool = False
    latency_ms: int = 0
    content_sha256: str = ""
    content_bytes: int = 0
    sanitized: str | None = None


_HTML_HIDDEN = re.compile(
    r"<[^>]*(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0)[^>]*>"
    r"(.{10,}?)</[^>]+>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_COMMENT = re.compile(r"<!--(.{20,}?)-->", re.DOTALL)
_WHITE_TEXT = re.compile(r"color\s*:\s*(#fff(fff)?|white|rgb\(\s*255\s*,\s*255\s*,\s*255\s*\))", re.I)
# A run of 6+ single characters separated by spaces. Real prose never does
# this; "a b c d e f" as an actual sentence is vanishingly rare, and the
# collapsed copy is only ever *added*, never substituted, so a false match
# costs nothing beyond a few wasted regex passes.
_SPACED_RUN = re.compile(r"(?:(?:^|(?<=\s))\w[ \t]){6,}\w*")


def _decode_tag_block(text: str) -> str:
    """Unicode tag characters render invisibly but carry ASCII. Decode them
    so the regex stage sees the real payload."""
    out = []
    for ch in text:
        cp = ord(ch)
        if TAG_BLOCK[0] <= cp <= TAG_BLOCK[1]:
            out.append(chr(cp - 0xE0000))
    return "".join(out)


def normalize(text: str) -> tuple[str, dict]:
    """Return normalized text plus the structural signals found while cleaning."""
    signals: dict = {}

    tag_payload = _decode_tag_block(text)
    if tag_payload.strip():
        signals["unicode_tag_payload"] = tag_payload[:200]

    invisible_found = sorted({INVISIBLE_CHARS[c] for c in text if c in INVISIBLE_CHARS})
    if invisible_found:
        signals["invisible_chars"] = invisible_found

    hidden_html = [m.group(2)[:200] for m in _HTML_HIDDEN.finditer(text)]
    if hidden_html:
        signals["hidden_html"] = hidden_html[:5]

    comments = [m.group(1)[:200] for m in _HTML_COMMENT.finditer(text)]
    if comments:
        signals["html_comments"] = comments[:5]

    if _WHITE_TEXT.search(text):
        signals["white_on_white"] = True

    # Build the surface the matcher actually reads: visible text plus
    # everything that was hidden from a human reviewer.
    merged = text
    if tag_payload:
        merged += "\n" + tag_payload
    for chunk in hidden_html + comments:
        merged += "\n" + chunk

    merged = unicodedata.normalize("NFKC", merged)
    for ch in INVISIBLE_CHARS:
        merged = merged.replace(ch, "")

    # Spacing obfuscation: "i g n o r e  a l l" defeats every word-based
    # pattern. This must run BEFORE whitespace collapse — the attacker's
    # word boundary is the double space, and collapsing destroys it.
    # The collapsed copy is only ever appended, never substituted, so a
    # false match costs a few wasted regex passes and nothing else.
    spaced = _SPACED_RUN.findall(merged)
    if spaced:
        rebuilt = []
        for run in spaced:
            words = [w.replace(" ", "").replace("\t", "") for w in re.split(r"[ \t]{2,}", run)]
            rebuilt.append(" ".join(w for w in words if w))
        collapsed = "\n".join(rebuilt)
        signals["spaced_obfuscation"] = collapsed[:200]
        merged += "\n" + collapsed

    merged = re.sub(r"[ \t]+", " ", merged)
    return merged.lower(), signals


class Detector:
    def __init__(self, rules: list[Rule] | None = None, muted: set[str] | None = None):
        self.muted = muted or set()
        self.rules = [r for r in (rules or RULES) if r.id not in self.muted]
        self._compiled = [
            (r, re.compile(r.pattern, re.IGNORECASE | re.MULTILINE)) for r in self.rules
        ]

    def scan(
        self,
        text: str,
        block_threshold: float = 0.75,
        flag_threshold: float = 0.40,
    ) -> Detection:
        started = time.perf_counter()
        raw = text or ""
        sha = hashlib.sha256(raw.encode("utf-8", "ignore")).hexdigest()

        normalized, signals = normalize(raw)
        matches: list[Match] = []

        for rule, compiled in self._compiled:
            m = compiled.search(normalized)
            if m:
                start = max(0, m.start() - 60)
                end = min(len(normalized), m.end() + 60)
                matches.append(
                    Match(
                        rule_id=rule.id,
                        family=rule.family,
                        weight=rule.weight,
                        excerpt=normalized[start:end].strip(),
                        offset=m.start(),
                    )
                )

        score = self._aggregate(matches, signals)
        families = sorted({m.family for m in matches})

        verdict = "allow"
        if score >= block_threshold:
            verdict = "block"
        elif score >= flag_threshold:
            verdict = "flag"

        return Detection(
            score=round(score, 3),
            verdict=verdict,
            matches=matches,
            families=families,
            signals=signals,
            latency_ms=int((time.perf_counter() - started) * 1000),
            content_sha256=sha,
            content_bytes=len(raw.encode("utf-8", "ignore")),
        )

    @staticmethod
    def _aggregate(matches: list[Match], signals: dict) -> float:
        """Noisy-OR over rule weights, then structural bonuses.

        Noisy-OR is the right shape here: ten weak signals should raise
        suspicion, but never as much as one unambiguous signal. Summing
        would let a document full of the word 'ignore' block itself.
        """
        if not matches and not signals:
            return 0.0

        # Everything -- rule weights, the multi-family tell, and the
        # hidden-content signals -- goes through ONE noisy-OR. Nothing is
        # added.
        #
        # The structural signals used to be additive bonuses on top of the
        # noisy-OR, and that was a real defect, not a stylistic choice: a
        # document carrying a unicode tag payload (+0.45), spaced-out text
        # (+0.30) and white-on-white HTML (+0.25) reached exactly 1.00 and
        # was blocked with `matched_rules: []`. Two things wrong with that.
        # A block nobody can explain is unusable in an audit log, which is
        # the part of this product people actually buy. And 1.00 means
        # certainty -- more than the strongest single unambiguous rule
        # (EX-002, a templated-URL markdown exfil, at 0.90) -- reached by
        # three circumstantial signals with no instruction found anywhere in
        # the text. Noisy-OR gives the behaviour the product claims: those
        # three now reach 0.71, which is a flag (look at this) rather than a
        # block (certain), and any real rule firing alongside them still
        # pushes it over.
        terms: list[float] = [m.weight for m in matches]

        # Distinct attack families in one document is a strong tell. Benign
        # text occasionally trips one family; it rarely trips three.
        families = {m.family for m in matches}
        if len(families) >= 3:
            terms.append(0.15)
        elif len(families) == 2:
            terms.append(0.07)

        # Hidden-content signals. These have almost no benign explanation in
        # a document being fed to an agent, so they are weighted heavily --
        # but as evidence, not as proof.
        if "unicode_tag_payload" in signals:
            terms.append(0.45)
        if signals.get("white_on_white"):
            terms.append(0.25)
        if "hidden_html" in signals:
            terms.append(0.20)
        if "invisible_chars" in signals:
            terms.append(0.10)
        if "spaced_obfuscation" in signals:
            terms.append(0.30)

        product = 1.0
        for weight in terms:
            product *= 1.0 - weight
        return min(1.0, 1.0 - product)


def sanitize(text: str, detection: Detection) -> str:
    """Neutralize rather than reject. Many pipelines would rather receive a
    defanged document than a hard failure, so this is the 'flag' path."""
    out = text
    for ch in INVISIBLE_CHARS:
        out = out.replace(ch, "")
    out = "".join(c for c in out if not (TAG_BLOCK[0] <= ord(c) <= TAG_BLOCK[1]))
    out = _HTML_COMMENT.sub("", out)
    out = _HTML_HIDDEN.sub("", out)
    for m in detection.matches:
        if m.weight >= 0.70:
            out = re.sub(
                re.escape(m.excerpt[:80]),
                "[airlock: removed suspected injection]",
                out,
                flags=re.IGNORECASE,
            )
    return out
