# HPC Campaign Examples

This repository contains end-to-end examples for
[HPC Campaign](https://github.com/ornladios/hpc-campaign). The first example is
a 2D uniform-grid ideal-MHD Orszag-Tang vortex simulation with ADIOS2 output,
ensemble execution, derived analysis, statistics, campaign ingestion, schema
validation, and visualization.

The `main` branch uses only APIs available on the current `hpc-campaign`
`master` branch. This `provenance-pr-102` branch demonstrates the W3C PROV API
proposed by
[hpc-campaign PR #102](https://github.com/dpugmire/hpc-campaign/pull/102).
See [PROVENANCE.md](PROVENANCE.md) for the complete data-to-PROV mapping.

## TLDR

Use the same Python environment that has ADIOS2, Matplotlib, and the desired
`hpc-campaign` checkout installed. For example, when driving this from Seurat:

```bash
cd /Users/dpn/proj/hpc_campaign/hpc-campaign-examples
source /Users/dpn/proj/seurat/.venv/bin/activate
```

Build the solver, rerun the ensemble into `./runs`, recreate the campaign,
generate heatmap PNGs, streamlines, scalar-field sequences, and verify the
archive:

```bash
make all
```

If the simulation output already exists and only the campaign should be
rebuilt:

```bash
make create
make visualizations
make verify
```

Open the generated archive in Seurat:

```bash
cd /Users/dpn/proj/seurat
source .venv/bin/activate
python app.py /Users/dpn/ORNL_Dropbox/campaign-store/mhd_orszag_tang_runs_full.aca
```

## Seurat plugins

This repository ships Seurat plugins for diagnostics that are specific to the
Orszag-Tang MHD example. Point Seurat at the plugin directory before launching
the viewer:

```bash
cd /path/to/hpc-campaign-examples
export SEURAT_PLUGIN_PATH="$PWD/plugins/seurat"
```

The available plugins are:

- `mhd_energy_conservation`: plots relative total-energy drift, with an optional
  residual between `total_energy` and the component-energy sum.
- `mhd_energy_partition`: plots internal, kinetic, and magnetic energy fractions.

These plugins are offered for scalar energy variables with more than one ADIOS
step: `total_energy`, `internal_energy`, `kinetic_energy`, and
`magnetic_energy`.

## Toy campaign

For the smallest complete example, build `toy_campaign`:

```bash
python scripts/toy_campaign.py --output-root ./toy_campaign_output
```

This creates two ADIOS/BP source files, `file1.bp` and `file2.bp`, with one
random 2D variable named `var` in each file. It also renders `file1.bp:var`
to `file1_var_heatmap.png` and `file2.bp:var` to `file2_var_heatmap.png`, then
registers both images as heatmap visualizations. W3C PROV records that `sim1`
creates `file1.bp:var`, `sim2` creates `file2.bp:var`, and each visualization
Activity derives its image from the matching `var`. The script writes
`toy_campaign.aca` and `toy_campaign.prov.json` under the output root.

The example refuses to overwrite existing generated outputs. Use a fresh
`--output-root` or `--archive` name when rerunning it.

## Requirements

- Python 3.10 or newer
- CMake 3.18 or newer
- A C++17 compiler
- ADIOS2 with C++ bindings
- MPI, unless the solver is configured with `OT_ENABLE_MPI=OFF`

On this branch, the Python project installs the matching experimental
`hpc-campaign` branch along with the Matplotlib dependency used by the
rendering script:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

For development against an existing checkout instead, install that checkout
after installing this project so its editable package takes precedence:

```bash
python -m pip install -e /path/to/hpc-campaign
```

The Makefile uses the active `python` by default. Override it when needed:

```bash
make PYTHON=/Users/dpn/proj/seurat/.venv/bin/python all
```

Check the active environment:

```bash
make env
```

## Make workflow

The Makefile provides the common end-to-end workflow:

```bash
make runs            # build and run the configured ensemble into ./runs
make create          # recreate the ACA from ./runs, with derived fields and stats
make heatmaps        # add primary and derived PNG heatmap image sequences
make streamlines     # add velocity and magnetic streamline image sequences
make scalar-fields   # add raw SCALAR_FIELD visualization sequences
make visualizations  # run heatmaps, streamlines, and scalar-fields
make verify          # print the ACA info table
make all             # run runs, create, visualizations, and verify
```

`make create` passes `--recreate`, `--forceDerived`, and `--forceStats`; it
rebuilds campaign registration, derived datasets, and statistics from
`RUN_ROOT`. The visualization targets pass `--replace`; they replace matching
visualization sequences by name, but they do not delete unrelated old
sequences that are no longer selected by the Makefile variables.

Useful Make variables:

```bash
make all ARCHIVE=/path/to/mhd.aca
make runs RUN_ROOT=/path/to/runs
make heatmaps PRIMARY_VARS=pressure,rho,current_z
make heatmaps DERIVED_VARS=div_b,grad_pressure_abs
make streamlines STREAMLINE_VARS=velocity,magnetic
make scalar-fields SCALAR_PRIMARY_VARS=pressure,rho
make scalar-fields SCALAR_DERIVED_VARS=div_b,grad_pressure_abs
make scalar-fields SCALAR_FIELD_DTYPE=
```

Defaults:

- `RUN_ROOT=$(CURDIR)/runs`
- `ARCHIVE=/Users/dpn/ORNL_Dropbox/campaign-store/mhd_orszag_tang_runs_full.aca`
- `PRIMARY_VARS=pressure,rho,speed,current_z`
- `DERIVED_VARS=div_b,grad_pressure_abs,grad_rho_abs`
- `STREAMLINE_VARS=velocity,magnetic`
- `SCALAR_PRIMARY_VARS=pressure,rho,speed,current_z`
- `SCALAR_DERIVED_VARS=div_b,grad_pressure_abs,grad_rho_abs`
- `SCALAR_FIELD_DTYPE=float32`

Set `SCALAR_FIELD_DTYPE=` to preserve the source ADIOS dtype for scalar-field
payloads. The default `float32` keeps the campaign archive smaller.

## Build the solver

MPI build:

```bash
cmake -S . -B build -DOT_ENABLE_MPI=ON
cmake --build build -j
```

Serial build:

```bash
cmake -S . -B build -DOT_ENABLE_MPI=OFF
cmake --build build -j
```

## Run an ensemble

The JSON files in `ensembles/` describe named runs and their solver settings.
Run the small ensemble with:

```bash
python scripts/run_ensembles.py \
  --binary ./build/ot_mhd \
  --config ensembles/simple.json
```

The resolution sweep is run similarly:

```bash
python scripts/run_ensembles.py \
  --binary ./build/ot_mhd \
  --config ensembles/resolution_sweep.json
```

The standard sweep runs the three solver variants at `64x64` and `128x128`,
for six total sources.

Use `--dry-run` to inspect commands without launching simulations. Each run
directory contains `output.bp` and `input_parameters.txt`.

The primary ADIOS dataset contains fields including:

- `rho` and `pressure`
- `vx`, `vy`, and `vz`
- `bx`, `by`, and `bz`
- `speed` and `current_z`
- scalar diagnostics such as `time`, energy totals, and divergence measures

Optional command-line arguments can also write `psi`, momentum components, and
total energy density. A run can prepend a code-specific string to every ADIOS
variable name; the data remains self-describing.

The default Make workflow runs `ensembles/simple.json` and writes into
`./runs`:

```bash
make runs
```

## Create a campaign

Register the primary output from every run:

```bash
python scripts/add_adios_files_to_campaign.py \
  ./runs \
  --archive mhd.aca \
  --recreate \
  --showInfo
```

The ingest script embeds `schemas/mhd_orszag_tang.yaml` and immediately calls
`Manager.validate_schema()`. The schema describes an append-mode `output.bp`
inside each run directory and declares `time` as the physical time variable.
ADIOS remains the authoritative description of variables inside the file.

Schema validation is metadata-only. Additional analysis, statistics, images,
and text datasets are allowed in each run. After validating the layout, the
script authors the campaign's W3C PROV document: simulation runs, logical
variables, software agents, Plans, and exact generation/derivation relations.

To write a reviewable PROV-JSON copy beside the campaign, add:

```bash
--exportProv ./mhd.prov.json
```

The Make target recreates the archive and also generates/registers derived
fields and statistics:

```bash
make create
```

## Add derived fields and statistics

Create `analysis.bp` containing `grad_rho_abs`, `grad_pressure_abs`, and
`div_b`, then register it with the source datasets:

```bash
python scripts/add_adios_files_to_campaign.py \
  ./runs \
  --archive mhd.aca \
  --withDerived \
  --recreate
```

Add per-step min, max, mean, median, standard deviation, and variance datasets:

```bash
python scripts/add_adios_files_to_campaign.py \
  ./runs \
  --archive mhd.aca \
  --withDerived \
  --withStats \
  --recreate \
  --showInfo
```

Existing derived and statistics datasets are reused. Use `--forceDerived` or
`--forceStats` to regenerate them.

## Render visualizations

There are two visualization payload styles:

- PNG image sequences, created by
  `scripts/render_adios_visualizations_to_campaign.py`.
- Raw `SCALAR_FIELD` sequences, created by
  `scripts/add_scalar_fields_to_campaign.py`.

Both are registered with explicit visualization metadata and W3C PROV
lineage. Seurat can use the campaign schema to attach physical time values from
the source `time` variable to these frame sequences.

Render selected primary fields from every primary dataset and store PNG images
in the campaign:

```bash
python scripts/render_adios_visualizations_to_campaign.py \
  --archive mhd.aca \
  --datasetPattern '*/output.bp' \
  --variable pressure,rho,speed,current_z \
  --data_root ./runs \
  --allSteps \
  --replace
```

Render derived fields from every `analysis.bp` dataset:

```bash
python scripts/render_adios_visualizations_to_campaign.py \
  --archive mhd.aca \
  --datasetPattern '*/analysis.bp' \
  --variable div_b,grad_pressure_abs,grad_rho_abs \
  --data_root ./runs \
  --allSteps \
  --replace
```

Render velocity and magnetic streamlines:

```bash
python scripts/render_adios_visualizations_to_campaign.py \
  --archive mhd.aca \
  --datasetPattern '*/output.bp' \
  --variable velocity,magnetic \
  --visType streamlines \
  --data_root ./runs \
  --allSteps \
  --replace
```

Store selected 2D fields as raw `SCALAR_FIELD` visualization sequences:

```bash
python scripts/add_scalar_fields_to_campaign.py \
  --archive mhd.aca \
  --datasetPattern '*/output.bp' \
  --variable pressure,rho,speed,current_z \
  --data_root ./runs \
  --allSteps \
  --dtype float32 \
  --replace
```

Store derived 2D fields as raw `SCALAR_FIELD` sequences:

```bash
python scripts/add_scalar_fields_to_campaign.py \
  --archive mhd.aca \
  --datasetPattern '*/analysis.bp' \
  --variable div_b,grad_pressure_abs,grad_rho_abs \
  --data_root ./runs \
  --allSteps \
  --dtype float32 \
  --replace
```

Equivalent Make targets:

```bash
make heatmaps
make streamlines
make scalar-fields
make visualizations
```

The rendering script uses `Manager.visualization()` to register explicit image
items, source variables, semantic roles, a thumbnail, and rendering metadata.
It also records one Visualization Activity per sequence. The output logical
variable points to an embedded sequence manifest, and qualified PROV
derivations identify every field used for geometry, color, or contours. The
scalar-field script follows the same pattern, but sequence items are
`SCALAR_FIELD` datasets rather than PNG images.

Each invocation also creates one configured workflow Plan shared by all of its
Visualization Activities. The Plan records the dataset and variable selection,
step selection, rendering or storage parameters, and replacement policy. Its
location is an immutable GitHub script URL when the local script matches a
commit known through `origin`; otherwise it is the embedded campaign-local
script path. Derived-variable and statistics processing use the same workflow
Plan convention.

## Run the tests

```bash
python -m pytest -q
python -m ruff check .
```

The tests validate the schema against a two-run campaign and exercise the
scientific-name resolution, multiple-input derived calculation, statistics,
simulation generation, exact derivation parents, and visualization provenance.
Generated campaigns and simulation products are ignored by Git.
