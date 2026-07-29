import hmac
from http import HTTPStatus

import pytest

from runplan.users import WebError
from runplan.web_auth import (
    BLOCK_SECONDS,
    COOKIE_MAX_AGE,
    MAX_FAILURES,
    PBKDF2_ITERATIONS,
    WebAuthenticator,
    format_password_hash,
    login_proof,
    parse_password_hash,
)


class Clock:
    def __init__(self) -> None:
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


def authenticator(password="shared secret", *, clock=None, **environment):
    values = {"RUNPLAN_WEB_PASSWORD": password, **environment}
    return WebAuthenticator.from_environment(values, clock=clock or Clock())


def test_password_hash_round_trips_browser_compatible_verifier() -> None:
    encoded = format_password_hash("correct horse", salt=b"0123456789abcdef")

    iterations, salt, verifier = parse_password_hash(encoded)

    assert iterations == PBKDF2_ITERATIONS
    assert salt == b"0123456789abcdef"
    assert len(verifier) == 32
    auth = WebAuthenticator.from_environment({"RUNPLAN_WEB_PASSWORD_HASH": encoded})
    challenge = auth.issue_challenge("127.0.0.1")
    auth.verify_login(
        "127.0.0.1",
        {"challengeId": challenge["challengeId"], "proof": login_proof("correct horse", challenge)},
    )


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"RUNPLAN_WEB_PASSWORD": "secret", "RUNPLAN_WEB_PASSWORD_HASH": "hash"},
        {"RUNPLAN_WEB_PASSWORD_HASH": "invalid"},
        {"RUNPLAN_WEB_PASSWORD": ""},
    ],
)
def test_authenticator_rejects_missing_ambiguous_or_invalid_configuration(environment) -> None:
    with pytest.raises(ValueError):
        WebAuthenticator.from_environment(environment)


def test_challenge_is_single_use_peer_bound_and_expires() -> None:
    clock = Clock()
    auth = authenticator(clock=clock)
    challenge = auth.issue_challenge("peer-one")
    payload = {
        "challengeId": challenge["challengeId"],
        "proof": login_proof("shared secret", challenge),
    }

    with pytest.raises(WebError, match="Incorrect password"):
        auth.verify_login("peer-two", payload)
    with pytest.raises(WebError, match="Incorrect password"):
        auth.verify_login("peer-one", payload)

    expired = auth.issue_challenge("peer-one")
    clock.value += 61
    with pytest.raises(WebError, match="Incorrect password"):
        auth.verify_login(
            "peer-one",
            {"challengeId": expired["challengeId"], "proof": login_proof("shared secret", expired)},
        )


def test_failed_logins_are_temporarily_rate_limited_and_success_resets_failures() -> None:
    clock = Clock()
    auth = authenticator(clock=clock)
    for _ in range(MAX_FAILURES):
        challenge = auth.issue_challenge("peer")
        with pytest.raises(WebError) as error:
            auth.verify_login("peer", {"challengeId": challenge["challengeId"], "proof": "wrong"})
        assert error.value.status == HTTPStatus.UNAUTHORIZED

    with pytest.raises(WebError) as blocked:
        auth.verify_login("peer", {})
    assert blocked.value.status == HTTPStatus.TOO_MANY_REQUESTS
    assert blocked.value.headers["Retry-After"] == str(BLOCK_SECONDS)

    clock.value += BLOCK_SECONDS
    challenge = auth.issue_challenge("peer")
    auth.verify_login(
        "peer",
        {"challengeId": challenge["challengeId"], "proof": login_proof("shared secret", challenge)},
    )
    assert auth.retry_after("peer") == 0


def test_cookie_is_persistent_http_only_and_invalidated_by_password_change() -> None:
    first = authenticator("first password")
    same = authenticator("first password")
    changed = authenticator("changed password")
    header = first.cookie_header(secure=True)
    value = header.split(";", 1)[0].split("=", 1)[1]

    assert first.is_authorized(value)
    assert same.is_authorized(value)
    assert not changed.is_authorized(value)
    assert f"Max-Age={COOKIE_MAX_AGE}" in header
    assert "HttpOnly" in header
    assert "SameSite=Strict" in header
    assert "Secure" in header
    assert "Secure" not in first.cookie_header(secure=False)


@pytest.mark.parametrize(
    ("peer", "environment", "forwarded_proto", "allowed"),
    [
        ("127.0.0.1", {}, None, True),
        ("203.0.113.1", {}, None, False),
        ("203.0.113.1", {"RUNPLAN_WEB_TRUST_PROXY": "true"}, "https", True),
        ("203.0.113.1", {}, "https", False),
        ("203.0.113.1", {"RUNPLAN_WEB_REQUIRE_HTTPS": "false"}, None, True),
    ],
)
def test_transport_policy_distinguishes_loopback_proxy_and_insecure_http(
    peer, environment, forwarded_proto, allowed
) -> None:
    assert authenticator(**environment).transport_is_secure(peer, forwarded_proto) is allowed


def test_login_proof_matches_hmac_over_the_one_time_nonce() -> None:
    auth = authenticator()
    challenge = auth.issue_challenge("peer")
    proof = login_proof("shared secret", challenge)

    auth.verify_login("peer", {"challengeId": challenge["challengeId"], "proof": proof})
    assert hmac.compare_digest(proof, proof)
