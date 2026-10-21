# Video Support Handoff

This document summarizes video support in the campaign examples and the
campaign API version it requires.

## Checkouts and branches

- Campaign library: `/Users/dpn/proj/hpc_campaign/hpc-campaign`, branch
  `provenance-api-redo` (PR #107, commit `620b91a`, including the first-call
  atomicity fix).
- Examples: `/Users/dpn/proj/hpc_campaign/hpc-campaign-examples`, branch
  `provenance-api-redo`, based on the video example branch `add_videos`.

The campaign checkout has unrelated pre-existing untracked files. Preserve
them while continuing this work.

## Campaign API and data model

`Manager.video(...)` registers a movie file as a distinct `VIDEO` dataset and
adds it as a typed item in a visualization sequence. A video item is not an
image item; viewers can identify its type as `VIDEO`. If `store=True`, the MP4
bytes are embedded in the ACA.

The public time arguments are mutually exclusive. Each supported mode results
in one physical time value per video frame:

```python
manager.video(
    "movie.mp4",
    name="run/visualizations/pressure_movie.mp4",
    source_dataset="run/output.bp",
    sequence_name="run/visualizations/pressure_movie",
    variables=[{"name": "pressure", "role": "color-by", "source_dataset": "run/output.bp"}],
    vis_type="heatmap",
    time_range=(0.0, 1.0),
    time_unit="s",
    store=True,
)
```

- `time_range=(t_min, t_max)` spreads frame times uniformly from the inclusive
  endpoints. The number of frames is probed with `ffprobe` unless
  `frame_count` is supplied. A one-frame movie requires equal endpoints.
- `time_variable=(dataset_name, variable_name)` with `time_indices=[...]` maps
  each video frame to a zero-based index in the selected campaign time
  variable. For example, `[0, 2, 3]` selects the first, third, and fourth
  physical time values. A string `time_variable="time"` can be used with
  `source_dataset` instead of the tuple.
- `frame_times=[...]` supplies an explicit physical time for every frame.

The item metadata stores `time_mode="physical_time"`, `time_values`,
`time_unit`, `frame_count`, and `time_source`. In the indexed mode,
`time_source` also records the campaign dataset, variable, and indices. The
viewer decides how to present the movie outside its time range and how to
interpolate or hold frames. This API provides the physical-time association
needed to synchronize movies with image sequences.

The ADIOS reader now resolves time variables in raw BP replicas using their
actual variable name and reads across all available ADIOS steps. It also
accepts the dataset-qualified form when present. The source dataset must have
an accessible local replica when using `time_indices`.

## Example workflow

The example renderer accepts `--movie`, `--fps`, `--ffmpeg`, and
`--movieOutputDir`. It renders
the same PNG frames used by image sequences, in the same order, then invokes
FFmpeg to encode an H.264 MP4. It registers a `VIDEO` item with
`time_variable=(dataset.name, "time")` and the exact ADIOS timestep indices
returned by the renderer. Movie mode requires one rendered frame per step.
The current Makefile target uses pressure heatmaps, all steps, and 10 frames
per second. MP4 copies remain under `RUN_ROOT/movies` by default, under
`<sequence-name>/revisions/<uuid>/movie.mp4`; override the output directory
with `MOVIE_OUTPUT_DIR`. Each render uses a fresh revision, so replacing the
visible sequence does not overwrite earlier files or reuse their producer.

```bash
make movies
```

`make visualizations` and `make all` include `movies`. FFmpeg with the
`libx264` encoder is required. The renderer pads odd pixel dimensions so
`yuv420p` encoding works with H.264.

Movie registration also adds a PROV Visualization Activity using the
Entity-first API. The source logical variables are declared with
`Manager.add_variable()` and passed as Activity inputs. The output is the
collection Entity from `Manager.add_visualization_sequence_entity()`, which
captures the ordered VIDEO dataset members. Rendering parameters, selected
steps, and sequence name are stored in Activity `metadata=`; the rendering
script is associated as a Plan. Image sequences use the same collection
pattern. Raw scalar-field sequences instead generate their registered
per-frame dataset Entities because the campaign collection API supports only
image and video sequences.

