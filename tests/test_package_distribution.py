"""Unit tests verifying package distribution, entrypoints, and assets."""

import tomllib
from pathlib import Path

import typer
from typer.testing import CliRunner

import src
from src.cli import app as src_cli_app
from src.services.script_service import ScriptService

runner = CliRunner()


def test_package_metadata_and_version() -> None:
    """Verify package exposes valid version and metadata."""
    assert hasattr(src, "__version__")
    assert isinstance(src.__version__, str)
    assert src.__version__ == "0.1.0"


def test_package_cli_app_instance() -> None:
    """Verify CLI exports a valid Typer application."""
    assert isinstance(src_cli_app, typer.Typer)


def test_package_cli_banner_invocation() -> None:
    """Verify invoking CLI banner succeeds."""
    result = runner.invoke(src_cli_app, ["banner"])
    assert result.exit_code == 0
    assert "NEWSROOM AI STUDIO" in result.stdout


def test_pyproject_scripts_entrypoints() -> None:
    """Verify pyproject.toml scripts point to valid import paths."""
    pyproject_path = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with open(pyproject_path, "rb") as f:
        data = tomllib.load(f)

    scripts = data.get("project", {}).get("scripts", {})
    assert "newsroom-ai" in scripts
    assert "newsroom_ai" in scripts
    assert "newsroom" in scripts
    assert "pipeline" in scripts
    assert "ai-video" in scripts

    for name, target in scripts.items():
        module_path, obj_name = target.split(":")
        assert module_path == "src.cli"
        assert obj_name == "app"


def test_bundled_prompts_discovery(tmp_path: Path) -> None:
    """Verify script service finds bundled YAML prompt definitions even in empty directory."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()

    # Pass empty custom directory so it falls back to bundled package prompts
    script_service = ScriptService(
        article_repo=None,  # type: ignore[arg-type]
        script_repo=None,  # type: ignore[arg-type]
        cost_repo=None,  # type: ignore[arg-type]
        prompts_dir=empty_dir,
    )

    configs = script_service.list_beat_generator_configs()
    assert "beat_sheet.yaml" in configs
    assert "eswar_host_persona.yaml" in configs

    beat_cfg = script_service.get_beat_generator_config("beat_sheet.yaml")
    assert "system_prompt" in beat_cfg["parsed"]
