from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest.mock import patch

import pytest

from runplan.cli import main, parse_arguments
from runplan.web_auth import parse_password_hash


def test_hash_password_command_generates_copyable_verifier() -> None:
    stdout = StringIO()
    with (
        patch("runplan.cli.getpass.getpass", side_effect=["secret", "secret"]),
        redirect_stdout(stdout),
    ):
        result = main(["hash-password"])

    assert result == 0
    parse_password_hash(stdout.getvalue().strip())
    assert parse_arguments(["hash-password"]).command == "hash-password"


@pytest.mark.parametrize(
    ("passwords", "message"),
    [(["", ""], "must not be empty"), (["one", "two"], "do not match")],
)
def test_hash_password_command_rejects_empty_or_mismatched_input(passwords, message) -> None:
    stderr = StringIO()
    with patch("runplan.cli.getpass.getpass", side_effect=passwords), redirect_stderr(stderr):
        result = main(["hash-password"])

    assert result == 2
    assert message in stderr.getvalue()
