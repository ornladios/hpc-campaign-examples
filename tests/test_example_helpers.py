"""Focused unit tests for transformations used by the example scripts."""

import subprocess
from pathlib import Path

import numpy as np

from scripts.adios_derived_variables import computeDerivedFields, resolveVarName
from scripts.adios_stats import computeStats
from scripts.mhd_provenance import github_script_location
from scripts.render_adios_visualizations_to_campaign import resolve_var_name, visualization_semantic_kwargs


def test_prefixed_adios_variable_name_resolves_to_scientific_name() -> None:
    """Code-specific prefixes must not hide the underlying variable meaning."""
    assert resolveVarName({"hll_pressure", "rho"}, "pressure") == "hll_pressure"
    assert resolveVarName({"hll_pressure", "pressure"}, "pressure") == "pressure"
    assert resolve_var_name({"hll_pressure", "rho"}, "pressure") == "hll_pressure"


def test_divergence_uses_both_magnetic_field_components() -> None:
    """The derived div_b field is computed from bx and by together."""
    y, x = np.mgrid[0:3, 0:4]
    derived = computeDerivedFields({"bx": x.astype(float), "by": y.astype(float)})

    np.testing.assert_allclose(derived["div_b"], 2.0)


def test_statistics_are_computed_over_the_complete_array() -> None:
    """Statistics written to the campaign summarize every array element."""
    stats = computeStats(np.asarray([[1.0, 2.0], [3.0, 4.0]]))

    assert stats["min"] == 1.0
    assert stats["max"] == 4.0
    assert stats["mean"] == 2.5
    assert stats["median"] == 2.5


def test_streamline_metadata_records_physical_components_and_background() -> None:
    """Visualization metadata should name every prefixed field used to render."""
    semantic = visualization_semantic_kwargs(
        "velocity_streamlines",
        "streamlines",
        {"run_vx", "run_vy", "run_speed"},
    )

    assert semantic == {
        "streamline_by": ("run_vx", "run_vy"),
        "color_by": "run_speed",
    }


def test_github_script_location_uses_an_immutable_commit_url(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    script = repository / "workflow.py"
    script.write_text("print('workflow')\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    subprocess.run(["git", "-C", str(repository), "add", "workflow.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Provenance Test",
            "-c",
            "user.email=provenance@example.com",
            "commit",
            "-q",
            "-m",
            "Add workflow",
        ],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "remote", "add", "origin", "git@github.com:example/workflows.git"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repository), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    location = github_script_location(script)

    assert location == f"https://github.com/example/workflows/blob/{commit}/workflow.py"

    script.write_text("print('modified workflow')\n", encoding="utf-8")
    assert github_script_location(script) is None


def test_github_script_location_rejects_an_untracked_file(tmp_path: Path) -> None:
    script = tmp_path / "workflow.py"
    script.write_text("print('local workflow')\n", encoding="utf-8")

    assert github_script_location(script) is None
