"""End-to-end test for the tiny toy_campaign example."""

from pathlib import Path

from adios2.stream import Stream
from hpc_campaign import Manager
from hpc_campaign.prov_mapping import HPC
from prov.model import PROV, ProvActivity, ProvDerivation, ProvEntity, ProvGeneration

from scripts.toy_campaign import (
    FILE1_DATASET,
    FILE2_DATASET,
    VARIABLE_NAME,
    ToyCampaignResult,
    build_toy_campaign,
)


def _adios_variables(path: Path) -> set[str]:
    """Return the variables visible in the first ADIOS step."""
    with Stream(str(path), "r") as stream:
        for _step in stream.steps():
            return set((stream.available_variables() or {}).keys())
    raise AssertionError(f"ADIOS dataset has no steps: {path}")


def _logical_variables(document) -> list[ProvEntity]:
    """Return campaign logical-variable entities from a PROV document."""
    return [
        record
        for record in document.get_records(ProvEntity)
        if HPC["LogicalVariable"] in record.get_asserted_types()
    ]


def _logical_variable_by_dataset(document, dataset: str, variable: str) -> ProvEntity:
    """Find one logical variable by its backing dataset and physical name."""
    matches = [
        record
        for record in _logical_variables(document)
        if dataset in record.get_attribute(HPC["datasetName"])
        and variable in record.get_attribute(HPC["variable"])
    ]
    assert len(matches) == 1
    return matches[0]


def test_toy_campaign_builds_two_files_visualization_and_prov(tmp_path: Path) -> None:
    """The example should create the intended tiny payload and lineage graph."""
    result: ToyCampaignResult = build_toy_campaign(tmp_path, archive="toy_campaign.aca", seed=7, shape=(5, 6))

    assert result.archive_path.is_file()
    assert result.file1_path.exists()
    assert result.file2_path.exists()
    assert result.file1_image_path.is_file()
    assert result.file2_image_path.is_file()
    assert result.prov_json_path.is_file()

    # Each source BP file contains exactly one variable, keeping the payload
    # small enough to inspect while still exercising the real ADIOS path.
    assert _adios_variables(result.file1_path) == {VARIABLE_NAME}
    assert _adios_variables(result.file2_path) == {VARIABLE_NAME}

    manager = Manager(archive="toy_campaign.aca", campaign_store=str(tmp_path))
    manager.open()
    try:
        layout = manager.validate_schema()
        assert layout["file_groups"]["file1"]["datasets"] == [FILE1_DATASET]
        assert layout["file_groups"]["file2"]["datasets"] == [FILE2_DATASET]

        info_data = manager.info(list_replicas=False, list_files=False)
        adios_datasets = {
            dataset.name
            for dataset in info_data.datasets.values()
            if dataset.del_time == 0 and dataset.file_format == "ADIOS"
        }
        assert adios_datasets == {FILE1_DATASET, FILE2_DATASET}

        sequences = {
            item.name: item
            for item in info_data.visualization_sequences.values()
            if item.name
            in {
                result.file1_visualization_sequence,
                result.file2_visualization_sequence,
            }
        }
        assert set(sequences) == {
            result.file1_visualization_sequence,
            result.file2_visualization_sequence,
        }
        assert sequences[result.file1_visualization_sequence].vis_type == "heatmap"
        assert sequences[result.file2_visualization_sequence].vis_type == "heatmap"
        assert (
            sequences[result.file1_visualization_sequence].items[0].dataset_name
            == result.file1_visualization_image_dataset
        )
        assert (
            sequences[result.file2_visualization_sequence].items[0].dataset_name
            == result.file2_visualization_image_dataset
        )

        document = manager.prov_document("campaign-provenance")
        asserted_types = {
            asserted_type for record in document.get_records() for asserted_type in record.get_asserted_types()
        }
        assert HPC["Simulation"] in asserted_types
        assert HPC["Visualization"] in asserted_types

        simulation_labels = {
            str(next(iter(record.get_attribute(PROV["label"]))))
            for record in document.get_records(ProvActivity)
            if HPC["Simulation"] in record.get_asserted_types()
        }
        assert simulation_labels == {"sim1", "sim2"}

        file1_var = _logical_variable_by_dataset(document, FILE1_DATASET, VARIABLE_NAME)
        file2_var = _logical_variable_by_dataset(document, FILE2_DATASET, VARIABLE_NAME)
        assert file1_var.get_attribute(HPC["variableDefinition"]) == {"var"}
        assert file2_var.get_attribute(HPC["variableDefinition"]) == {"var"}
        file1_sequence = manager.visualization_sequence_entity(result.file1_visualization_sequence)
        file2_sequence = manager.visualization_sequence_entity(result.file2_visualization_sequence)
        assert HPC["ImageSequence"] in document.get_record(file1_sequence)[0].get_asserted_types()
        assert HPC["ImageSequence"] in document.get_record(file2_sequence)[0].get_asserted_types()
        file1_image = manager.dataset_entity(result.file1_visualization_image_dataset)
        file2_image = manager.dataset_entity(result.file2_visualization_image_dataset)
        assert HPC["Image"] in document.get_record(file1_image)[0].get_asserted_types()
        assert HPC["Image"] in document.get_record(file2_image)[0].get_asserted_types()

        # Each generated sequence traces back to the var from its own file.
        file1_parents = {
            record.args[1]
            for record in document.get_records(ProvDerivation)
            if record.args[0] == file1_sequence
        }
        file2_parents = {
            record.args[1]
            for record in document.get_records(ProvDerivation)
            if record.args[0] == file2_sequence
        }
        assert file1_parents == {file1_var.identifier}
        assert file2_parents == {file2_var.identifier}

        generations = {
            record.args[0]: record.args[1]
            for record in document.get_records(ProvGeneration)
        }
        simulations = {
            str(next(iter(record.get_attribute(PROV["label"])))): record.identifier
            for record in document.get_records(ProvActivity)
            if HPC["Simulation"] in record.get_asserted_types()
        }
        assert generations[file1_var.identifier] == simulations["sim1"]
        assert generations[file2_var.identifier] == simulations["sim2"]

        visualization_activities = [
            record
            for record in document.get_records(ProvActivity)
            if HPC["Visualization"] in record.get_asserted_types()
        ]
        assert len(visualization_activities) == 2
        assert generations[file1_sequence] in {activity.identifier for activity in visualization_activities}
        assert generations[file2_sequence] in {activity.identifier for activity in visualization_activities}
    finally:
        manager.close()
