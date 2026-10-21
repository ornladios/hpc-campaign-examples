#!/usr/bin/env python3
"""Create a tiny two-file HPC Campaign with visualizations and PROV records.

This example is intentionally smaller than the MHD workflow. It creates two
ADIOS/BP datasets:

* ``file1.bp`` contains one variable named ``var``.
* ``file2.bp`` contains one variable named ``var``.

The script then renders each ``var`` as a PNG heatmap, registers both PNGs as
campaign visualizations, and records the scientific provenance:

* ``sim1`` generated ``file1.bp:var``;
* ``sim2`` generated ``file2.bp:var``;
* one Visualization Activity used ``file1.bp:var`` to generate its heatmap;
* one Visualization Activity used ``file2.bp:var`` to generate its heatmap;
* software Agents and Plans document the responsible code paths.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCHEMA_PATH = REPO_ROOT / "schemas" / "toy_campaign.yaml"
DEFAULT_OUTPUT_ROOT = Path("toy_campaign_output")
DEFAULT_ARCHIVE = "toy_campaign.aca"
DEFAULT_SEED = 20260909
DEFAULT_SHAPE = (16, 24)

PLAN_DATASET = "plans/toy_campaign.py"
FILE1_DATASET = "file1.bp"
FILE2_DATASET = "file2.bp"
VARIABLE_NAME = "var"
FILE1_VISUALIZATION_IMAGE_FILE = "file1_var_heatmap.png"
FILE2_VISUALIZATION_IMAGE_FILE = "file2_var_heatmap.png"
VISUALIZATION_NAME = "var_heatmap"
FILE1_VISUALIZATION_SEQUENCE = f"{FILE1_DATASET}/visualizations/{VISUALIZATION_NAME}"
FILE2_VISUALIZATION_SEQUENCE = f"{FILE2_DATASET}/visualizations/{VISUALIZATION_NAME}"
FILE1_VISUALIZATION_IMAGE_DATASET = f"{FILE1_VISUALIZATION_SEQUENCE}/image.000000.png"
FILE2_VISUALIZATION_IMAGE_DATASET = f"{FILE2_VISUALIZATION_SEQUENCE}/image.000000.png"


@dataclass(frozen=True)
class ToyCampaignResult:
    """Filesystem and campaign names created by ``build_toy_campaign``."""

    archive_path: Path
    output_root: Path
    file1_path: Path
    file2_path: Path
    file1_image_path: Path
    file2_image_path: Path
    prov_json_path: Path
    file1_visualization_sequence: str
    file2_visualization_sequence: str
    file1_visualization_image_dataset: str
    file2_visualization_image_dataset: str


def _import_hpc_campaign():
    """Import hpc-campaign lazily so CLI errors explain the missing package."""
    try:
        from hpc_campaign import Manager

        return Manager
    except ModuleNotFoundError as exc:
        if exc.name in {"hpc_campaign", "hpc_campaign.manager"}:
            message = "Could not import hpc-campaign. Install this example's Python dependencies first."
            raise SystemExit(message) from exc
        raise


def _import_adios_stream():
    """Import the ADIOS2 stream writer used for the two toy BP files."""
    try:
        from adios2.stream import Stream

        return Stream
    except ModuleNotFoundError as exc:
        if exc.name == "adios2":
            raise SystemExit("This example requires the Python package 'adios2'.") from exc
        raise


def _import_matplotlib_pyplot():
    """Import matplotlib with a headless backend suitable for scripts and tests."""
    try:
        cache_root = Path(tempfile.gettempdir()) / "hpc_campaign_toy_visualization_cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("MPLCONFIGDIR", str(cache_root / "matplotlib"))
        os.environ.setdefault("XDG_CACHE_HOME", str(cache_root / "xdg"))

        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ModuleNotFoundError as exc:
        if exc.name == "matplotlib":
            raise SystemExit("This example requires matplotlib to render the PNG heatmap.") from exc
        raise


def _package_version(package: str) -> str | None:
    """Return an installed package version when it is available."""
    try:
        return version(package)
    except PackageNotFoundError:
        return None


@contextmanager
def pushd(path: Path):
    """Temporarily register relative payload paths from the output root."""
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def _require_available_targets(paths: list[Path]) -> None:
    """Refuse to replace outputs from an earlier run."""
    existing = [path for path in paths if path.exists()]
    if existing:
        formatted = "\n".join(f"  {path}" for path in existing)
        raise FileExistsError(
            "refusing to replace existing toy campaign output(s):\n"
            f"{formatted}\n"
            "Choose a fresh --output-root or --archive name."
        )


def write_adios_field(path: Path, variable: str, values: np.ndarray) -> None:
    """Write one ADIOS/BP file containing exactly one array variable."""
    Stream = _import_adios_stream()
    data = np.asarray(values, dtype=np.float64)

    with Stream(str(path), "w") as stream:
        stream.begin_step()
        stream.write(variable, data, data.shape, [0, 0], data.shape)
        stream.end_step()


def render_heatmap(path: Path, values: np.ndarray, title: str) -> None:
    """Render one array as a PNG heatmap for visual registration."""
    plt = _import_matplotlib_pyplot()

    fig, ax = plt.subplots(figsize=(5.0, 3.5), constrained_layout=True)
    image = ax.imshow(values, origin="lower", cmap="viridis", aspect="auto")
    ax.set_title(title)
    ax.set_xticks([])
    ax.set_yticks([])
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    fig.savefig(path, format="png", dpi=150)
    plt.close(fig)


def _register_data_files(manager: Any) -> None:
    """Register the two BP payloads under their campaign dataset names."""
    # manager.data() records that a physical payload exists in the campaign.
    # This is not yet provenance; it creates the dataset identity that later
    # PROV logical variables can point to with their dataset= argument.
    manager.data(FILE1_DATASET, name=FILE1_DATASET)
    manager.data(FILE2_DATASET, name=FILE2_DATASET)


def _record_source_provenance(manager: Any, seed: int, shape: tuple[int, int]):
    """Record two root Simulation Activities and their logical variables."""
    # manager.add_agent() creates a PROV Agent. Here the Agent is the software
    # responsible for producing file1.bp and file2.bp.
    script_agent = manager.add_agent("software", "toy_campaign.py")

    # manager.add_plan() creates a PROV Plan. A Plan is the recipe or
    # configuration for an activity; this one records the seed and array shape
    # that make the random fields reproducible.
    run_plan = manager.add_plan(
        "toy random field generation",
        location=PLAN_DATASET,
        value=f"seed={seed}; shape={shape[0]}x{shape[1]}",
    )

    # add_variable() creates one LogicalVariable Entity backed by the existing
    # campaign dataset. It records the physical ADIOS name, stable scientific
    # definition, units, and coordinate system. Generation is recorded
    # explicitly below by add_activity().
    file1_var = manager.add_variable(
        dataset=FILE1_DATASET,
        variable=VARIABLE_NAME,
        definition="var",
        units="unitless",
        coordinate_system="array_index",
    )
    file2_var = manager.add_variable(
        dataset=FILE2_DATASET,
        variable=VARIABLE_NAME,
        definition="var",
        units="unitless",
        coordinate_system="array_index",
    )

    # Each simulation is a root Activity with no inputs. Its output is the
    # logical variable declared above; these calls record wasGeneratedBy.
    # Provenance added: file1.bp:var and file2.bp:var were generated by sim1
    # and sim2, respectively, each associated with toy_campaign.py and the
    # reproducibility Plan.
    manager.add_activity(
        "simulation",
        name="sim1",
        outputs={"var": file1_var},
        agent=script_agent,
        plan=run_plan,
    )
    manager.add_activity(
        "simulation",
        name="sim2",
        outputs={"var": file2_var},
        agent=script_agent,
        plan=run_plan,
    )

    return file1_var, file2_var


def _register_visualization(
    manager: Any,
    *,
    source_dataset: str,
    image_path: Path,
    seed: int,
    shape: tuple[int, int],
) -> None:
    """Register the PNG as a heatmap visualization sequence."""
    # manager.visualization() registers the image payload and visualization
    # metadata in the campaign: source dataset, variable role, steps, thumbnail,
    # and rendering metadata. The PROV derivation is added separately below by
    # manager.add_activity(), where we can explicitly say which logical
    # variable the image was derived from.
    manager.visualization(
        images=[image_path],
        kind="heatmap",
        source_dataset=source_dataset,
        name=VISUALIZATION_NAME,
        steps=[0],
        thumbnail_image=0,
        store=True,
        # This metadata is stored with the campaign visualization sequence.
        # Activity-level provenance is recorded separately below.
        metadata={
            "generated_by": Path(__file__).name,
            "seed": int(seed),
            "shape": [int(shape[0]), int(shape[1])],
            "colormap": "viridis",
        },
        color_by=VARIABLE_NAME,
    )


def _record_visualization_provenance(
    manager: Any,
    *,
    source_var_prov: Any,
    sequence_name: str,
    agent: Any,
    plan: Any,
) -> Any:
    """Record one heatmap sequence's lineage from its ``var`` input."""
    sequence = manager.add_visualization_sequence_entity(sequence_name)

    # add_activity() links an existing logical-variable input to an existing
    # collection Entity for the image sequence. It records the Visualization
    # Activity, its Usage and Generation, and the qualified derivation. The
    # sequence Entity contains the ordered image dataset members.
    result = manager.add_activity(
        "visualization",
        # "source" is the PROV role for this input: the heatmap uses this var.
        inputs={"source": source_var_prov},
        outputs={"image_sequence": sequence},
        # metadata records method details; inputs and outputs above define
        # provenance lineage.
        metadata={
            "visualization_type": "heatmap",
            "colormap": "viridis",
            "sequence_name": sequence_name,
        },
        # agent records the software responsible for this visualization step.
        agent=agent,
        # plan records the reusable recipe for this visualization step. Here it
        # points back to the stored toy_campaign.py script.
        plan=plan,
    )
    return result.outputs["image_sequence"]


