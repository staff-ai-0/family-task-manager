"""B4: production config must fail fast on insecure default secrets.

A placeholder/empty SECRET_KEY means forgeable JWTs and session cookies. The app
must refuse to boot with one when DEBUG is false, while local/dev (DEBUG=true)
keeps working with the shipped default.
"""
import pytest
from pydantic import ValidationError

from app.core.config import Settings

DEFAULT_KEY = "your-secret-key-change-this-in-production"


def test_production_rejects_default_secret_key():
    with pytest.raises(ValidationError):
        Settings(DEBUG=False, SECRET_KEY=DEFAULT_KEY, _env_file=None)


def test_production_rejects_empty_secret_key():
    with pytest.raises(ValidationError):
        Settings(DEBUG=False, SECRET_KEY="", _env_file=None)


def test_production_allows_real_secret_key():
    s = Settings(DEBUG=False, SECRET_KEY="x" * 40, _env_file=None)
    assert s.SECRET_KEY == "x" * 40


def test_debug_allows_default_secret_key():
    # local/dev must keep working with the placeholder
    s = Settings(DEBUG=True, SECRET_KEY=DEFAULT_KEY, _env_file=None)
    assert s.DEBUG is True
