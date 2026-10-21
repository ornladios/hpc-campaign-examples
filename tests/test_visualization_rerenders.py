"""Exercise repeated rendering through the documented command-line scripts."""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from adios2.stream import Stream
from hpc_campaign import Manager
from prov.model import ProvGeneration

from scripts.mhd_provenance import record_campaign_provenance

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "schemas" / "mhd_orszag_tang.yaml"


def _campaign_with_source(root: Path) -> Path:
    source = root / "run-001" / "output.bp"
    source.parent.mkdir()
    field = np.arange(12, dtype=np.float64).reshape(3, 4)
    with Stream(str(source), "w") as stream:
        for time in (0.0, 0.25):
            stream.begin_step()
            stream.write("sim_pressure", field + time, field.shape, [0, 0], field.shape)
            stream.write("time", np.asarray([time]), [1], [0], [1])
            stream.end_step()
    archive = root / "mhd.aca"
    manager = Manager(archive=str(archive))
    manager.open(create=True)
    try:
        manager.set_schema(SCHEMA_PATH)
        manager.data(source, name="run-001/output.bp")
        record_campaign_provenance(manager, [source], root)
    finally:
        manager.close()
    return archive


def _render_state(archive: Path, sequence_name: str, scalar: bool) -> dict:
    manager = Manager(archive=str(archive))
    manager.open(create=False)
    try:
        assert set(manager.validate_schema()["instances"]) == {"run-001"}
        info = manager.info(list_replicas=False, list_files=False)
        sequence = next(item for item in info.visualization_sequences.values() if item.name == sequence_name)
        members = {item.item_uuid for item in sequence.items}
        outputs = (
            {manager.dataset_entity(item.dataset_name) for item in sequence.items}
            if scalar
            else {manager.visualization_sequence_entity(sequence_name)}
        )
        document = manager.prov_document("campaign-provenance")
        generations = {relation.args[:2] for relation in document.get_records(ProvGeneration)}
        assert all(len([pair for pair in generations if pair[0] == output]) == 1 for output in outputs)
        payloads = {
            (str(row[0]), int(row[1])): hashlib.sha256(bytes(row[2])).hexdigest()
            for row in manager.con.execute(
                "SELECT d.uuid, f.fileid, f.data FROM dataset d "
                "JOIN replica r ON r.datasetid = d.rowid "
                "JOIN repfiles rf ON rf.replicaid = r.rowid "
                "JOIN file f ON f.fileid = rf.fileid "
                "WHERE d.fileformat IN ('IMAGE', 'VIDEO', 'SCALAR_FIELD')"
            )
        }
        return {
            "members": members,
            "outputs": outputs,
            "generations": generations,
            "payloads": payloads,
            "document_hash": manager.prov_documents(active=True)[0].sha256,
            "dataset_count": len(info.datasets),
        }
    finally:
        manager.close()


@pytest.mark.parametrize("kind", ["image", "external_image", "movie", "scalar"])
def test_rerenders_preserve_previous_products_and_producers(tmp_path: Path, kind: str) -> None:
    if kind == "movie" and shutil.which("ffmpeg") is None:
        pytest.skip("movie rendering requires FFmpeg")
    archive = _campaign_with_source(tmp_path)
    scalar = kind == "scalar"
    script = "add_scalar_fields_to_campaign.py" if scalar else "render_adios_visualizations_to_campaign.py"
    sequence_name = "run-001/output.bp/visualizations/pressure_view"
    command = [
        sys.executable,
        str(REPO_ROOT / "scripts" / script),
        "--archive",
        str(archive),
        "--dataset",
        "run-001/output.bp",
        "--variable",
        "pressure",
        "--name",
        "pressure_view",
        "--data_root",
        str(tmp_path),
        "--allSteps",
    ]
    if kind == "movie":
        sequence_name += "_movie"
        command.extend(["--movie", "--movieOutputDir", str(tmp_path / "movies")])
    elif kind == "external_image":
        command.extend(["--externalImages", "--imageOutputDir", str(tmp_path / "images")])

    previous = None
    previous_files = {}
    for rendering in range(3):
        # The first rerender is identical; the next changes the stored pixels
        # or scalar encoding. Both must create distinct products.
        settings = ["--dtype", "float64" if rendering == 2 else "float32"] if scalar else []
        if not scalar and rendering == 2:
            settings = ["--cmap", "plasma"]
        result = subprocess.run([*command, "--replace", *settings], capture_output=True, text=True)
        assert result.returncode == 0, "\n".join((result.stdout + result.stderr).splitlines()[-25:])
        current = _render_state(archive, sequence_name, scalar)
        if previous is not None:
            assert current["members"].isdisjoint(previous["members"])
            assert current["outputs"].isdisjoint(previous["outputs"])
            assert previous["generations"] <= current["generations"]
            assert all(current["payloads"][key] == value for key, value in previous["payloads"].items())
            assert all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in previous_files.items())
        previous = current
        previous_files = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for folder in (tmp_path / "movies", tmp_path / "images")
            for path in folder.rglob("*")
            if path.is_file()
        }

    # An existing sequence without --replace must fail before adding datasets
    # or altering provenance or earlier media.
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0
    assert "Visualization sequence already exists" in result.stderr
    assert _render_state(archive, sequence_name, scalar) == previous
    assert all(hashlib.sha256(path.read_bytes()).hexdigest() == value for path, value in previous_files.items())
