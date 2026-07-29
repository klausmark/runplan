from pathlib import Path

import pytest

from runplan.web import RunplanUser, UserRegistry, WebError, load_user_registry


def test_missing_registry_can_create_and_reload_first_user(tmp_path: Path) -> None:
    config = tmp_path / "users.toml"
    registry = load_user_registry(config)
    assert registry.list() == []

    created = registry.create("sample-runner", "Sample Runner")
    second = registry.create("runner-two", "Runner Two")
    reloaded = load_user_registry(config)

    assert created == {
        "id": "sample-runner",
        "name": "Sample Runner",
        "activeProgram": None,
    }
    assert reloaded.list() == [created, second]
    user = reloaded.get("sample-runner")
    assert user.credentials_file == tmp_path / "users/sample-runner/credentials.toml"
    assert not user.credentials_file.exists()


def test_create_validates_names_and_rejects_duplicates(tmp_path: Path) -> None:
    registry = load_user_registry(tmp_path / "users.toml")
    with pytest.raises(WebError):
        registry.create("Invalid User", "Valid Name")
    with pytest.raises(WebError):
        registry.create("valid", "")
    registry.create("valid", "Valid Name")

    with pytest.raises(WebError) as error:
        registry.create("valid", "Another Name")

    assert error.value.status == 409


def test_settings_store_credentials_without_returning_password(tmp_path: Path) -> None:
    config = tmp_path / "users.toml"
    registry = load_user_registry(config)
    registry.create("runner", "Runner One")

    result = registry.update_settings(
        "runner",
        {
            "fullName": "Runner Updated",
            "defaultPace": "5:45 min/km",
            "garminEmail": "runner@example.com",
            "garminPassword": "secret-value",
        },
    )
    preserved = registry.update_settings(
        "runner",
        {
            "fullName": "Runner Updated",
            "defaultPace": "5:30 min/km",
            "garminEmail": "new@example.com",
            "garminPassword": "",
        },
    )

    assert "garminPassword" not in result["settings"]
    assert result["settings"]["hasGarminPassword"]
    assert preserved["settings"]["defaultPace"] == "5:30 min/km"
    reloaded = load_user_registry(config)
    assert reloaded.get("runner").default_pace == "5:30 min/km"
    credentials = reloaded.get("runner").credentials_file.read_text(encoding="utf-8")
    assert 'email = "new@example.com"' in credentials
    assert 'password = "secret-value"' in credentials


def test_settings_require_valid_pace_and_initial_password(tmp_path: Path) -> None:
    registry = load_user_registry(tmp_path / "users.toml")
    registry.create("runner", "Runner")
    base = {
        "fullName": "Runner",
        "garminEmail": "runner@example.com",
        "garminPassword": "",
    }
    with pytest.raises(WebError):
        registry.update_settings("runner", {**base, "defaultPace": "fast"})

    with pytest.raises(WebError, match="(?i)password"):
        registry.update_settings("runner", {**base, "defaultPace": "6:00 min/km"})


def test_loads_relative_profile_paths_without_exposing_them(tmp_path: Path) -> None:
    config = tmp_path / "users.toml"
    config.write_text(
        '\n[[users]]\nid = "sample-runner"\nname = "Sample Runner"\n'
        'credentials_file = "secrets/sample-runner.toml"\n'
        'token_store = "tokens/sample-runner"\nstate_dir = "state/sample-runner"',
        encoding="utf-8",
    )

    registry = load_user_registry(config)
    user = registry.get("sample-runner")

    assert registry.list() == [
        {"id": "sample-runner", "name": "Sample Runner", "activeProgram": None}
    ]
    assert user.credentials_file == tmp_path / "secrets/sample-runner.toml"
    assert user.token_store == tmp_path / "tokens/sample-runner"
    assert user.state_directory == tmp_path / "state/sample-runner"


def test_rejects_unknown_user() -> None:
    registry = UserRegistry(
        [RunplanUser("known", "Known", Path("credentials"), Path("tokens"), Path("state"))]
    )

    with pytest.raises(WebError) as error:
        registry.get("unknown")

    assert error.value.status == 400


def test_active_program_round_trips_without_exposing_profile_paths(tmp_path: Path) -> None:
    config = tmp_path / "users.toml"
    registry = load_user_registry(config)
    registry.create("runner", "Runner")

    updated = registry.set_active_program("runner", "marathon.yaml")
    reloaded = load_user_registry(config)

    assert updated.active_program == "marathon.yaml"
    assert reloaded.get("runner").active_program == "marathon.yaml"
    assert reloaded.list()[0]["activeProgram"] == "marathon.yaml"
