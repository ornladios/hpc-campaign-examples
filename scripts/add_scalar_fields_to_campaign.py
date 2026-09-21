#!/usr/bin/env python3
"""
Store ADIOS 2D variable steps as SCALAR_FIELD visualization sequences.

This complements render_adios_visualizations_to_campaign.py. Instead of
rendering PNG images, it stores each selected 2D array step directly as a
SCALAR_FIELD item and registers a visualization sequence that points back to
the source ADIOS variable.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .mhd_provenance import VisualizationProvenanceRecorder
    from .render_adios_visualizations_to_campaign import (
        MissingVariableError,
        _import_hpc_campaign,
        build_directory_map,
        discover_variables,
        live_adios_datasets,
        normalize_vis_type,
        read_variable_arrays,
        resolve_dataset_path,
        resolve_requested_variable,
        select_datasets,
        split_csv,
        visualization_semantic_kwargs,
        visualization_sequence_name,
    )
except ImportError:  # Direct execution places scripts/ rather than the repo root on sys.path.
    from mhd_provenance import VisualizationProvenanceRecorder
    from render_adios_visualizations_to_campaign import (
        MissingVariableError,
        _import_hpc_campaign,
        build_directory_map,
        discover_variables,
        live_adios_datasets,
        normalize_vis_type,
        read_variable_arrays,
        resolve_dataset_path,
        resolve_requested_variable,
        select_datasets,
        split_csv,
        visualization_semantic_kwargs,
        visualization_sequence_name,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Store ADIOS 2D variable steps as SCALAR_FIELD visualization sequences."
    )
    parser.add_argument("--archive", required=True, help="Campaign archive name/path.")
    parser.add_argument("--campaign_store", default="", help="Campaign store path.")
    parser.add_argument(
        "--dataset",
        action="append",
        default=None,
        help="Exact campaign ADIOS dataset name. Can be repeated or comma-separated.",
    )
    parser.add_argument(
        "--datasetPattern",
        action="append",
        default=None,
        help="fnmatch pattern for campaign ADIOS dataset names, e.g. '*/output.bp'.",
    )
    parser.add_argument("--allDatasets", action="store_true", help="Use all ADIOS datasets in the campaign.")
    variable_group = parser.add_mutually_exclusive_group()
    variable_group.add_argument(
        "--variable",
        action="append",
        help="ADIOS variable to store. Can be repeated or comma-separated.",
    )
    variable_group.add_argument("--allVariables", action="store_true", help="Try every ADIOS variable.")
    parser.add_argument(
        "--data_root",
        type=Path,
        default=None,
        help="Root used to resolve relative BP replica paths stored in the campaign.",
    )
    parser.add_argument("--step", type=int, default=-1, help="Step to store. Negative means from the end.")
    parser.add_argument("--allSteps", action="store_true", help="Store every ADIOS step instead of --step.")
    parser.add_argument("--visType", default="heatmap", help="Visualization kind recorded in the campaign.")
    parser.add_argument(
        "--name",
        default=None,
        help=(
            "Short visualization name for one variable, expanded to "
            "<dataset>/visualizations/<name>. If omitted, defaults to "
            "<variable>_scalar_field."
        ),
    )
    parser.add_argument("--replace", action="store_true", help="Replace existing visualization sequences.")
    parser.add_argument(
        "--dtype",
        default=None,
        help="Optional NumPy dtype used to store scalar fields, e.g. float32.",
    )
    parser.add_argument("--skipMissing", action="store_true", help="Skip datasets missing a requested variable.")
    parser.add_argument(
        "--skipNon2D",
        action="store_true",
        help="Skip variables whose selected steps are not rank-2 after squeeze.",
    )
    parser.add_argument("--dryRun", action="store_true", help="Print selected work without writing scalar fields.")
    parser.add_argument("--listDatasets", action="store_true", help="Print matching campaign datasets and exit.")
    parser.add_argument("--showInfo", action="store_true", help="Print hpc-campaign info after writing.")
    parser.add_argument(
        "--exportProv",
        type=Path,
        default=None,
        help="Optional path for exporting the updated W3C PROV document as PROV-JSON.",
    )
    return parser.parse_args()


def scalar_field_sequence_short_name(
    variable: str,
    explicit_name: str | None,
    variable_count: int,
) -> str:
    if explicit_name is not None:
        if variable_count > 1:
            raise SystemExit("--name can only be used with one --variable.")
        return explicit_name
    return f"{variable}_scalar_field".replace("/", "_").replace(" ", "_")


def scalar_field_item_name(sequence_name: str, step: int) -> str:
    return f"{sequence_name}/scalar.{int(step):06d}.raw"


def to_scalar_field_array(
    array: np.ndarray,
    *,
    dataset_name: str,
    variable: str,
    step: int,
) -> np.ndarray:
    field = np.asarray(array).squeeze()
    if field.ndim != 2:
        raise ValueError(
            f"Expected rank-2 data for {dataset_name}:{variable} step={step}; "
            f"got ndim={field.ndim}"
        )
    return np.ascontiguousarray(field)


def add_scalar_field_sequence(
    manager,
    *,
    dataset_name: str,
    variable: str,
    vis_type: str,
    name: str,
    steps: list[int],
    arrays: list[np.ndarray],
    replace: bool,
    dtype: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    if not arrays:
        raise SystemExit("No scalar fields were selected.")

    sequence_name = visualization_sequence_name(dataset_name, name)
    item_names: list[str] = []
    for step, array in zip(steps, arrays, strict=True):
        field = to_scalar_field_array(
            array,
            dataset_name=dataset_name,
            variable=variable,
            step=step,
        )
        item_name = scalar_field_item_name(sequence_name, step)
        item_metadata = dict(metadata or {})
        item_metadata.update(
            {
                "generated_by": Path(__file__).name,
                "source_dataset": dataset_name,
                "source_variable": variable,
                "step": int(step),
            }
        )
        manager.scalar_field_data(
            field,
            name=item_name,
            dtype=dtype,
            metadata=item_metadata,
        )
        item_names.append(item_name)

    return manager.visualization_sequence(
        name=sequence_name,
        vis_type=normalize_vis_type(vis_type),
        source_dataset=dataset_name,
        variables=[{"name": variable, "role": "color-by"}],
        items=[{"type": "SCALAR_FIELD", "name": item_name} for item_name in item_names],
        metadata={
            "generated_by": Path(__file__).name,
            "steps": [int(step) for step in steps],
            "scalar_fields": True,
            "dtype": dtype or "source",
        },
        replace=replace,
    )


def selected_scalar_variables(
    bp_path: Path,
    requested_variables: list[str],
    all_variables: bool,
) -> list[str]:
    if not all_variables:
        return requested_variables
    return discover_variables(bp_path)


def main() -> int:
    args = parse_args()

    exact_names = split_csv(args.dataset)
    patterns = split_csv(args.datasetPattern)
    variables = split_csv(args.variable)

    data_root = args.data_root.expanduser().resolve() if args.data_root is not None else None
    if args.dtype:
        np.dtype(args.dtype)

    manager_class, format_info_fn = _import_hpc_campaign()
    manager = manager_class(archive=args.archive, campaign_store=args.campaign_store)
    manager.open(create=False)

    added = 0
    skipped = 0
    provenance_recorder = None
    try:
        info_data = manager.info(list_replicas=True, list_files=False)
        if args.listDatasets:
            if exact_names or patterns or args.allDatasets:
                datasets = select_datasets(info_data, exact_names, patterns, args.allDatasets)
            else:
                datasets = live_adios_datasets(info_data)
            for dataset in datasets:
                print(dataset.name)
            return 0

        if args.allVariables and args.name is not None:
            raise SystemExit("--name cannot be used with --allVariables.")
        if not variables and not args.allVariables:
            raise SystemExit("Select at least one variable with --variable or use --allVariables.")
        if not args.dryRun:
            active_documents = manager.prov_documents(active=True)
            if len(active_documents) != 1:
                raise SystemExit(
                    "Scalar-field provenance requires exactly one active campaign PROV document; "
                    "create the campaign with add_adios_files_to_campaign.py first."
                )

        datasets = select_datasets(info_data, exact_names, patterns, args.allDatasets)
        print(f"[info] datasets : {len(datasets)}")
        print(f"[info] variables: {'<all>' if args.allVariables else variables}")
        print(f"[info] visType  : {normalize_vis_type(args.visType)}")
        workflow_details = {
            "selection": {
                "datasets": [dataset.name for dataset in datasets],
                "dataset_patterns": patterns,
                "requested_datasets": exact_names,
                "variables": "all" if args.allVariables else variables,
                "steps": "all" if args.allSteps else {"index": args.step},
            },
            "parameters": {
                "dtype": args.dtype or "source",
                "visualization_type": normalize_vis_type(args.visType),
            },
            "output_policy": {"replace": bool(args.replace)},
        }

        directory_map = build_directory_map(info_data)
        for dataset in datasets:
            bp_path = resolve_dataset_path(dataset, data_root, directory_map)
            print(f"[info] dataset path: {bp_path}")
            try:
                dataset_variables = selected_scalar_variables(
                    bp_path,
                    variables,
                    args.allVariables,
                )
            except MissingVariableError as exc:
                if args.skipMissing:
                    print(f"[warn] skipped dataset: {exc}")
                    skipped += 1
                    continue
                raise SystemExit(str(exc)) from exc

            for variable in dataset_variables:
                try:
                    physical_variable = resolve_requested_variable(bp_path, variable, args.visType)
                    steps, arrays = read_variable_arrays(
                        bp_path,
                        physical_variable,
                        args.step,
                        args.allSteps,
                    )
                    fields = [
                        to_scalar_field_array(
                            array,
                            dataset_name=dataset.name,
                            variable=physical_variable,
                            step=step,
                        )
                        for step, array in zip(steps, arrays, strict=True)
                    ]
                except (MissingVariableError, ValueError) as exc:
                    if args.skipMissing or args.skipNon2D:
                        print(f"[warn] skipped: {exc}")
                        skipped += 1
                        continue
                    raise SystemExit(str(exc)) from exc

                name = scalar_field_sequence_short_name(
                    variable,
                    args.name,
                    len(dataset_variables),
                )
                sequence_name = visualization_sequence_name(dataset.name, name)
                if args.dryRun:
                    print(
                        f"[dry-run] {dataset.name} variable={physical_variable} "
                        f"sequence={sequence_name} scalar_fields={len(fields)}"
                    )
                    continue

                visid = add_scalar_field_sequence(
                    manager,
                    dataset_name=dataset.name,
                    variable=physical_variable,
                    vis_type=args.visType,
                    name=name,
                    steps=steps,
                    arrays=fields,
                    replace=args.replace,
                    dtype=args.dtype,
                )
                print(f"[ok] added scalar-field sequence visid={visid} name={sequence_name} items={len(fields)}")

                semantic_kwargs = visualization_semantic_kwargs(
                    physical_variable,
                    normalize_vis_type(args.visType),
                    set(discover_variables(bp_path)),
                )
                if provenance_recorder is None:
                    provenance_recorder = VisualizationProvenanceRecorder(
                        manager,
                        Path(__file__),
                        workflow="store_scalar_fields",
                        workflow_details=workflow_details,
                    )
                provenance_output = provenance_recorder.record(
                    source_dataset=dataset.name,
                    sequence_name=sequence_name,
                    vis_type=normalize_vis_type(args.visType),
                    semantic_kwargs=semantic_kwargs,
                    steps=steps,
                    rendering_parameters={
                        "scalar_fields": True,
                        "dtype": args.dtype or "source",
                    },
                )
                print(f"[ok] provenance output={provenance_output}")
                added += 1

        if args.exportProv is not None:
            manager.export_prov("campaign-provenance", args.exportProv.expanduser().resolve())
            print(f"[ok] exported PROV-JSON: {args.exportProv.expanduser().resolve()}")

        if args.showInfo:
            print(format_info_fn(manager.info(list_replicas=False, list_files=False)))
    finally:
        manager.close()

    print(f"[ok] done. scalar-field sequences={added} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
