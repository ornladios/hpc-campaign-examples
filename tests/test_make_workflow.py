"""Regression checks for the commands emitted by the Make workflow."""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("absolute", [False, True])
def test_runs_target_resolves_relative_and_absolute_build_directories(tmp_path: Path, absolute: bool) -> None:
    build_dir = tmp_path / "build" if absolute else Path("build")
    result = subprocess.run(
        ["make", "-n", "runs", f"BUILD_DIR={build_dir}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert f"--binary {(REPO_ROOT / build_dir / 'ot_mhd').resolve()} " in result.stdout


def test_verify_target_validates_the_completed_archive() -> None:
    result = subprocess.run(
        ["make", "-n", "verify", "ARCHIVE=example.aca"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "scripts/verify_campaign.py --archive example.aca" in result.stdout
    assert result.stdout.index("scripts/verify_campaign.py") < result.stdout.index("sqlite3")
