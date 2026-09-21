"""W3C PROV mapping for the Orszag-Tang campaign example.

The ADIOS files remain the authoritative description of array shape, type, and
timesteps. This module records the scientific identity and lineage needed to
answer questions such as "which pressure field produced this image?".
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
from adios2.stream import Stream
from hpc_campaign import Manager, VariableSpec
from hpc_campaign.prov_mapping import HPC
from prov.model import ProvDocument, ProvEntity, QualifiedName

STAT_NAMES = ("min", "max", "mean", "median", "std", "var")

# These names are the stable scientific definitions used by this example.
# A physical ADIOS name may carry a run-specific prefix, for example hll_pressure.
SOURCE_DEFINITIONS = {
    "current_abs_max": "current_abs_max",
    "current_rms": "current_rms",
    "divb_abs_max": "divb_abs_max",
    "divb_l2": "divb_l2",
    "internal_energy": "internal_energy",
    "kinetic_energy": "kinetic_energy",
    "magnetic_energy": "magnetic_energy",
    "total_energy": "total_energy",
    "mean_pressure": "mean_pressure",
    "max_speed": "max_speed",
    "current_z": "current_density_z",
    "pressure": "pressure",
    "mass": "mass",
    "speed": "speed",
    "step": "step",
    "time": "time",
    "rho": "density",
    "vx": "velocity_x",
    "vy": "velocity_y",
    "vz": "velocity_z",
    "bx": "magnetic_field_x",
    "by": "magnetic_field_y",
    "bz": "magnetic_field_z",
    "psi": "glm_cleaning_field",
    "mx": "momentum_density_x",
    "my": "momentum_density_y",
    "mz": "momentum_density_z",
    "E": "total_energy_density",
}

FIELD_DEFINITIONS = {
    "density",
    "pressure",
    "velocity_x",
    "velocity_y",
    "velocity_z",
    "magnetic_field_x",
    "magnetic_field_y",
    "magnetic_field_z",
    "speed",
    "current_density_z",
    "glm_cleaning_field",
    "momentum_density_x",
    "momentum_density_y",
    "momentum_density_z",
    "total_energy_density",
}

UNITS_BY_DEFINITION = {
    "step": "index",
    "time": "normalized time",
    "density": "normalized density",
    "pressure": "normalized pressure",
    "mean_pressure": "normalized pressure",
    "velocity_x": "normalized velocity",
    "velocity_y": "normalized velocity",
    "velocity_z": "normalized velocity",
    "speed": "normalized velocity",
    "magnetic_field_x": "normalized magnetic field",
    "magnetic_field_y": "normalized magnetic field",
    "magnetic_field_z": "normalized magnetic field",
    "current_density_z": "normalized current density",
    "current_abs_max": "normalized current density",
    "current_rms": "normalized current density",
    "mass": "normalized mass",
    "kinetic_energy": "normalized energy",
    "magnetic_energy": "normalized energy",
    "internal_energy": "normalized energy",
    "total_energy": "normalized energy",
    "max_speed": "normalized velocity",
    "divb_abs_max": "normalized magnetic field per grid index",
    "divb_l2": "normalized magnetic field per grid index",
    "glm_cleaning_field": "normalized GLM field",
    "momentum_density_x": "normalized momentum density",
    "momentum_density_y": "normalized momentum density",
    "momentum_density_z": "normalized momentum density",
    "total_energy_density": "normalized energy density",
}

DERIVED_PRODUCTS = {
    "grad_rho_abs": {
        "definition": "density_gradient_magnitude",
        "inputs": {"density": "density"},
        "operation": "gradient_magnitude",
        "units": "normalized density per grid index",
    },
    "grad_pressure_abs": {
        "definition": "pressure_gradient_magnitude",
        "inputs": {"pressure": "pressure"},
        "operation": "gradient_magnitude",
        "units": "normalized pressure per grid index",
    },
    "div_b": {
        "definition": "magnetic_field_divergence",
        "inputs": {
            "magnetic_x": "magnetic_field_x",
            "magnetic_y": "magnetic_field_y",
        },
        "operation": "divergence",
        "units": "normalized magnetic field per grid index",
    },
}


@dataclass(frozen=True)
class LogicalProduct:
    """One logical variable plus metadata reused by later activities."""

    reference: QualifiedName
    definition: str
    units: str | None
    coordinate_system: str | None


@dataclass(frozen=True)
class WorkflowPlan:
    """One configured workflow Plan and its embedded implementation."""

    reference: QualifiedName
    script_dataset: str
    location: str


@dataclass
class ProvenanceIndex:
    """References created while ingesting one campaign."""

    runs: dict[str, QualifiedName] = field(default_factory=dict)
    by_physical: dict[tuple[str, str], LogicalProduct] = field(default_factory=dict)
    by_definition: dict[tuple[str, str], LogicalProduct] = field(default_factory=dict)

    def add(
        self,
        run_name: str,
        dataset_name: str,
        physical_name: str,
        product: LogicalProduct,
    ) -> None:
        self.by_physical[(dataset_name, physical_name)] = product
        self.by_definition[(run_name, product.definition)] = product


def _token(value: str) -> str:
    """Return a valid campaign vocabulary token."""
    token = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    if not token:
        return "variable"
    if not token[0].isalpha():
        token = f"variable_{token}"
    return token


def canonical_definition(physical_name: str) -> str:
    """Map an exact or prefixed ADIOS name to a shared scientific definition."""
    for suffix in sorted(SOURCE_DEFINITIONS, key=len, reverse=True):
        if physical_name == suffix or physical_name.endswith(f"_{suffix}"):
            return SOURCE_DEFINITIONS[suffix]
    return _token(physical_name)


def units_for_definition(definition: str) -> str:
    """Return the deliberately simple unit string used by the example."""
    return UNITS_BY_DEFINITION.get(definition, "normalized code units")


def coordinate_system_for_definition(definition: str) -> str | None:
    """Only spatial fields carry the run's Cartesian coordinate-system label."""
    return "Cartesian" if definition in FIELD_DEFINITIONS else None


