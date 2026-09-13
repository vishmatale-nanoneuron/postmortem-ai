# Airlock — Python SDK

The prompt-injection and exfiltration guard for AI agents, as three calls.
Paid per call from your key's prepaid credits; every non-200 raises, so a
caller that treats "any exception = block" fails closed.

```bash
pip install nanoneuron-airlock        # once published; until then: pip install ./sdk/python
```

```python
from airlock import Airlock, AirlockError

guard = Airlock(api_key="alk_...")

# Inbound: score untrusted text before it reaches the model. 1 credit.
result = guard.scan(document_text, source="web")
if result.blocked:
    raise RuntimeError(f"injection: {[m.rule_id for m in result.matches]}")

# Outbound: check a payload and its destination before sending. 1 credit.
check = guard.egress(payload, destination="https://hooks.slack.com/...", allowlist=["hooks.slack.com"])
if not check.allowed:
    payload = check.redacted or ""

# Proxy: let Airlock fetch the page and hand back text only if it passes. 2 credits.
page = guard.fetch("https://example.com/vendor-terms.html", allowlist=["example.com"])
if page.allowed:
    model_input = page.content
```

Async: `from airlock import AsyncAirlock` — same methods, `await`ed.

Errors: `AuthenticationError` (401), `InsufficientCredits` (402, nothing was
scanned), `RateLimited` (429, `.retry_after` seconds), `FetchRefused`
(proxy 422/502, verdict block), `AirlockError` (anything else). Every error
carries `.request_id`, which is what to quote if you ask about it.

Deep scan (`deep=True`, +4 credits) adds a Gemini second opinion that can only
raise a verdict; `sanitize=True` returns a defanged copy in `result.sanitized`.
Reference: https://www.nanoneuron.ai/docs#airlock
