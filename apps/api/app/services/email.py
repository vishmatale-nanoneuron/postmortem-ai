"""Transactional email via Resend (Vercel Marketplace integration --
provisioned against the real nanoneuron.ai sending domain, not a
placeholder). Kept as small, purpose-specific functions rather than a
generic "send_email" abstraction since each caller has exactly one real
template and no shared logic worth factoring out yet.
"""

import hashlib
import logging

from urllib.parse import quote, urlencode

import resend

from ..settings import Settings

logger = logging.getLogger("postmortem_ai")


class EmailNotConfiguredError(RuntimeError):
    """Raised when RESEND_API_KEY/RESEND_EMAIL_DOMAIN aren't set -- callers
    turn this into a 503, same "unconfigured means off" stance as the
    UPI/wire 'configured' checks and every other optional integration."""


def send_password_reset_email(settings: Settings, to_email: str, reset_url: str) -> None:
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    # idempotency_key ties retries of the *same* logical request to one
    # send -- without it, a client-side retry after a slow/ambiguous
    # response could send the same link twice. Hashed (not the raw URL,
    # which embeds a JWT and can exceed Resend's 256-char key limit);
    # scoped to the URL itself since a new request always mints a new
    # token/URL, so this never suppresses a genuinely new reset request.
    url_fingerprint = hashlib.sha256(reset_url.encode()).hexdigest()
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Reset your PostMortem AI password",
            "html": (
                "<p>Someone requested a password reset for this account. "
                f'If that was you, <a href="{reset_url}">click here to choose a new password</a> '
                "-- this link expires in 30 minutes and can only be used once.</p>"
                "<p>If you didn't request this, no action is needed -- your password hasn't changed.</p>"
            ),
        },
        {"idempotency_key": f"password-reset/{url_fingerprint}"},
    )
    logger.info("password_reset_email_sent")


