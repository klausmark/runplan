from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = PROJECT_ROOT / "Dockerfile"


def test_dependencies_are_installed_before_application_source() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    dependency_install = "uv sync --locked --no-dev --no-install-project --no-editable"
    source_copy = "COPY src ./src"
    project_install = "uv sync --locked --no-dev --no-editable"

    assert dockerfile.index(dependency_install) < dockerfile.index(source_copy)
    assert dockerfile.index(source_copy) < dockerfile.rindex(project_install)


def test_runtime_image_does_not_include_uv() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    runtime_stage = dockerfile.split("FROM python:3.13-slim AS runtime", maxsplit=1)[1]

    assert "ghcr.io/astral-sh/uv" not in runtime_stage
    assert "COPY --from=builder /opt/runplan /opt/runplan" in runtime_stage
