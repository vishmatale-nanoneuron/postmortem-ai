"""Parser unit tests against best-effort sample alert texts (no real bank
sample available yet -- see bank_alerts.py's module docstring). Kept
deliberately varied across common Indian bank phrasing so the patterns
aren't overfit to one exact wording.
"""

from app.bank_alerts import extract_amount, extract_reference, looks_like_a_credit


def test_extracts_upi_reference_and_amount_from_a_typical_credit_alert() -> None:
    text = (
        "Dear Customer, Rs.999.00 credited to your A/c No XX0454 on 25-08-26 "
        "through UPI Ref No 123456789012. -Axis Bank"
    )
    assert extract_reference(text) == "123456789012"
    assert extract_amount(text) == 999
    assert looks_like_a_credit(text) is True


def test_extracts_utr_reference_from_a_neft_style_alert() -> None:
    text = "An amount of INR 15.00 has been credited to your account via NEFT. UTR No: N123ABC456789"
    assert extract_reference(text) == "N123ABC456789"
    assert extract_amount(text) == 15


def test_a_debit_alert_is_never_treated_as_a_credit() -> None:
    # The one check that would be actively dangerous to get wrong.
    text = "Rs.999.00 debited from your A/c No XX0454 on 25-08-26. UPI Ref No 999888777666."
    assert looks_like_a_credit(text) is False


def test_unparseable_text_returns_none_rather_than_a_wrong_guess() -> None:
    text = "Your OTP for login is 482910. Do not share this with anyone."
    assert extract_reference(text) is None
    assert looks_like_a_credit(text) is False


def test_amount_with_comma_thousands_separator_parses_correctly() -> None:
    text = "Rs.1,999.00 credited to your account. Ref No: REF00099988877"
    assert extract_amount(text) == 1999
