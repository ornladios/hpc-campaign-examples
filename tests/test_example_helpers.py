"""Focused unit tests for transformations used by the example scripts."""

from pathlib import Path

import numpy as np
import pytest

from scripts.adios_derived_variables import computeDerivedFields, resolveVarName
from scripts.adios_stats import computeStats
from scripts.render_adios_visualizations_to_campaign import (
    encode_mp4,
    movie_file_path,
    resolve_var_name,
    visualization_semantic_kwargs,
    visualization_variable_specs,
)


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


def test_video_variable_specs_use_semantic_names_and_roles() -> None:
    source_dataset = "run-001/output.bp"
    specs = visualization_variable_specs(
        {
            "color_by": "sim_pressure",
            "contour_by": "sim_pressure",
        },
        source_dataset,
    )

    assert specs == [
        {"name": "sim_pressure", "role": "color-by", "source_dataset": source_dataset},
        {"name": "sim_pressure", "role": "contour-by", "source_dataset": source_dataset},
    ]


def test_video_variable_specs_map_streamline_components() -> None:
    source_dataset = "run-001/output.bp"
    specs = visualization_variable_specs(
        {
            "streamline_by": ("sim_bx", "sim_by"),
            "color_by": "sim_pressure",
        },
        source_dataset,
    )

    assert [(spec["name"], spec["role"]) for spec in specs] == [
        ("sim_pressure", "color-by"),
        ("sim_bx", "streamline-x"),
        ("sim_by", "streamline-y"),
    ]
    assert all(spec["source_dataset"] == source_dataset for spec in specs)


def test_movie_output_path_is_persistent_and_mirrors_sequence_name(tmp_path: Path) -> None:
    output_path = movie_file_path(tmp_path, "run-001/output.bp/visualizations/pressure_movie")

    assert output_path == tmp_path / "run-001/output.bp/visualizations/pressure_movie.mp4"


def test_encode_mp4_preserves_rendered_frame_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Frames reach FFmpeg in list order, independent of simulation step labels."""
    import scripts.render_adios_visualizations_to_campaign as renderer

    monkeypatch.setattr(renderer.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    observed: dict[str, object] = {}

    def fake_run(command: list[str], check: bool) -> None:
        frame_pattern = Path(command[command.index("-i") + 1])
        frame_paths = sorted(frame_pattern.parent.glob("frame.*.png"))
        observed["frames"] = [path.read_bytes() for path in frame_paths]
        observed["fps"] = command[command.index("-framerate") + 1]
        observed["check"] = check
        Path(command[-1]).write_bytes(b"mp4")

    monkeypatch.setattr(renderer.subprocess, "run", fake_run)
    output = encode_mp4([b"first", b"second", b"third"], tmp_path / "movie.mp4", 12.5)

    assert observed == {"frames": [b"first", b"second", b"third"], "fps": "12.5", "check": True}
    assert output.read_bytes() == b"mp4"


def test_encode_mp4_rejects_nonpositive_frame_rate(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="positive"):
        encode_mp4([b"frame"], tmp_path / "movie.mp4", 0)
