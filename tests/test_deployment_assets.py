import stat
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = PROJECT_ROOT / "deploy" / "runplan-deploy"


def test_deployment_builds_before_health_gated_cutover() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    build = 'RUNPLAN_IMAGE="$candidate_image" docker compose build runplan'
    cutover = (
        'docker image tag "$candidate_image" runplan:local\n'
        "cutover_started=true\n"
        "compose_up\n"
        "check_external_health"
    )

    assert script.index(build) < script.index(cutover)
    assert "compose_local up -d --no-build --force-recreate --wait --wait-timeout 90" in script


def test_deployment_retains_and_restores_the_previous_image() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert 'docker image tag "$old_image" runplan:rollback' in script
    assert 'docker image tag "$old_image" runplan:local' in script
    assert 'git reset --hard "$old_commit"' in script
    assert "write_state failed-commit" in script
    assert "Skipping previously failed commit" in script


def test_deployment_script_is_executable() -> None:
    assert DEPLOY_SCRIPT.stat().st_mode & stat.S_IXUSR


def test_systemd_timer_runs_periodically_and_persists() -> None:
    timer = (PROJECT_ROOT / "deploy" / "runplan-deploy.timer").read_text(encoding="utf-8")
    service = (PROJECT_ROOT / "deploy" / "runplan-deploy.service").read_text(encoding="utf-8")

    assert "OnUnitActiveSec=5min" in timer
    assert "Persistent=true" in timer
    assert "StateDirectory=runplan-deploy" in service
    assert "TimeoutStartSec=30min" in service


def test_runtime_data_is_excluded_from_the_docker_build_context() -> None:
    dockerignore = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert "/runplan-data" in dockerignore.splitlines()


def test_deployment_does_not_require_external_generation_configuration() -> None:
    compose = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    environment_example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert "MINIMAX" not in compose
    assert "MINIMAX" not in environment_example