def build_toy_campaign(
    output_root: Path,
    *,
    archive: str = DEFAULT_ARCHIVE,
    seed: int = DEFAULT_SEED,
    shape: tuple[int, int] = DEFAULT_SHAPE,
    schema_path: Path = DEFAULT_SCHEMA_PATH,
    export_prov: Path | None = None,
) -> ToyCampaignResult:
    """Create the toy campaign and return the paths and names it produced."""
    if len(shape) != 2 or shape[0] <= 0 or shape[1] <= 0:
        raise ValueError("shape must be a pair of positive integers")

    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    archive_path = output_root / archive
    file1_path = output_root / FILE1_DATASET
    file2_path = output_root / FILE2_DATASET
    file1_image_path = output_root / FILE1_VISUALIZATION_IMAGE_FILE
    file2_image_path = output_root / FILE2_VISUALIZATION_IMAGE_FILE
    prov_json_path = (
        export_prov.expanduser().resolve()
        if export_prov is not None
        else output_root / "toy_campaign.prov.json"
    )

    _require_available_targets(
        [archive_path, file1_path, file2_path, file1_image_path, file2_image_path, prov_json_path]
    )

    rng = np.random.default_rng(seed)
    file1_values = rng.random(shape)
    file2_values = rng.random(shape)

    write_adios_field(file1_path, VARIABLE_NAME, file1_values)
    write_adios_field(file2_path, VARIABLE_NAME, file2_values)
    render_heatmap(file1_image_path, file1_values, "toy_campaign: file1.bp:var")
    render_heatmap(file2_image_path, file2_values, "toy_campaign: file2.bp:var")

    Manager = _import_hpc_campaign()
    manager = Manager(archive=archive, campaign_store=str(output_root))

    # manager.open(create=True) creates the ACA file if needed and prepares the
    # Manager to register datasets and append provenance records.
    manager.open(create=True)
    try:
        with pushd(output_root):
            _register_data_files(manager)

            # The schema validates the intentionally tiny two-file payload layout.
            # manager.set_schema() stores the schema as a campaign TEXT dataset;
            # manager.validate_schema() checks the registered dataset names
            # against that schema without reading array contents.
            manager.set_schema(schema_path)
            manager.validate_schema()

            # Store this script in the campaign so Plans can point at the exact
            # recipe used to generate the toy data and visualization.
            # This makes the Plan locations above resolvable inside the ACA.
            manager.text(Path(__file__).resolve(), name=PLAN_DATASET, store=True)

            file1_var, file2_var = _record_source_provenance(manager, seed, shape)

            _register_visualization(
                manager,
                source_dataset=FILE1_DATASET,
                image_path=Path(FILE1_VISUALIZATION_IMAGE_FILE),
                seed=seed,
                shape=shape,
            )
            _register_visualization(
                manager,
                source_dataset=FILE2_DATASET,
                image_path=Path(FILE2_VISUALIZATION_IMAGE_FILE),
                seed=seed,
                shape=shape,
            )

            matplotlib_agent = manager.add_agent("software", "Matplotlib", version=_package_version("matplotlib"))
            render_plan = manager.add_plan("toy heatmap rendering", location=PLAN_DATASET)
            # Provenance added: file1_var_heatmap.png was generated from file1_var.
            file1_image = _record_visualization_provenance(
                manager,
                source_var_prov=file1_var,
                sequence_name=FILE1_VISUALIZATION_SEQUENCE,
                agent=matplotlib_agent,
                plan=render_plan,
            )
            # Provenance added: file2_var_heatmap.png was generated from file2_var.
            file2_image = _record_visualization_provenance(
                manager,
                source_var_prov=file2_var,
                sequence_name=FILE2_VISUALIZATION_SEQUENCE,
                agent=matplotlib_agent,
                plan=render_plan,
            )

        # manager.export_prov() writes a reviewable PROV-JSON copy of the
        # active provenance document. The canonical provenance stays in the
        # campaign archive.
        manager.export_prov("campaign-provenance", prov_json_path)
        print(f"Campaign archive: {archive_path}")
        print(f"ADIOS datasets: {file1_path}, {file2_path}")
        print(f"Visualization images: {file1_image_path}, {file2_image_path}")
        print(f"Visualization sequences: {FILE1_VISUALIZATION_SEQUENCE}, {FILE2_VISUALIZATION_SEQUENCE}")
        print(f"Final image sequence entities: {file1_image}, {file2_image}")
        print(f"PROV-JSON export: {prov_json_path}")
    finally:
        manager.close()

    return ToyCampaignResult(
        archive_path=archive_path,
        output_root=output_root,
        file1_path=file1_path,
        file2_path=file2_path,
        file1_image_path=file1_image_path,
        file2_image_path=file2_image_path,
        prov_json_path=prov_json_path,
        file1_visualization_sequence=FILE1_VISUALIZATION_SEQUENCE,
        file2_visualization_sequence=FILE2_VISUALIZATION_SEQUENCE,
        file1_visualization_image_dataset=FILE1_VISUALIZATION_IMAGE_DATASET,
        file2_visualization_image_dataset=FILE2_VISUALIZATION_IMAGE_DATASET,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="directory where the toy BP files, PNG, archive, and PROV-JSON are written",
    )
    parser.add_argument(
        "--archive",
        default=DEFAULT_ARCHIVE,
        help="campaign archive filename under --output-root",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed for reproducible toy data")
    parser.add_argument(
        "--shape",
        type=int,
        nargs=2,
        metavar=("HEIGHT", "WIDTH"),
        default=DEFAULT_SHAPE,
        help="2D shape of each random variable",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help="schema file to embed and validate",
    )
    parser.add_argument(
        "--exportProv",
        type=Path,
        default=None,
        help="optional PROV-JSON export path; default is <output-root>/toy_campaign.prov.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_toy_campaign(
        args.output_root,
        archive=args.archive,
        seed=args.seed,
        shape=tuple(args.shape),
        schema_path=args.schema,
        export_prov=args.exportProv,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
