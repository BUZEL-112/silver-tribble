#!/usr/bin/env python3
"""Build and validation script for Newsroom AI package distribution."""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = ROOT_DIR / "dist"


def run_command(cmd: list[str], cwd: Path = ROOT_DIR) -> None:
    """Execute shell command with stream output and error handling."""
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        print(f"Command failed with exit code {result.returncode}: {' '.join(cmd)}")
        sys.exit(result.returncode)


def clean_dist() -> None:
    """Remove previous build artifacts and egg-info directories."""
    print("Cleaning distribution directories...")
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    for p in ROOT_DIR.glob("*.egg-info"):
        if p.is_dir():
            shutil.rmtree(p)
    for p in (ROOT_DIR / "src").glob("*.egg-info"):
        if p.is_dir():
            shutil.rmtree(p)


def build_package() -> None:
    """Build sdist and wheel distributions."""
    print("Building package artifacts...")
    # Synchronize bundled prompts
    src_prompts = ROOT_DIR / "src" / "prompts"
    src_prompts.mkdir(parents=True, exist_ok=True)
    for yaml_file in (ROOT_DIR / "prompts").glob("*.yaml"):
        shutil.copy2(yaml_file, src_prompts / yaml_file.name)

    # Ensure typing markers
    (ROOT_DIR / "src" / "py.typed").touch(exist_ok=True)

    uv_path = shutil.which("uv")
    if uv_path:
        run_command([uv_path, "build"])
    else:
        run_command([sys.executable, "-m", "build"])


def verify_package() -> None:
    """Validate built distributions with twine check."""
    print("Validating distribution metadata with twine...")
    wheel_files = list(DIST_DIR.glob("*.whl"))
    tar_files = list(DIST_DIR.glob("*.tar.gz"))

    if not wheel_files or not tar_files:
        print("Error: No wheel or sdist found in dist directory.")
        sys.exit(1)

    uv_path = shutil.which("uv")
    target_files = [str(p) for p in list(DIST_DIR.glob("*.whl")) + list(DIST_DIR.glob("*.tar.gz"))]
    if uv_path:
        run_command([uv_path, "run", "--with", "twine", "twine", "check"] + target_files)
    else:
        run_command([sys.executable, "-m", "twine", "check"] + target_files)


def test_installation() -> None:
    """Install built wheel in a temporary virtualenv and verify CLI entrypoints."""
    wheel_files = list(DIST_DIR.glob("*.whl"))
    if not wheel_files:
        print("Error: No wheel available for test installation.")
        sys.exit(1)

    wheel_path = wheel_files[0]
    print(f"Verifying isolated installation for: {wheel_path.name}")

    with tempfile.TemporaryDirectory() as temp_dir:
        venv_path = Path(temp_dir) / "test_venv"
        run_command([sys.executable, "-m", "venv", str(venv_path)])

        venv_python = venv_path / "bin" / "python"
        venv_cli = venv_path / "bin" / "newsroom-ai"

        run_command([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"])
        run_command([str(venv_python), "-m", "pip", "install", str(wheel_path)])

        # Test CLI help
        run_command([str(venv_cli), "--help"], cwd=Path(temp_dir))
        # Test CLI banner
        run_command([str(venv_cli), "banner"], cwd=Path(temp_dir))
        # Test Python import
        import_cmd = "import src; print('Imported src version:', src.__version__)"
        run_command(
            [str(venv_python), "-c", import_cmd],
            cwd=Path(temp_dir),
        )

    print("Isolated package installation test passed successfully.")


def main() -> None:
    """Main execution entrypoint."""
    parser = argparse.ArgumentParser(description="Build and verify Newsroom AI distribution.")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean dist and egg-info directories first",
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Only verify existing dist files",
    )
    parser.add_argument(
        "--test-install",
        action="store_true",
        help="Test installing wheel into temporary virtualenv",
    )
    args = parser.parse_args()

    if args.clean or not args.verify_only:
        clean_dist()

    if not args.verify_only:
        build_package()

    verify_package()

    if args.test_install:
        test_installation()

    print("\nPackage build and verification completed.")
    print("Distributions:")
    for item in DIST_DIR.glob("*"):
        print(f"  - {item.name} ({item.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