def send_purchase_reminder_email(settings: Settings, to_email: str, user_id: str, *, days_since_signup: int) -> None:
    """The one automated nudge this app sends toward a purchase decision,
    for an account that signed up, never paid for either product, and has
    had at least a day. Sent at most once per account, ever.

    Both products are paid from the first use, so the email does the job a
    trial would have done: it points at the real output (the worked example
    drafted from a public outage; the live engine replay on /airlock), the
    prices, and how to pay from anywhere. Never a fabricated urgency claim
    ("only 2 spots left", a countdown, a discount that isn't real) -- this
    app's own core invariant against inventing anything not literally true
    extends to how it asks for money, not just what it drafts."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    site = settings.frontend_url
    when = "yesterday" if days_since_signup <= 1 else f"{days_since_signup} days ago"
    # Idempotency key is scoped to the user, not a per-send fingerprint --
    # this email goes out at most once ever per account (enforced by
    # free_incident_reminder_sent_at at the call site), so any retry of the
    # same logical send collapses to the same Resend send.
    resend.Emails.send(
        {
            "from": f"NanoNeuron <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Before you decide: the real output, and how to pay from anywhere",
            "html": (
                f"<p>You created a NanoNeuron account {when} and have not started anything yet. Both products "
                "are paid from the first use -- there is no free tier -- so here is the honest way to judge them "
                "before paying:</p>"
                f'<p><strong>PostMortem AI</strong> -- read <a href="{site}/blog/github-outage-demo">the full '
                "postmortem it drafted from a real public outage</a>. Every claim cites a recorded piece of "
                "evidence; anything the evidence does not say is left out rather than made up. That is exactly "
                "the output you would get on your own incidents.</p>"
                f'<p><strong>Airlock</strong> -- <a href="{site}/airlock">the Airlock page</a> replays the real '
                "detection engine on captured injection attempts: the rules that fired, the scores, the verdicts. "
                "It also fetches and screens URLs before your agent reads them.</p>"
                f'<p><strong>Prices.</strong> PostMortem AI: \u20b9{settings.subscription_price_inr}/month, or '
                f"${settings.subscription_price_usd} / \u00a3{settings.subscription_price_gbp} / "
                f"\u20ac{settings.subscription_price_eur} -- <a href=\"{site}/pricing\">details</a>. Airlock: "
                f"{settings.airlock_pack_scans:,} scan credits for \u20b9{settings.airlock_pack_price_inr} / "
                f"${settings.airlock_pack_price_usd} / \u00a3{settings.airlock_pack_price_gbp} / "
                f'\u20ac{settings.airlock_pack_price_eur} -- <a href="{site}/airlock#pricing">details</a>.</p>'
                "<p><strong>Paying from anywhere.</strong> UPI in India; an international bank wire in USD, GBP or "
                "EUR from any other country. The payee details are emailed to you from your dashboard, and the "
                "founder verifies each payment by hand, usually the same day, with a confirmation email when it "
                "lands. A wire costs the sender a bank fee, so for Airlock it is worth buying several packs at "
                "once, and for PostMortem AI the annual plan (two months free) is the sensible choice.</p>"
                "<p>This is the only reminder you will get from us. If you have a question, reply to this email "
                "and it reaches the founder directly.</p>"
            ),
        },
        {"idempotency_key": f"purchase-reminder/{user_id}"},
    )
    logger.info("purchase_reminder_email_sent")


def build_upi_payment_link(upi_id: str, payee_name: str, amount_inr: int) -> str:
    """An NPCI UPI deep link (`upi://pay?...`), built by hand from the spec.

    Deliberately zero-dependency: this is a URI scheme, not an API, so there
    is no SDK, no vendor, no fee and no account involved -- the money still
    moves bank-to-bank exactly as before. It only removes typing.

    Why it matters: before this, a client received a bare UPI ID and had to
    copy it, then type the amount themselves. A hand-typed amount is the one
    input most likely to be wrong, and a wrong amount is precisely what stops
    a payment matching its claim in bank_alerts.py -- which surfaces to the
    customer as a rejected claim after they have actually paid. Pre-filling
    payee and amount removes that failure mode at the source.

    Every value is percent-encoded: a payee name with a space or an "&"
    would otherwise silently truncate the query string and produce a link
    that opens a UPI app with the wrong (or missing) payee.
    """
    params = urlencode(
        {"pa": upi_id, "pn": payee_name, "am": str(amount_inr), "cu": "INR"},
        quote_via=quote,
    )
    return f"upi://pay?{params}"


def send_upi_payment_details_email(
    settings: Settings, to_email: str, request_id: str, upi_id: str, payee_name: str, amount_inr: int
) -> None:
    """Self-serve replacement for a client having to email the founder to
    receive the real UPI ID (see billing.py's POST /upi/email-details). The
    account details stay founder-only via GET /upi/info -- never returned
    from an API response a scraper or throwaway account could read -- but a
    genuine, already-authenticated client can now reach them without a
    manual round-trip. request_id is a fresh per-request nonce from the
    caller, not derived from the (static) account details themselves, so a
    deliberate second send after the rate-limit window still goes out --
    only a client-side retry of the exact same request collapses to one
    Resend send, same idempotency reasoning as send_password_reset_email."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    payment_link = build_upi_payment_link(upi_id, payee_name, amount_inr)

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Your PostMortem AI UPI payment details",
            "html": (
                f"<p>Pay <strong>₹{amount_inr}/month</strong> via UPI.</p>"
                f'<p><a href="{payment_link}" style="display:inline-block;background:#1a1a1a;color:#f7f7f5;'
                f'padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600">'
                f"Pay ₹{amount_inr} with any UPI app</a></p>"
                "<p style=\"font-size:13px;color:#555\">Opens your UPI app with the payee and amount already "
                "filled in. Tap it on the phone your UPI app is installed on.</p>"
                f"<p style=\"font-size:13px;color:#555\">Prefer to enter it manually? UPI ID: <code>{upi_id}</code>"
                f"<br>Payee name: {payee_name} &middot; Amount: ₹{amount_inr}</p>"
                "<p>Once you've paid, go back to the UPI tab in your dashboard and submit the transaction "
                "reference / UTR number from your payment app -- your account is activated once that's reviewed.</p>"
            ),
        },
        {"idempotency_key": f"upi-details/{request_id}"},
    )
    logger.info("upi_payment_details_email_sent")