### Video variable roles

The renderer converts semantic kwargs to the variable specifications expected
by `Manager.video(variables=...)`. For example, `{"color_by": "pressure"}`
becomes:

```python
variables=[{"name": "pressure", "role": "color-by", "source_dataset": dataset.name}]
```

For streamlines, `streamline_by` tuple members become `streamline-x` and
`streamline-y` entries, and an optional `color_by` becomes a `color-by` entry.
The integration test asserts the sequence variable names and roles, VIDEO item
type, per-frame physical times, and time indices.

## ACA visibility and standalone files

The MP4 payload is stored as an embedded file associated with a `VIDEO`
dataset. It is not represented as an ADIOS array variable, so `bpls` does not
list the movie payload among the ACA variables. Use campaign metadata to
discover video datasets and sequence associations:

```bash
hpc_campaign manager /path/to/campaign.aca info
```

The `info` output lists dataset paths ending in `.mp4`, identifies them as
`VIDEO`, and shows the visualization sequence item reference. The
`--list-files` option shows embedded file records. Campaign's embedded replica
may still record a local path. The example's separate MP4 copy is the durable,
user-selected output; the library API does not provide a public export
operation for embedded video payloads.

The current local archive is
`/Users/dpn/ORNL_Dropbox/campaign-store/mhd_orszag_tang_runs_full.aca`. Three
standalone copies were extracted and verified under
`/Users/dpn/ORNL_Dropbox/campaign-store/mhd_orszag_tang_runs_full_movies/`:

- `hll_first_order_pressure_heatmap.mp4` (35 frames)
- `muscl_hll_pressure_heatmap.mp4` (42 frames)
- `rusanov_first_order_pressure_heatmap.mp4` (30 frames)

These are runtime artifacts, not files tracked in the examples repository.

## Dependencies and validation

The examples `pyproject.toml` pins the campaign dependency to the
`provenance-api-redo` branch. That branch contains the Entity-first
provenance API and `Manager.video()` used by the examples. For local development,
installing a campaign checkout after this project makes the checkout's
editable package take precedence.

Validation for the provenance API migration:

- Ruff checks: passed for tracked example code and the new verification files.
- Examples full test suite against the campaign checkout with the review fixes:
  `31 passed, 4 subtests passed`. This covers simulation, derived products,
  image/video collections, scalar-field outputs, video time metadata, final
  schema validation, relative/absolute Makefile build paths, and repeated
  image, external PNG, movie, and scalar-field rendering. Rerender tests verify
  that earlier payloads and producer links are preserved.
- A clean installation from the examples dependency declaration resolved
  campaign commit `8628bc3`. The review fixes are additionally installed as a
  local wheel in that disposable environment, and the tests and workflow run
  without a local campaign checkout on `PYTHONPATH`.
- A disposable full `make all` run uses all three solvers on 16x16 grids,
  serial execution, and two stored timesteps. It produces 3 VIDEO sequences,
  27 IMAGE sequences, and 21 SCALAR_FIELD sequences. All 72 visualization
  outputs trace to a simulation, and `ffprobe` verifies each standalone MP4
  has two H.264 frames matching the stored physical times `[0.0, 0.02]`.
- Running `make visualizations verify` again on that archive succeeds. The
  visible sequence count stays at 51, with 102 Visualization Activities
  recording the two executions. All 99 earlier embedded media payloads and
  618 Generation links are preserved, as are the first three standalone
  movies. All six MP4 revisions pass `ffprobe`, and the 72 current output
  Entities trace to the correct simulation.
- This is a small compatibility check. The default 128x128 ensemble, MPI
  execution, and interactive viewer playback were not rerun for this change.

Shared script Plans are stored once as root-level
`__provenance_plan_<script-name>` datasets. This prevents them from being
interpreted as another simulation directory by the layout schema. Ingestion
validates the schema after provenance registration; `make verify` validates
the final layout and loads the active provenance document with its hash check.

## Suggested next checks

1. Inspect `hpc_campaign manager <archive> info` and movie playback in the
   campaign viewer.
2. Confirm behavior when time-variable replicas are remote or archived and no
   local replica is available.
