"""Payment-link builders -- pure functions, no database and no network, so
unlike most of this suite these run everywhere, including a bare CI job.

These were originally appended to test_payment_details_email.py and silently
skipped there: that module has a file-level skipif on TEST_DATABASE_URL which
applies to every test in it, whether or not the test touches a database. A
test that never runs is worse than no test.
"""


def test_the_upi_link_prefills_payee_and_amount() -> None:
    """The whole point: a client should never hand-type the amount. A
    mistyped amount is what stops a payment matching its claim in
    bank_alerts.py, which reaches the customer as a rejected claim after
    they have actually paid."""
    from app.services.email import build_upi_payment_link

    link = build_upi_payment_link("founder@upi", "Nanoneuron", 999)
    assert link.startswith("upi://pay?")
    assert "pa=founder%40upi" in link
    assert "am=999" in link
    assert "cu=INR" in link


def test_the_upi_link_encodes_characters_that_would_break_the_query_string() -> None:
    """An unencoded '&' in a payee name silently truncates the URI, giving a
    link that opens a UPI app with a missing amount -- worse than no link at
    all, because it still looks like it worked."""
    from app.services.email import build_upi_payment_link

    link = build_upi_payment_link("a@b", "Vishal & Co", 999)
    assert "%26" in link
    assert "&pn=Vishal & Co" not in link
    assert "am=999" in link


def test_the_upi_link_handles_a_non_ascii_payee_name() -> None:
    from app.services.email import build_upi_payment_link

    link = build_upi_payment_link("x@y", "नैनो", 1500)
    assert "am=1500" in link
    assert " " not in link  # fully percent-encoded, safe inside an href
