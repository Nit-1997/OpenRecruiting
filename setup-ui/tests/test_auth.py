import json
import stat

import pytest

from app.auth import Auth, AuthError


@pytest.fixture
def auth(tmp_path):
    return Auth(tmp_path / "password.json")


def test_a_fresh_instance_needs_setup(auth):
    assert auth.needs_setup() is True


def test_setting_a_password_creates_a_0600_file_and_logs_you_in(auth, tmp_path):
    token = auth.set_password("a-good-password")

    assert auth.verify(token) is True
    assert auth.needs_setup() is False
    mode = stat.S_IMODE((tmp_path / "password.json").stat().st_mode)
    assert mode == 0o600, "the hash file must not be world-readable"


def test_the_password_is_never_stored_in_plaintext(auth, tmp_path):
    auth.set_password("correct horse battery staple")

    stored = (tmp_path / "password.json").read_text()
    assert "correct horse battery staple" not in stored
    assert set(json.loads(stored)) == {"salt", "hash", "iterations"}


def test_the_password_cannot_be_reset_by_an_unauthenticated_caller(auth):
    """Whoever claimed the instance owns it. If set_password worked twice,
    anyone reaching the port could take it over and the password would mean
    nothing."""
    auth.set_password("first-password")

    with pytest.raises(AuthError, match="already set"):
        auth.set_password("attacker-password")


def test_a_short_password_is_refused(auth):
    with pytest.raises(AuthError, match="at least 8"):
        auth.set_password("short")


def test_login_succeeds_with_the_right_password(auth):
    auth.set_password("a-good-password")

    assert auth.verify(auth.login("a-good-password")) is True


def test_login_fails_with_the_wrong_password(auth):
    auth.set_password("a-good-password")

    with pytest.raises(AuthError, match="Incorrect"):
        auth.login("not-the-password")


def test_repeated_failures_lock_the_door(auth):
    """This guards a Docker socket. Unlimited guesses against a local port is
    not an acceptable posture even behind a localhost bind."""
    auth.set_password("a-good-password")
    for _ in range(5):
        with pytest.raises(AuthError):
            auth.login("wrong")

    with pytest.raises(AuthError, match="Too many failed attempts"):
        auth.login("a-good-password")  # correct, but locked out


def test_a_successful_login_clears_the_failure_count(auth):
    auth.set_password("a-good-password")
    for _ in range(4):
        with pytest.raises(AuthError):
            auth.login("wrong")

    auth.login("a-good-password")

    for _ in range(4):
        with pytest.raises(AuthError, match="Incorrect"):
            auth.login("wrong")


def test_an_unknown_or_missing_token_is_rejected(auth):
    auth.set_password("a-good-password")

    assert auth.verify(None) is False
    assert auth.verify("") is False
    assert auth.verify("made-up-token") is False


def test_an_expired_token_is_rejected(auth, monkeypatch):
    import app.auth as module

    monkeypatch.setattr(module, "_TOKEN_TTL_SECONDS", -1)
    token = auth.set_password("a-good-password")

    assert auth.verify(token) is False
