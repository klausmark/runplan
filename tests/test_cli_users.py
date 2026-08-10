from argparse import Namespace
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml

from runplan.cli import _sync_one_user, main, parse_arguments, run_user_sync
from runplan.users import RunplanUser, UserRegistry, load_user_registry
from tests.helpers import program_data


def test_user_sync_parser_requires_one_user_target() -> None:
    one = parse_arguments(["sync", "klaus"])
    all_users = parse_arguments(["sync", "--all"])

    assert one.user_id == "klaus"
    assert not one.all_users
    assert all_users.all_users


def test_user_set_plan_validates_and_persists_user_program(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "users.toml"
    programs = tmp_path / "programs"
    registry = load_user_registry(config)
    registry.create("klaus", "Klaus")
    user_programs = programs / "klaus"
    user_programs.mkdir(parents=True)
    (user_programs / "plan.yaml").write_text(yaml.safe_dump(program_data()), encoding="utf-8")
    monkeypatch.setenv("RUNPLAN_USERS_FILE", str(config))
    monkeypatch.setenv("RUNPLAN_PROGRAM_DIR", str(programs))

    result = main(["user", "set-plan", "klaus", "plan.yaml"])

    assert result == 0
    assert load_user_registry(config).get("klaus").active_program == "plan.yaml"


def test_all_users_skips_missing_plan_and_continues_after_failure() -> None:
    users = UserRegistry(
        [
            RunplanUser("skip", "Skip", Path("c"), Path("t"), Path("s")),
            RunplanUser("ok", "OK", Path("c"), Path("t"), Path("s"), active_program="a.yaml"),
            RunplanUser("bad", "Bad", Path("c"), Path("t"), Path("s"), active_program="b.yaml"),
        ]
    )

    with (
        patch("runplan.users.load_user_registry", return_value=users),
        patch("runplan.cli._sync_one_user", side_effect=[0, 12]) as sync_one,
        redirect_stdout(StringIO()),
    ):
        result = run_user_sync(Namespace(all_users=True))

    assert result == 1
    assert [call.args[1].id for call in sync_one.call_args_list] == ["ok", "bad"]


def test_single_user_sync_injects_the_isolated_profile(tmp_path: Path) -> None:
    program = tmp_path / "klaus" / "plan.yaml"
    program.parent.mkdir()
    program.write_text("program: {}\n", encoding="utf-8")
    user = RunplanUser(
        "klaus",
        "Klaus",
        tmp_path / "credentials.toml",
        tmp_path / "tokens",
        tmp_path / "state",
        five_k_best="27:55",
        active_program="plan.yaml",
    )

    with (
        patch("runplan.cli.default_program_directory", return_value=tmp_path),
        patch("runplan.cli.run_sync", return_value=0) as sync,
    ):
        result = _sync_one_user(Namespace(), user)

    assert result == 0
    delegated = sync.call_args.args[0]
    assert delegated.yaml_file == program
    assert not hasattr(delegated, "owner_id")
    assert delegated.fallback_pace_value == "27:55"
    assert delegated.credentials_file == user.credentials_file
    assert delegated.token_store == user.token_store
    assert delegated.repository.state_directory == user.state_directory.resolve()


def test_serve_programs_default_to_external_user_data_directory(monkeypatch) -> None:
    monkeypatch.delenv("RUNPLAN_PROGRAM_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", "/srv/runplan-data")
    assert parse_arguments(["serve"]).program_dir == Path("/srv/runplan-data/runplan/programs")

    monkeypatch.setenv("RUNPLAN_PROGRAM_DIR", "/srv/plans")
    assert parse_arguments(["serve"]).program_dir == Path("/srv/plans")
