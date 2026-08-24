from app.security.passwords import hash_password, verify_password


def test_a_correct_password_verifies() -> None:
    stored = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", stored)


def test_a_wrong_password_is_rejected() -> None:
    stored = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", stored)


def test_two_hashes_of_the_same_password_differ() -> None:
    # Proves a random per-password salt is actually being used -- identical
    # hashes for the same password would mean the salt is fixed or missing.
    first = hash_password("same password")
    second = hash_password("same password")
    assert first != second
    assert verify_password("same password", first)
    assert verify_password("same password", second)


def test_a_malformed_stored_hash_is_rejected_not_a_crash() -> None:
    for malformed in ("", "not-scrypt$abc$def", "scrypt$onlyonepart", "scrypt$not-base64!!$also-not!!"):
        assert not verify_password("anything", malformed)