def send_wire_payment_details_email(
    settings: Settings,
    to_email: str,
    request_id: str,
    currency: str,
    amount: int,
    account_name: str,
    account_number: str,
    bank_name: str,
    swift_code: str,
    correspondent_bank: str,
    correspondent_swift: str,
    nostro_account: str,
    routing_reference: str,
) -> None:
    """Wire-transfer equivalent of send_upi_payment_details_email above --
    same reasoning, same idempotency shape."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": f"Your PostMortem AI wire payment details ({currency})",
            "html": (
                f"<p>Pay <strong>{currency} {amount}/month</strong> via SWIFT wire to:</p>"
                f"<p>Account name: {account_name}<br>Account number: <code>{account_number}</code><br>"
                f"Bank: {bank_name}<br>SWIFT/BIC: <code>{swift_code}</code></p>"
                f"<p>Correspondent bank: {correspondent_bank}<br>Correspondent SWIFT: "
                f"<code>{correspondent_swift}</code><br>Intermediary/nostro account: "
                f"<code>{nostro_account}</code><br>Routing reference (ABA/IBAN): <code>{routing_reference}</code></p>"
                # The single most important instruction in this email, and it
                # was missing entirely. Correspondent banks deduct their fees
                # from the transfer itself under SHA/BEN charge codes, so a
                # customer who sends the exact price has *less* than the price
                # arrive. bank_alerts.py matches on an exact amount
                # (amount != claim.amount_inr -> no auto-verification), which
                # means a short-landing wire silently fails to verify and has
                # to be reconciled by hand, every time. "OUR" makes the sender
                # bear those fees so the full amount lands and matching works.
                f'<p style="background:#fff8e1;border-left:3px solid #b8860b;padding:10px 14px">'
                f"<strong>Important:</strong> please send with charge code <code>OUR</code> "
                f"(sender pays all fees). Under <code>SHA</code> or <code>BEN</code>, intermediary "
                f"banks deduct their fees from the transfer, so less than {currency} {amount} arrives "
                "-- which delays activation while it's reconciled by hand.</p>"
                f"<p>Please also put your account email in the payment reference/message field, so the "
                "transfer can be matched to your account.</p>"
                # A large share of this product's audience is Indian DevOps/SRE
                # engineers working abroad. NRIs in 12 countries (US, UK,
                # Canada, Australia, Singapore, UAE, Saudi Arabia, Qatar,
                # Oman, Malaysia, Hong Kong, France) can pay by UPI from an
                # international mobile number linked to an NRE/NRO account --
                # instant, and with none of the wire fees above. Nobody was
                # telling them, so they were paying USD 15-40 in charges to
                # send a payment they could have made for free.
                f'<p style="background:#f0f7f4;border-left:3px solid #2a6e5c;padding:10px 14px">'
                f"<strong>Have an Indian bank account?</strong> If you're an NRI with an NRE/NRO "
                f"account, you can pay by <strong>UPI instead</strong> -- instantly, with no wire "
                f"fees at all. Request UPI details from the payment tab in your dashboard.</p>"
                "<p>Once you've sent it, go back to the Wire tab in your dashboard and submit the transaction "
                "reference from your MT103 -- your account is activated once that's reviewed.</p>"
            ),
        },
        {"idempotency_key": f"wire-details/{request_id}"},
    )
    logger.info("wire_payment_details_email_sent")


def send_founder_claim_notification(
    settings: Settings, claim_id: str, method: str, currency: str, amount: int, reference: str, payer_email: str
) -> None:
    """The gap this closes: before this existed, a real customer could pay
    real money, submit a claim (POST /v1/billing/upi/claim or /wire/claim),
    and it would land as a 'pending' row in payment_claims with nothing
    telling the founder it exists -- discoverable only by opening the
    founder dashboard and noticing the pending_payment_claims count went
    up. Best-effort and non-blocking by design: raised inside a try/except
    at the call site (see billing.py's _insert_claim) so a Resend outage
    never turns a real, valid payment claim into a failed submission for
    the customer -- the claim itself is the record of truth; this email is
    only a faster way to notice it, not a required step in creating it."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    dashboard_url = f"{settings.frontend_url}/founder"
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [settings.founder_email],
            "subject": f"New {method.upper()} payment claim -- {currency} {amount}",
            "html": (
                f"<p>A new payment claim was just submitted: <strong>{currency} {amount}</strong> via "
                f"<strong>{method.upper()}</strong>, from <strong>{payer_email}</strong>.</p>"
                f"<p>Reference: <code>{reference}</code></p>"
                f'<p><a href="{dashboard_url}">Review and approve or reject it in the founder dashboard</a>. '
                "Nothing is granted automatically -- this claim stays pending until you act on it.</p>"
            ),
        },
        # Idempotent per claim, not per send -- a retry of the same claim
        # submission (if the route were ever retried) should never produce
        # a second notification for one real claim.
        {"idempotency_key": f"claim-notification/{claim_id}"},
    )
    logger.info("founder_claim_notification_sent", extra={"claim_id": claim_id, "method": method})


