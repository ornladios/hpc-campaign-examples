"""W3C PROV mapping for the Orszag-Tang campaign example.

The ADIOS files remain the authoritative description of array shape, type, and
timesteps. This module records the scientific identity and lineage needed to
answer questions such as "which pressure field produced this image?".
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
from adios2.stream import Stream
from hpc_campaign import Manager
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


@dataclass
class ProvenanceIndex:
    """References created while ingesting one campaign."""

    simulations: dict[str, QualifiedName] = field(default_factory=dict)
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
    dataset: str,
    path: Path,
) -> dict[str, QualifiedName]:
    outputs: dict[str, QualifiedName] = {}
    for position, physical_name in enumerate(discover_adios_variables(path)):
        definition = canonical_definition(physical_name)
        units = units_for_definition(definition)
        coordinate_system = coordinate_system_for_definition(definition)
        reference = manager.add_variable(
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
        outputs[f"variable_{position}"] = reference
    if not outputs:
        raise ValueError(f"Simulation dataset contains no variables: {dataset}")
    return outputs


def _register_derived_variables(
    manager: Manager,
    index: ProvenanceIndex,
    run_name: str,
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
        output = manager.add_variable(
            dataset=dataset,
            variable=physical_name,
            definition=str(spec["definition"]),
            units=str(spec["units"]),
            coordinate_system="Cartesian",
        )
        manager.add_activity(
            "quantity_of_interest",
            inputs=inputs,
            outputs={"result": output},
            metadata={
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
                output,
                str(spec["definition"]),
                str(spec["units"]),
                "Cartesian",
            ),
        )


def _register_statistics(
    manager: Manager,
    index: ProvenanceIndex,
    run_name: str,
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
            statistic: manager.add_variable(
                dataset=stats_dataset,
                variable=output_name,
                definition=f"{source.definition}_{statistic}",
                units=_stat_units(source.units, statistic),
            )
            for statistic, output_name in sorted(outputs_by_statistic.items())
        }
        manager.add_activity(
            "quantity_of_interest",
            inputs={"source": source.reference},
            outputs=outputs,
            metadata={
                "operation": "descriptive_statistics",
                "statistics": sorted(outputs),
                "scope": "all elements per output timestep",
                "script_dataset": plan_location,
            },
            agent=agent,
            plan=plan,
        )
        for statistic, reference in outputs.items():
            output_name = outputs_by_statistic[statistic]
            definition = f"{source.definition}_{statistic}"
            index.add(
                run_name,
                stats_dataset,
                output_name,
                LogicalProduct(
                    reference,
                    definition,
                    _stat_units(source.units, statistic),
                    None,
                ),
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
        source_outputs = _register_source_variables(manager, index, run_name, name, path)
        index.simulations[run_name] = manager.add_activity(
            "simulation",
            name=run_name,
            outputs=source_outputs,
            agent=solver,
            plan=run_plan,
        ).activity

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
        # The script is one reusable Plan. Run-specific parameters belong on
        # the simulation Plans and operation-specific values belong in each
        # Activity metadata; duplicating the script per run
        # would add metadata without changing its identity or meaning.
        # Root-level metadata must not introduce another schema run scope.
        plan_location = _store_plan_source(manager, script, "__provenance_plan_adios_derived_variables.py")
        plan = manager.add_plan("MHD derived-variable calculation", location=plan_location)
        for name, path in sorted(derived_paths.items()):
            run_name = run_name_from_dataset(name, resolved_root)
            _register_derived_variables(
                manager,
                index,
                run_name,
                name,
                path,
                analysis_agent,
                plan,
                plan_location,
            )

    if stats_paths:
        assert analysis_agent is not None
        script = Path(__file__).with_name("adios_stats.py")
        plan_location = _store_plan_source(manager, script, "__provenance_plan_adios_stats.py")
        plan = manager.add_plan("MHD descriptive-statistics calculation", location=plan_location)
        for name, path in sorted(stats_paths.items()):
            run_name = run_name_from_dataset(name, resolved_root)
            _register_statistics(
                manager,
                index,
                run_name,
                name,
                path,
                analysis_agent,
                plan,
                plan_location,
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


class VisualizationProvenanceRecorder:
    """Append visualization Activities after image sequences are registered."""

    def __init__(self, manager: Manager, script_path: Path):
        self.manager = manager
        self.script_path = script_path.resolve()
        self.agent = manager.add_agent(
            "software",
            "Matplotlib",
            version=_package_version("matplotlib"),
        )
        self.plan: tuple[QualifiedName, str] | None = None

    def _plan(self) -> tuple[QualifiedName, str]:
        """Return the one reusable rendering Plan shared by all runs."""
        if self.plan is not None:
            return self.plan
        location = _store_plan_source(
            self.manager,
            self.script_path,
            f"__provenance_plan_{self.script_path.name}",
        )
        plan = self.manager.add_plan("MHD visualization script", location=location)
        self.plan = (plan, location)
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
        output_variable: str = "image_sequence",
    ) -> Any:
        """Record one media collection or the datasets in a scalar-field sequence."""
        document = active_document(self.manager)
        records = _input_records(document, source_dataset, semantic_kwargs)

        activity_id = uuid.uuid4()
        info = self.manager.info(list_replicas=False, list_files=False)
        sequence = next(
            (item for item in info.visualization_sequences.values() if item.name == sequence_name),
            None,
        )
        if sequence is None:
            raise LookupError(f"Visualization sequence was not registered: {sequence_name}")

        item_types = {item.item_type for item in sequence.items}
        if item_types <= {"IMAGE", "VIDEO"}:
            sequence_entity = self.manager.add_visualization_sequence_entity(sequence_name)
            outputs = {output_variable: sequence_entity}
            sequence_items = [
                {
                    "order": item.item_order,
                    "dataset": item.dataset_name,
                    "item_type": item.item_type,
                }
                for item in sequence.items
            ]
        else:
            if len(sequence.items) != len(steps):
                raise ValueError(
                    f"Visualization sequence has {len(sequence.items)} items but {len(steps)} time steps: "
                    f"{sequence_name}"
                )
            outputs = {}
            sequence_items = []
            for position, item in enumerate(sequence.items):
                role = f"frame_{item.item_order}"
                outputs[role] = self.manager.add_dataset_entity(item.dataset_name)
                sequence_items.append(
                    {
                        "role": role,
                        "order": item.item_order,
                        "dataset": item.dataset_name,
                        "step": int(steps[position]),
                    }
                )
            if not outputs:
                raise ValueError(f"Visualization sequence has no items: {sequence_name}")

        plan, plan_location = self._plan()
        result = self.manager.add_activity(
            "visualization",
            inputs={role: record.identifier for role, record in records.items()},
            outputs=outputs,
            metadata={
                "visualization_type": vis_type,
                "steps": [int(step) for step in steps],
                "semantic_variables": semantic_kwargs,
                "rendering_parameters": rendering_parameters,
                "sequence_name": sequence_name,
                "sequence_items": sequence_items,
                "script_dataset": plan_location,
            },
            agent=self.agent,
            plan=plan,
            activity_id=activity_id,
        )
        return result
