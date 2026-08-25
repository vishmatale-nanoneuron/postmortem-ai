"""Cloudflare Turnstile verification -- bot/script signup protection.

Optional, same "unconfigured means disabled" stance as every other
not-yet-provisioned integration in this codebase (Stripe, UPI, wire,
alerting): TURNSTILE_SECRET_KEY unset means verify_turnstile always
succeeds without a real check, so this doesn't block local dev or a
deploy that hasn't set up a real Turnstile site yet. Once a real secret
key is set, verification becomes real and mandatory.
"""

import httpx

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


async def verify_turnstile(secret_key: str | None, token: str | None, remote_ip: str | None = None) -> bool:
    if not secret_key:
        return True
    if not token:
        return False

    data = {"secret": secret_key, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(VERIFY_URL, data=data)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError:
        # Cloudflare being unreachable must not be indistinguishable from
        # "the user is a bot" -- but it also must not silently grant
        # access, so this fails closed (returns False), not open.
        return False

    return bool(result.get("success"))