def send_client_claim_confirmation(
    settings: Settings, claim_id: str, to_email: str, method: str, currency: str, amount: int, reference: str
) -> None:
    """The client-side counterpart to send_founder_claim_notification above
    -- before this existed, submitting a claim only ever produced an inline
    UI message (see workspace.tsx's UpiPayment/WirePayment 'Submitted...'
    text); a client who closed the tab had no record anywhere that their
    claim was received, what reference they submitted, or what happens
    next. Same best-effort, non-blocking call site as the founder
    notification (see billing.py's _insert_claim) and the same per-claim
    idempotency reasoning -- the payment_claims row is the real record
    either way; this is only ever a courtesy copy of it."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "We've received your payment claim",
            "html": (
                f"<p>Your <strong>{method.upper()}</strong> payment claim for <strong>{currency} {amount}</strong> "
                f"has been received, with reference <code>{reference}</code>.</p>"
                "<p>The founder reviews every claim by hand before activating an account -- there's no automatic "
                "approval. You'll be able to see the outcome in your dashboard, typically within a day.</p>"
                "<p>If the reference above has a typo, you can correct it or withdraw the claim from the "
                "payment tab in your dashboard as long as it's still pending.</p>"
                f'<p>Need a document for your finance team? Your <a href="{settings.frontend_url}/invoice/{claim_id}">'
                "proforma invoice</a> is ready now, and becomes the receipt once the payment is verified.</p>"
            ),
        },
        {"idempotency_key": f"claim-confirmation/{claim_id}"},
    )
    logger.info("client_claim_confirmation_sent", extra={"claim_id": claim_id, "method": method})


def send_client_claim_approved_email(settings: Settings, claim_id: str, to_email: str, method: str) -> None:
    """The missing end of the manual-payment conversation. A client could
    submit a claim and receive send_client_claim_confirmation above -- which
    literally tells them "you'll be able to see the outcome in your
    dashboard" -- and then never hear anything again. On a rail where
    approval is manual and asynchronous (the founder reviews by hand,
    possibly hours later, see founder.py's approve_payment_claim), that left
    a paying customer with no way to learn their access had turned on except
    repeatedly logging in to check.

    Deliberately says nothing about amounts or references: this fires after
    the subscription is already active, so the useful content is "it's on,
    here's what to do next," not a restatement of the receipt they already
    got."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Your payment is approved -- your account is active",
            "html": (
                f"<p>Your <strong>{method.upper()}</strong> payment has been reviewed and approved. "
                "Your subscription is active now -- nothing else to do.</p>"
                "<p>You can record an incident, add evidence, and generate a grounded postmortem draft "
                "straight away. Every claim in a draft cites a real evidence entry you recorded; anything "
                "the evidence doesn't support is marked unsupported rather than invented, and publishing "
                "always records you as the named approver.</p>"
                f'<p>Your <a href="{settings.frontend_url}/invoice/{claim_id}">receipt</a> is in your dashboard, '
                "printable, with the amount, reference and date the payment was verified.</p>"
                "<p>If anything looks wrong with your account, reply to this email.</p>"
            ),
        },
        {"idempotency_key": f"claim-approved/{claim_id}"},
    )
    logger.info("client_claim_approved_sent", extra={"claim_id": claim_id, "method": method})


