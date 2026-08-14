"""Direct-bcrypt password hashing (passlib removed for bcrypt 5.x compat).

passlib 1.7.4 silently truncated passwords at 72 bytes before hashing; the
replacement must keep doing so, or any hash minted under passlib for a longer
password stops verifying.
"""
from app.core.security import get_password_hash, hash_password, verify_password

# Minted with passlib 1.7.4 CryptContext(schemes=["bcrypt"]) before the migration.
PASSLIB_HASH_PASSWORD123 = "$2b$12$oKcPOLX4aJ9NvwRUS1IMduHo9sa5oq/cPr7t6MaphFKAsAsPhI.5G"
# passlib hash of "x" * 80 (truncated by passlib to its first 72 bytes).
PASSLIB_HASH_80_X = "$2b$12$lKc0Boshp9duqN6YlgMe.OCfmjeZO38suPWu0TS5VzbV7DpyklCCO"


def test_roundtrip():
    hashed = hash_password("s3cret-Pw!")
    assert hashed.startswith("$2b$")
    assert verify_password("s3cret-Pw!", hashed)
    assert not verify_password("wrong", hashed)


def test_legacy_passlib_hash_still_verifies():
    assert verify_password("password123", PASSLIB_HASH_PASSWORD123)
    assert not verify_password("password124", PASSLIB_HASH_PASSWORD123)


def test_long_password_does_not_raise():
    # bcrypt 5.x raises ValueError past 72 bytes unless truncated first
    hashed = hash_password("x" * 80)
    assert verify_password("x" * 80, hashed)


def test_72_byte_truncation_preserved():
    assert verify_password("x" * 80, PASSLIB_HASH_80_X)
    assert verify_password("x" * 72, PASSLIB_HASH_80_X)
    assert not verify_password("x" * 71, PASSLIB_HASH_80_X)


def test_malformed_hash_returns_false():
    assert not verify_password("anything", "not-a-bcrypt-hash")
    assert not verify_password("anything", "")


def test_alias_still_exported():
    assert get_password_hash is hash_password