def discover_adios_variables(dataset_path: Path) -> list[str]:
    """Read variable names from the first step of an ADIOS dataset."""
    with Stream(str(dataset_path), "r") as stream:
        for _step in stream.steps():
            return sorted((stream.available_variables() or {}).keys())
    raise ValueError(f"ADIOS dataset contains no steps: {dataset_path}")


def dataset_name(dataset_path: Path, out_root: Path) -> str:
    """Return the ACA dataset name used by the ingest script."""
    return dataset_path.relative_to(out_root).as_posix()


def run_name_from_dataset(dataset: str, out_root: Path) -> str:
    """Return the run scope that owns a run-relative dataset."""
    parent = Path(dataset).parent.as_posix()
    return out_root.name if parent == "." else parent


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _store_plan_source(manager: Manager, source: Path, logical_name: str) -> str:
    """Embed a small plan file and return its campaign-local location."""
    manager.text(source, name=logical_name, store=True)
    return logical_name


def _git_output(directory: Path, *arguments: str) -> str | None:
    """Run a read-only Git query in directory, returning stripped stdout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _github_repository_url(remote: str) -> str | None:
    """Normalize common GitHub remote spellings to an HTTPS repository URL."""
    value = remote.strip()
    match = re.fullmatch(r"https?://github\.com/(?P<path>[^\s]+?)(?:\.git)?/?", value)
    if match is None:
        match = re.fullmatch(r"git@github\.com:(?P<path>[^\s]+?)(?:\.git)?", value)
    if match is None:
        match = re.fullmatch(r"ssh://git@github\.com/(?P<path>[^\s]+?)(?:\.git)?/?", value)
    if match is None:
        return None
    return f"https://github.com/{match.group('path')}"


def github_script_location(source: Path) -> str | None:
    """Return an immutable GitHub URL when source matches a known origin commit."""
    resolved = source.expanduser().resolve()
    root_text = _git_output(resolved.parent, "rev-parse", "--show-toplevel")
    if root_text is None:
        return None
    root = Path(root_text).resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError:
        return None

    if _git_output(root, "ls-files", "--error-unmatch", "--", relative) is None:
        return None
    if _git_output(root, "diff", "--name-only", "HEAD", "--", relative) is not None:
        return None

    remote = _git_output(root, "remote", "get-url", "origin")
    commit = _git_output(root, "rev-parse", "HEAD")
    remote_refs = _git_output(
        root,
        "for-each-ref",
        "--contains",
        "HEAD",
        "--format=%(refname:short)",
        "refs/remotes/origin",
    )
    if remote is None or commit is None or remote_refs is None:
        return None
    repository = _github_repository_url(remote)
    if repository is None:
        return None
    return f"{repository}/blob/{commit}/{relative}"


def add_workflow_plan(
    manager: Manager,
    *,
    name: str,
    workflow: str,
    script_path: Path,
    details: dict[str, Any],
) -> WorkflowPlan:
    """Create one configured workflow Plan with a resolvable script reference."""
    resolved_script = script_path.expanduser().resolve()
    script_dataset = _store_plan_source(
        manager,
        resolved_script,
        f"plans/{resolved_script.name}",
    )
    location = github_script_location(resolved_script) or script_dataset
    payload = {
        "schema_version": 1,
        "workflow": workflow,
        "implementation_dataset": script_dataset,
        **details,
    }
    value = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    reference = manager.add_plan(name, location=location, value=value)
    return WorkflowPlan(reference, script_dataset, location)


def _store_json(manager: Manager, logical_name: str, payload: dict[str, Any]) -> None:
    """Embed JSON as a normal TEXT dataset without leaving a temporary file."""
    with tempfile.TemporaryDirectory(prefix="mhd_provenance_") as temporary:
        source = Path(temporary) / "manifest.json"
        source.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        manager.text(source, name=logical_name, store=True)


def _source_dataset_for_stats(stats_dataset: str) -> str:
    path = Path(stats_dataset)
    stem = path.stem
    if not stem.endswith("_stats"):
        raise ValueError(f"Not a statistics dataset: {stats_dataset}")
    return (path.parent / f"{stem[:-6]}{path.suffix}").as_posix()


def _split_statistic_name(variable_name: str) -> tuple[str, str] | None:
    for statistic in STAT_NAMES:
        suffix = f"_{statistic}"
        if variable_name.endswith(suffix):
            return variable_name[: -len(suffix)], statistic
    return None


def _stat_units(source_units: str | None, statistic: str) -> str | None:
    if source_units is None:
        return None
    if statistic == "var":
        return f"({source_units})^2"
    return source_units


def _register_source_variables(
    manager: Manager,
    index: ProvenanceIndex,
    run_name: str,
    run: QualifiedName,
    dataset: str,
    path: Path,
) -> None:
    for physical_name in discover_adios_variables(path):
        definition = canonical_definition(physical_name)
        units = units_for_definition(definition)
        coordinate_system = coordinate_system_for_definition(definition)
        reference = manager.add_variable(
            run=run,
            dataset=dataset,
            variable=physical_name,
            definition=definition,
            units=units,
            coordinate_system=coordinate_system,
        )
        index.add(
            run_name,
            dataset,
            physical_name,
            LogicalProduct(reference, definition, units, coordinate_system),
        )


def _register_derived_variables(
    manager: Manager,
    index: ProvenanceIndex,
    run_name: str,
    run: QualifiedName,
    dataset: str,
    path: Path,
    agent: QualifiedName,
    plan: QualifiedName,
    plan_location: str,
) -> None:
    for physical_name in discover_adios_variables(path):
        spec = DERIVED_PRODUCTS.get(physical_name)
        if spec is None:
            continue

        inputs = {
            role: index.by_definition[(run_name, definition)].reference
            for role, definition in spec["inputs"].items()
        }
        result = manager.add_activity(
            "quantity_of_interest",
            inputs=inputs,
            outputs={
                "result": VariableSpec(
                    run=run,
                    dataset=dataset,
                    variable=physical_name,
                    definition=str(spec["definition"]),
                    units=str(spec["units"]),
                    coordinate_system="Cartesian",
                )
            },
            action_spec={
                "operation": spec["operation"],
                "discretization": "numpy.gradient with unit grid spacing",
                "script_dataset": plan_location,
            },
            agent=agent,
            plan=plan,
        )
        index.add(
            run_name,
            dataset,
            physical_name,
            LogicalProduct(
                result.outputs["result"],
                str(spec["definition"]),
                str(spec["units"]),
                "Cartesian",
            ),
        )


def _register_statistics(
    manager: Manager,
    index: ProvenanceIndex,
    run_name: str,
    run: QualifiedName,
    stats_dataset: str,
    stats_path: Path,
    agent: QualifiedName,
    plan: QualifiedName,
    plan_location: str,
) -> None:
    source_dataset = _source_dataset_for_stats(stats_dataset)
    grouped: dict[str, dict[str, str]] = {}
    for output_name in discover_adios_variables(stats_path):
        parsed = _split_statistic_name(output_name)
        if parsed is None:
            continue
        source_name, statistic = parsed
        grouped.setdefault(source_name, {})[statistic] = output_name

    for source_name, outputs_by_statistic in sorted(grouped.items()):
        source = index.by_physical.get((source_dataset, source_name))
        if source is None:
            raise LookupError(
                f"Statistics dataset {stats_dataset!r} references unknown source "
                f"{source_dataset!r}:{source_name!r}"
            )

        outputs = {
            statistic: VariableSpec(
                run=run,
                dataset=stats_dataset,
                variable=output_name,
                definition=f"{source.definition}_{statistic}",
                units=_stat_units(source.units, statistic),
            )
            for statistic, output_name in sorted(outputs_by_statistic.items())
        }
        result = manager.add_activity(
            "quantity_of_interest",
            inputs={"source": source.reference},
            outputs=outputs,
            action_spec={
                "operation": "descriptive_statistics",
                "statistics": sorted(outputs),
                "scope": "all elements per output timestep",
                "script_dataset": plan_location,
            },
            agent=agent,
            plan=plan,
        )
        for statistic, reference in result.outputs.items():
            output_name = outputs_by_statistic[statistic]
            output_spec = outputs[statistic]
            index.add(
                run_name,
                stats_dataset,
                output_name,
                LogicalProduct(reference, output_spec.definition, output_spec.units, None),
            )


def record_campaign_provenance(
    manager: Manager,
    datasets: list[Path],
    out_root: Path,
) -> ProvenanceIndex:
    """Record runs, source variables, derived fields, and statistics.

    The caller must register every dataset with Manager.data first because
    logical variables point to existing ACA dataset identities.
    """
    if manager.prov_documents(active=True):
        raise ValueError("The campaign already contains active provenance; recreate it before ingesting again")

    resolved_root = out_root.resolve()
    dataset_paths = {dataset_name(path, resolved_root): path for path in datasets if path.exists()}
    primary = {name: path for name, path in dataset_paths.items() if Path(name).name == "output.bp"}
    if not primary:
        raise ValueError("Provenance ingest requires at least one run-relative output.bp dataset")

    index = ProvenanceIndex()
    solver = manager.add_agent("software", "ot_mhd")

    for name, path in sorted(primary.items()):
        run_name = run_name_from_dataset(name, resolved_root)
        parameters = path.parent / "input_parameters.txt"
        plan_location = None
        if parameters.is_file():
            plan_location = _store_plan_source(
                manager,
                parameters,
                f"{run_name}/plans/input_parameters.txt",
            )
        run_plan = manager.add_plan(
            f"{run_name} simulation configuration",
            location=plan_location,
        )
        run = manager.add_run(run_name, plan=run_plan, agent=solver)
        index.runs[run_name] = run
        _register_source_variables(manager, index, run_name, run, name, path)

    derived_paths = {
        name: path for name, path in dataset_paths.items() if Path(name).name == "analysis.bp"
    }
    stats_paths = {
        name: path for name, path in dataset_paths.items() if Path(name).stem.endswith("_stats")
    }
    analysis_agent = (
        manager.add_agent("software", "NumPy", version=np.__version__)
        if derived_paths or stats_paths
        else None
    )
    if derived_paths:
        assert analysis_agent is not None
        script = Path(__file__).with_name("adios_derived_variables.py")
        workflow_plan = add_workflow_plan(
            manager,
            name="MHD derived-variable workflow",
            workflow="derived_variables",
            script_path=script,
            details={
                "selection": {"datasets": sorted(derived_paths)},
                "parameters": {
                    "discretization": "numpy.gradient with unit grid spacing",
                    "products": sorted(DERIVED_PRODUCTS),
                },
            },
        )
        for name, path in sorted(derived_paths.items()):
            run_name = run_name_from_dataset(name, resolved_root)
            _register_derived_variables(
                manager,
                index,
                run_name,
                index.runs[run_name],
                name,
                path,
                analysis_agent,
                workflow_plan.reference,
                workflow_plan.script_dataset,
            )

    if stats_paths:
        assert analysis_agent is not None
        script = Path(__file__).with_name("adios_stats.py")
        workflow_plan = add_workflow_plan(
            manager,
            name="MHD descriptive-statistics workflow",
            workflow="descriptive_statistics",
            script_path=script,
            details={
                "selection": {"datasets": sorted(stats_paths)},
                "parameters": {
                    "scope": "all elements per output timestep",
                    "statistics": list(STAT_NAMES),
                },
            },
        )
        for name, path in sorted(stats_paths.items()):
            run_name = run_name_from_dataset(name, resolved_root)
            _register_statistics(
                manager,
                index,
                run_name,
                index.runs[run_name],
                name,
                path,
                analysis_agent,
                workflow_plan.reference,
                workflow_plan.script_dataset,
            )

    return index


def active_document(manager: Manager) -> ProvDocument:
    """Return the campaign-authored active document."""
    documents = manager.prov_documents(active=True)
    if len(documents) != 1:
        raise LookupError(f"Expected one active PROV document, found {len(documents)}")
    return manager.prov_document(documents[0].document_id)


def find_logical_variable(
    document: ProvDocument,
    dataset: str,
    variable: str,
) -> ProvEntity:
    """Resolve one logical variable by its campaign dataset and physical name."""
    matches = [
        record
        for record in document.get_records(ProvEntity)
        if HPC["LogicalVariable"] in record.get_asserted_types()
        and dataset in record.get_attribute(HPC["datasetName"])
        and variable in record.get_attribute(HPC["variable"])
    ]
    if len(matches) != 1:
        raise LookupError(
            f"Expected one logical variable for {dataset!r}:{variable!r}, found {len(matches)}"
        )
    return matches[0]


def _input_records(
    document: ProvDocument,
    source_dataset: str,
    semantic_kwargs: dict[str, Any],
) -> dict[str, ProvEntity]:
    inputs: dict[str, ProvEntity] = {}

    def add(role: str, variable: str) -> None:
        inputs[role] = find_logical_variable(document, source_dataset, variable)

    if semantic_kwargs.get("variable"):
        add("primary", str(semantic_kwargs["variable"]))
    if semantic_kwargs.get("color_by"):
        add("color", str(semantic_kwargs["color_by"]))
    if semantic_kwargs.get("contour_by"):
        add("contour", str(semantic_kwargs["contour_by"]))
    if semantic_kwargs.get("y_axis"):
        value = semantic_kwargs["y_axis"]
        names = [value] if isinstance(value, str) else list(value)
        for index, name in enumerate(names):
            add(f"y_axis_{index}", str(name))
    if semantic_kwargs.get("streamline_by"):
        value = semantic_kwargs["streamline_by"]
        names = [value] if isinstance(value, str) else list(value)
        for index, name in enumerate(names):
            add(f"streamline_{index}", str(name))

    if not inputs:
        raise ValueError("Visualization provenance requires at least one logical-variable input")
    return inputs


def _record_definition(record: ProvEntity) -> str:
    """Return the single scientific definition on a logical variable."""
    definitions = record.get_attribute(HPC["variableDefinition"])
    if len(definitions) != 1:
        raise ValueError(f"Logical variable has {len(definitions)} definitions: {record.identifier}")
    return str(next(iter(definitions)))


def _visualization_definition(records: dict[str, ProvEntity], vis_type: str) -> str:
    """Choose a scientific identity for a generated image sequence.

    A scalar-field view inherits the primary variable's definition. A
    streamline view is about the vector field, not the optional scalar field
    used only as its color background, so matching component suffixes are
    collapsed (for example, magnetic_field_x/y -> magnetic_field).
    """
    primary = records.get("primary")
    if primary is not None:
        return f"{_token(_record_definition(primary))}_visualization"

    component_definitions = [
        _record_definition(record)
        for role, record in sorted(records.items())
        if role.startswith("streamline_")
    ]
    if component_definitions:
        bases = {re.sub(r"_[xyz]$", "", definition) for definition in component_definitions}
        if len(bases) == 1:
            return f"{_token(next(iter(bases)))}_visualization"

    # Manager.visualization uses role-specific arguments rather than a generic
    # "primary" role for most scalar plots. Prefer the field carrying the
    # picture's values before falling back to the presentation kind.
    for role in ("color", "contour", "y_axis_0"):
        record = records.get(role)
        if record is not None:
            return f"{_token(_record_definition(record))}_visualization"

    # This fallback remains meaningful for future multi-input visualization
    # kinds whose inputs do not share a conventional component name.
    return f"{_token(vis_type)}_visualization"


class VisualizationProvenanceRecorder:
    """Append visualization Activities after image sequences are registered."""

    def __init__(
        self,
        manager: Manager,
        script_path: Path,
        *,
        workflow: str = "render_visualizations",
        workflow_details: dict[str, Any] | None = None,
    ):
        self.manager = manager
        self.script_path = script_path.resolve()
        self.workflow = workflow
        self.workflow_details = dict(workflow_details or {})
        self.agent = manager.add_agent(
            "software",
            "Matplotlib",
            version=_package_version("matplotlib"),
        )
        self.plan: tuple[QualifiedName, str] | None = None

    def _plan(self) -> tuple[QualifiedName, str]:
        """Return the configured workflow Plan shared by this invocation."""
        if self.plan is not None:
            return self.plan
        labels = {
            "render_visualizations": "MHD visualization workflow",
            "store_scalar_fields": "MHD scalar-field visualization workflow",
        }
        workflow_plan = add_workflow_plan(
            self.manager,
            name=labels.get(self.workflow, f"MHD {self.workflow} workflow"),
            workflow=self.workflow,
            script_path=self.script_path,
            details=self.workflow_details,
        )
        self.plan = (workflow_plan.reference, workflow_plan.script_dataset)
        return self.plan

    def record(
        self,
        *,
        source_dataset: str,
        sequence_name: str,
        vis_type: str,
        semantic_kwargs: dict[str, Any],
        steps: list[int],
        rendering_parameters: dict[str, Any],
    ) -> QualifiedName:
        """Record one sequence as a single time-varying logical data product."""
        document = active_document(self.manager)
        records = _input_records(document, source_dataset, semantic_kwargs)
        input_runs = {
            next(iter(record.get_attribute(HPC["run"])))
            for record in records.values()
        }
        if len(input_runs) != 1:
            raise ValueError("A visualization activity must use logical variables from one run")
        run = next(iter(input_runs))
        run_name = Path(source_dataset).parent.as_posix()
        if run_name == ".":
            run_name = "root"

        info = self.manager.info(list_replicas=False, list_files=False)
        sequence = next(
            (item for item in info.visualization_sequences.values() if item.name == sequence_name),
            None,
        )
        if sequence is None:
            raise LookupError(f"Visualization sequence was not registered: {sequence_name}")

        activity_id = uuid.uuid4()
        manifest_name = (
            f"{run_name}/provenance/visualizations/"
            f"{_token(Path(sequence_name).name)}_{activity_id.hex}.json"
        )
        manifest = {
            "sequence_name": sequence.name,
            "visualization_type": sequence.vis_type,
            "thumbnail_dataset": sequence.thumbnail_dataset_name,
            "items": [
                {
                    "order": item.item_order,
                    "type": item.item_type,
                    "dataset": item.dataset_name,
                    "uuid": item.item_uuid,
                }
                for item in sequence.items
            ],
        }
        _store_json(self.manager, manifest_name, manifest)

        plan, plan_location = self._plan()
        definition = _visualization_definition(records, vis_type)
        result = self.manager.add_activity(
            "visualization",
            inputs={role: record.identifier for role, record in records.items()},
            outputs={
                "image_sequence": VariableSpec(
                    run=run,
                    dataset=manifest_name,
                    variable="image_sequence",
                    definition=definition,
                )
            },
            action_spec={
                "visualization_type": vis_type,
                "steps": [int(step) for step in steps],
                "semantic_variables": semantic_kwargs,
                "rendering_parameters": rendering_parameters,
                "sequence_manifest": manifest_name,
                "script_dataset": plan_location,
            },
            agent=self.agent,
            plan=plan,
            activity_id=activity_id,
        )
        return result.outputs["image_sequence"]
