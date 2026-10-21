"""Integration tests for the schema embedded by the MHD ingest script."""

import subprocess
import sys
from pathlib import Path

import h5py
import pytest
from hpc_campaign import Manager
from hpc_campaign.schema import SchemaInterpretationError

from scripts.verify_campaign import verify_campaign

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "mhd_orszag_tang.yaml"


def _make_placeholder_dataset(path: Path) -> None:
    """Create a real payload while keeping schema validation metadata-only."""
    with h5py.File(path, "w") as handle:
        handle.create_dataset("pressure", data=[1.0])


def test_schema_applies_to_two_runs_and_allows_derived_products(tmp_path: Path) -> None:
    """Each run must contain output.bp; other registered products are allowed."""
    payload = tmp_path / "payload.h5"
    _make_placeholder_dataset(payload)

    manager = Manager(archive="mhd.aca", campaign_store=str(tmp_path))
    manager.open(create=True, truncate=True)
    try:
        manager.set_schema(SCHEMA_PATH)
        for name in (
            "run-001/output.bp",
            "run-001/analysis.bp",
            "run-001/output_stats.bp",
            "run-002/output.bp",
        ):
            manager.data(payload, name=name)

        layout = manager.validate_schema()
    finally:
        manager.close()

    assert sorted(layout["instances"]) == ["run-001", "run-002"]
    assert layout["instances"]["run-001"]["file_groups"]["output"]["datasets"] == [
        "run-001/output.bp"
    ]
    assert layout["instances"]["run-002"]["file_groups"]["output"]["datasets"] == [
        "run-002/output.bp"
    ]


@pytest.mark.parametrize("with_provenance", [False, True])
def test_verify_campaign_requires_stored_provenance(tmp_path: Path, with_provenance: bool) -> None:
    payload = tmp_path / "payload.h5"
    _make_placeholder_dataset(payload)
    archive = tmp_path / "mhd.aca"
    manager = Manager(archive=str(archive))
    manager.open(create=True)
    try:
        manager.set_schema(SCHEMA_PATH)
        manager.data(payload, name="run-001/output.bp")
        if with_provenance:
            pressure = manager.add_variable(dataset="run-001/output.bp", variable="pressure", definition="pressure")
            manager.add_activity("simulation", outputs={"pressure": pressure})
    finally:
        manager.close()

    if not with_provenance:
        with pytest.raises(ValueError, match="Expected one active provenance document, found 0"):
            verify_campaign(archive)
        return

    before = archive.read_bytes()
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "verify_campaign.py"), "--archive", str(archive)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "schema validated for 1 run(s)" in result.stdout
    assert "active provenance loaded and hash verified" in result.stdout
    assert archive.read_bytes() == before


def test_verify_campaign_rejects_an_invalid_final_layout(tmp_path: Path) -> None:
    payload = tmp_path / "payload.h5"
    _make_placeholder_dataset(payload)
    archive = tmp_path / "mhd.aca"
    manager = Manager(archive=str(archive))
    manager.open(create=True)
    try:
        manager.set_schema(SCHEMA_PATH)
        manager.data(payload, name="run-001/analysis.bp")
    finally:
        manager.close()

    with pytest.raises(SchemaInterpretationError, match="output.bp"):
        verify_campaign(archive)
