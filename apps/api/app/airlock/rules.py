"""Seed detection rules.

Design notes:
- Every rule carries a weight, not a boolean. Verdicts come from accumulated
  score, so a single weak signal never blocks on its own.
- Rules are deliberately conservative. False positives kill adoption faster
  than misses, because a blocked legitimate document is visible and a missed
  attack usually is not.
- Weights above 0.75 are reserved for patterns with no plausible benign use.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    family: str
    pattern: str
    weight: float
    is_regex: bool = True
    description: str = ""


RULES: list[Rule] = [
    # ---- instruction override -------------------------------------------
    Rule(
        "IO-001",
        "instruction_override",
        r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?|directions?)",
        0.80,
        description="Classic instruction-override phrasing.",
    ),
    Rule(
        "IO-002",
        "instruction_override",
        r"disregard\s+(everything|all|the)\s+(above|before|prior|previous)",
        0.75,
        description="Tells the model to disregard everything above it in the context.",
    ),
    Rule(
        "IO-003",
        "instruction_override",
        r"forget\s+(your|all|the)\s+(instructions?|training|rules?|guidelines?|system\s+prompt)",
        0.75,
        description="Tells the model to forget its instructions, training or guidelines.",
    ),
    Rule(
        "IO-004",
        "instruction_override",
        r"(new|updated|revised)\s+(system\s+)?(instructions?|directive|prompt)\s*[:\-]",
        0.60,
        description="Announces replacement instructions, as though the prompt were being updated.",
    ),
    Rule(
        "IO-005",
        "instruction_override",
        r"from\s+now\s+on\s*,?\s*(you\s+(will|must|should|are)|ignore|respond)",
        0.55,
        description="\"From now on\" framing -- redefines behaviour for the rest of the session.",
    ),
    # ---- role hijack -----------------------------------------------------
    Rule(
        "RH-001",
        "role_hijack",
        r"you\s+are\s+(now\s+)?(a\s+|an\s+)?(dan|developer\s+mode|unrestricted|jailbroken|uncensored)",
        0.85,
        description="Names a known jailbreak persona (DAN, developer mode, unrestricted, uncensored).",
    ),
    Rule(
        "RH-002",
        "role_hijack",
        r"(enter|enable|activate)\s+(developer|debug|god|admin|maintenance)\s+mode",
        0.70,
        description="Asks the model to enter a privileged mode that does not exist.",
    ),
    Rule(
        "RH-003",
        "role_hijack",
        r"pretend\s+(you\s+are|to\s+be)\s+(not\s+)?(an?\s+)?(ai|assistant|bound|restricted)",
        0.55,
        description="Asks the model to pretend it is not an AI, or not bound by its rules.",
    ),
    Rule(
        "RH-004",
        "role_hijack",
        r"your\s+(real|true|actual)\s+(purpose|goal|instruction|directive)\s+is",
        0.60,
        description="Claims to reveal the model's \"real\" purpose, overriding the stated one.",
    ),
    # ---- delimiter / context break --------------------------------------
    Rule(
        "DB-001",
        "delimiter_break",
        r"</?(system|assistant|human|instructions?|s>)\s*>",
        0.70,
        description="Fake chat-role tags injected into document text.",
    ),
    Rule(
        "DB-002",
        "delimiter_break",
        r"\[\/?(INST|SYS|SYSTEM|ASSISTANT)\]",
        0.70,
        description="Fake [INST]/[SYS] delimiters borrowed from instruction-tuned prompt formats.",
    ),
    Rule(
        "DB-003",
        "delimiter_break",
        r"(\|im_start\||\|im_end\||<\|endoftext\|>)",
        0.75,
        description="Raw chat-template tokens (im_start, im_end, endoftext) inside document text.",
    ),
    Rule(
        "DB-004",
        "delimiter_break",
        r"^\s*#{0,3}\s*(system|assistant)\s*:\s*$",
        0.45,
        description="A bare \"system:\" or \"assistant:\" line, imitating the start of a new turn.",
    ),
    # ---- exfiltration ----------------------------------------------------
    Rule(
        "EX-001",
        "exfiltration",
        r"(send|post|upload|forward|transmit|exfiltrate)\s+(the\s+|all\s+|this\s+|your\s+)?"
        r"(conversation|history|context|system\s+prompt|credentials?|keys?|tokens?|secrets?|data)",
        0.85,
        description="Instructs the agent to send, post, upload or forward data somewhere.",
    ),
    Rule(
        "EX-002",
        "exfiltration",
        r"!\[.*?\]\(https?://[^)]*\{\{?[^)]*\}\}?[^)]*\)",
        0.90,
        description="Markdown image with templated URL — classic silent exfil.",
    ),
    Rule(
        "EX-003",
        "exfiltration",
        r"(reveal|print|output|repeat|show)\s+(your|the)\s+(system\s+prompt|initial\s+instructions?|configuration)",
        0.75,
        description="Asks the model to reveal its system prompt or initial configuration.",
    ),
    Rule(
        "EX-004",
        "exfiltration",
        r"https?://[^\s]{0,80}\?(q|d|data|payload|c|x)=[^\s]{40,}",
        0.65,
        description="Long opaque query string — probable data channel.",
    ),
    Rule(
        "EX-005",
        "exfiltration",
        r"(curl|wget|fetch|requests\.(get|post))\s*\(?['\"]?https?://",
        0.50,
        description="Embeds a curl/wget/fetch call to an external URL.",
    ),
    # ---- tool abuse ------------------------------------------------------
    Rule(
        "TA-001",
        "tool_abuse",
        r"(call|invoke|use|execute)\s+the\s+\w+\s+tool\s+(with|to)\s+",
        0.55,
        description="Directs the agent to call a specific tool -- content deciding the agent's actions.",
    ),
    Rule(
        "TA-002",
        "tool_abuse",
        r"(delete|drop|truncate|rm\s+-rf|wipe|purge)\s+(all\s+|the\s+|every\s+)?"
        r"(files?|records?|rows?|tables?|database|bucket|repo)",
        0.70,
        description="Asks for a destructive tool action: delete, drop, truncate, wipe or purge.",
    ),
    Rule(
        "TA-003",
        "tool_abuse",
        r"(without|skip|bypass|no\s+need\s+for)\s+(asking|confirmation|approval|checking)",
        0.70,
        description="Attempts to suppress the human-in-the-loop gate.",
    ),
    Rule(
        "TA-004",
        "tool_abuse",
        r"the\s+user\s+(has\s+)?(already\s+)?(approved|authorized|consented|pre-approved)",
        0.75,
        description="Fabricated authorization claim inside untrusted content.",
    ),
    # ---- authority spoofing ---------------------------------------------
    Rule(
        "AS-001",
        "authority_spoof",
        r"(this\s+is\s+)?(a\s+)?(message|note|instruction)\s+from\s+"
        r"(anthropic|openai|your\s+(developer|creator|admin|operator))",
        0.80,
        description="Impersonates the model vendor or the operator to manufacture authority.",
    ),
    Rule(
        "AS-002",
        "authority_spoof",
        r"(test|sandbox|staging|evaluation)\s+mode\s*[:\-]?\s*(enabled|active|on)",
        0.55,
        description="Claims a test or sandbox mode is active, implying the real rules do not apply.",
    ),
    Rule(
        "AS-003",
        "authority_spoof",
        r"(urgent|immediately|critical|do\s+not\s+delay)[^.]{0,40}(you\s+must|required\s+to)",
        0.40,
        description="Manufactured urgency paired with an obligation -- pressure to skip a check.",
    ),
    # ---- memory poisoning ------------------------------------------------
    Rule(
        "MP-001",
        "memory_poison",
        r"(remember|save|store|note)\s+(this|that|for\s+(all\s+)?future)\s*[:\-]?\s*"
        r"(always|never|from\s+now)",
        0.60,
        description="Asks the agent to remember a standing rule beyond this conversation.",
    ),
    Rule(
        "MP-002",
        "memory_poison",
        r"(add|append)\s+to\s+your\s+(memory|instructions?|system\s+prompt|context)",
        0.75,
        description="Asks the agent to append to its own memory, instructions or system prompt.",
    ),
    # ---- encoding / obfuscation -----------------------------------------
    Rule(
        "EN-001",
        "encoding",
        r"[A-Za-z0-9+/]{120,}={0,2}",
        0.35,
        description="Long base64 blob. Weak alone; strong with other signals.",
    ),
    Rule(
        "EN-002",
        "encoding",
        r"(\\u00[0-9a-f]{2}){8,}",
        0.45,
        description="A long run of \\u escapes -- text deliberately hidden from a plain reader.",
    ),
    Rule(
        "EN-003",
        "encoding",
        r"(decode|base64|rot13|reverse)\s+(the\s+following|this)\s+and\s+(then\s+)?(execute|follow|run|do)",
        0.85,
        description="Decode-then-execute: hides the payload and instructs the model to run it.",
    ),
]

RULES_BY_ID = {r.id: r for r in RULES}

# Invisible / bidi characters used to hide payloads from human reviewers.
INVISIBLE_CHARS = {
    "\u200b": "zero-width space",
    "\u200c": "zero-width non-joiner",
    "\u200d": "zero-width joiner",
    "\u2060": "word joiner",
    "\ufeff": "byte-order mark",
    "\u202a": "bidi embedding",
    "\u202b": "bidi embedding",
    "\u202d": "bidi override",
    "\u202e": "bidi override",
    "\u2066": "bidi isolate",
    "\u2067": "bidi isolate",
}

# Unicode tag block — renders as nothing, carries full ASCII payloads.
TAG_BLOCK = (0xE0000, 0xE007F)