def send_client_claim_rejected_email(settings: Settings, claim_id: str, to_email: str, method: str) -> None:
    """Counterpart to send_client_claim_approved_email above, for the other
    outcome. Worse to omit than the approval, not better: a client whose
    claim is rejected has usually either paid and had the reference fail to
    match, or mistyped it -- both cases where silence reads as "my money
    vanished."

    Deliberately non-accusatory and gives a real next step. It never asserts
    the customer didn't pay -- the founder rejects a claim when it can't be
    matched, which is not the same thing."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"PostMortem AI <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "We couldn't match your payment claim",
            "html": (
                f"<p>Your <strong>{method.upper()}</strong> payment claim was reviewed but couldn't be "
                "matched to a payment we've received, so it hasn't activated an account.</p>"
                "<p>This is usually a mistyped transaction reference, or a transfer still in flight -- "
                "international wires in particular can take a few working days to land.</p>"
                "<p><strong>If you have paid:</strong> reply to this email with the transaction reference "
                "and the date, and it'll be sorted out by hand. You have not lost your payment.</p>"
                "<p>You can also submit a fresh claim from the payment tab in your dashboard.</p>"
            ),
        },
        {"idempotency_key": f"claim-rejected/{claim_id}"},
    )
    logger.info("client_claim_rejected_sent", extra={"claim_id": claim_id, "method": method})


# ---------------------------------------------------------------------------
# Airlock. Same rails, different product: the emails above say "/month" and
# "your subscription is active", both of which would be false for a pack of
# scans. Two templates rather than parameterising the subscription ones,
# because the useful content differs (a pack email should say how many
# scans; an activation email should say where the API key lives).
# ---------------------------------------------------------------------------


def send_airlock_payment_details_email(
    settings: Settings,
    to_email: str,
    request_id: str,
    *,
    method: str,
    currency: str,
    amount: int,
    scan_credits: int,
    lines: list[tuple[str, str]],
    upi_link: str | None = None,
) -> None:
    """Account details for paying for an Airlock pack. `lines` is the
    method-specific label/value list (UPI ID and payee, or the wire
    beneficiary and correspondent rows) assembled by the route from
    settings; this function never reads bank settings itself. Same
    idempotency shape as send_upi_payment_details_email."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    symbol = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€"}.get(currency, currency + " ")
    detail_rows = "".join(f"<br>{label}: <code>{value}</code>" for label, value in lines if value)
    button = (
        f'<p><a href="{upi_link}" style="display:inline-block;background:#1a1a1a;color:#f7f7f5;'
        f'padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600">'
        f"Pay {symbol}{amount} with any UPI app</a></p>"
        if upi_link
        else ""
    )
    charge_note = (
        "<p style=\"font-size:13px;color:#555\">Send with the OUR charge code so the full amount arrives; "
        "a wire that lands short cannot be matched to your claim. Your bank will charge you a fee for the "
        "wire (commonly USD 15-40); the amount above already covers several packs if you chose them, and "
        "buying more packs per wire is the way to keep that fee a small share of what you pay.</p>"
        if method == "wire"
        else ""
    )
    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"Airlock by NanoNeuron <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": f"Airlock: payment details for {scan_credits:,} scans",
            "html": (
                f"<p>Pay <strong>{symbol}{amount}</strong> ({currency}) for <strong>{scan_credits:,} Airlock scans</strong> "
                f"via {method.upper()}.</p>"
                + button
                + f"<p style=\"font-size:13px;color:#555\">Details{detail_rows}</p>"
                + charge_note
                + "<p>Once you've paid, go back to the Airlock section of your dashboard and submit the transaction "
                "reference. Your credits are added the moment the payment is verified -- usually within the day -- "
                "and you'll get an email when that happens.</p>"
            ),
        },
        {"idempotency_key": f"airlock-details/{request_id}"},
    )
    logger.info("airlock_payment_details_email_sent", extra={"method": method})


def send_airlock_credits_approved_email(settings: Settings, claim_id: str, to_email: str, method: str) -> None:
    """Airlock's counterpart to send_client_claim_approved_email. Fires
    after the credits are already on the account, so it says what to do
    next -- mint a key and call the API -- rather than restating the
    receipt."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    resend.Emails.send(
        {
            "from": f"Airlock by NanoNeuron <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": "Your Airlock credits are live",
            "html": (
                f"<p>Your <strong>{method.upper()}</strong> payment has been verified and your Airlock scan credits "
                "are on your account now -- nothing else to do.</p>"
                "<p>To start scanning: open the Airlock section of your dashboard, create an API key (it is shown "
                "once, so copy it), and call <code>POST /v1/airlock/scan</code> with the key in an "
                "<code>X-Airlock-Key</code> header. Every response tells you how many credits remain.</p>"
                f'<p>Your <a href="{settings.frontend_url}/invoice/{claim_id}">receipt</a> is in your dashboard, '
                "printable, with the amount, reference and date the payment was verified.</p>"
                "<p>If anything looks wrong with your balance, reply to this email.</p>"
            ),
        },
        {"idempotency_key": f"airlock-approved/{claim_id}"},
    )
    logger.info("airlock_credits_approved_sent", extra={"claim_id": claim_id, "method": method})


def send_airlock_balance_email(settings: Settings, to_email: str, remaining: int, *, empty: bool) -> None:
    """Sent on the call that takes the balance below the low-water mark, and
    again on the call that empties it. A prepaid service that goes quiet
    when the money runs out fails the customer at the worst moment -- their
    agent starts getting 402s in production with no warning."""
    if not settings.resend_api_key or not settings.resend_email_domain:
        raise EmailNotConfiguredError("RESEND_API_KEY/RESEND_EMAIL_DOMAIN are not configured")

    resend.api_key = settings.resend_api_key
    if empty:
        subject = "Airlock: your credits are used up -- scans are now refused"
        lead = (
            "<p>Your Airlock balance is <strong>0</strong>. Every scan and egress check now answers "
            "<code>402</code> until you buy another pack; nothing is scanned and nothing is charged in the meantime.</p>"
        )
    else:
        subject = f"Airlock: {remaining:,} credits left"
        lead = (
            f"<p>Your Airlock balance has dropped to <strong>{remaining:,}</strong> credits. At your current rate "
            "it is worth buying the next pack before it runs out, so your agents never see a 402.</p>"
        )
    resend.Emails.send(
        {
            "from": f"Airlock by NanoNeuron <noreply@{settings.resend_email_domain}>",
            "to": [to_email],
            "subject": subject,
            "html": (
                lead
                + "<p>Buy a pack from the Airlock section of your dashboard: pick a currency and pack count, have the "
                "payee details emailed to you, pay by UPI or wire, and submit the reference. Credits land the moment "
                "the payment is verified.</p>"
                "<p>Every API response carries <code>credits_remaining</code>, so an integration can alert on this "
                "too.</p>"
            ),
        },
        # One send per crossing per balance value: a retried request for
        # the same crossing collapses, a later crossing does not.
        {"idempotency_key": f"airlock-balance/{to_email}/{'empty' if empty else 'low'}/{remaining}"},
    )
    logger.info("airlock_balance_email_sent", extra={"remaining": remaining, "empty": empty})
