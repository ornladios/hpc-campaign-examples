# Video Support Handoff

This document summarizes video support in the campaign examples and the
campaign API version it requires.

## Checkouts and branches

- Campaign library: `/Users/dpn/proj/hpc_campaign/hpc-campaign`, current
  checkout branch `provenance-api-redo`; the video API used for validation is
  commit `7de6241` on `add_video`.
- Examples: `/Users/dpn/proj/hpc_campaign/hpc-campaign-examples`, branch
  `add_videos`.

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
per second. MP4 copies remain under `RUN_ROOT/movies` by default, preserving
the sequence path; override this with `MOVIE_OUTPUT_DIR`.

```bash
make movies
```

`make visualizations` and `make all` include `movies`. FFmpeg with the
`libx264` encoder is required. The renderer pads odd pixel dimensions so
`yuv420p` encoding works with H.264.

Movie registration also adds a PROV visualization Activity. The Activity
links the source logical variables to an output named `video`; its rendering
parameters include the timestep list, frame rate, and encoder. The sequence
manifest records each item type, dataset name, UUID, and ordering. The
provenance recorder defaults to the existing `image_sequence` output name for
non-video visualizations, preserving their current behavior.

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

The examples `pyproject.toml` pins the campaign dependency to `master`, as
requested. As of October 15, 2026, remote `master` does not export
`VariableSpec` or provide `Manager.video()`. The current provenance and movie
examples therefore need a campaign checkout with both APIs installed after
the examples package until the relevant campaign changes are merged. If the
provenance API is present but `Manager.video()` is missing, the renderer exits
with a direct movie API requirement message.

Validation performed during this work:

- Ruff checks: passed for the whole examples repository.
- Examples full test suite against campaign commit `7de6241`: `21 passed`,
  including `test_example_helpers.py` and `test_mhd_provenance.py`.
- Campaign video tests: `4 passed` (`tests/test_video.py`).
- `make movies` against a disposable copy of the ACA completed and added three
  videos with 35, 42, and 30 frames, plus per-video provenance records. MP4s
  were retained under the temporary `MOVIE_OUTPUT_DIR` used for validation.
- A disposable ACA smoke check registered an MP4 against a real example BP
  dataset. The resulting `VIDEO` item had 35 per-frame physical times from
  0.0 to 1.0 seconds.
- The three videos in the current ACA were extracted, checksum-checked, and
  inspected with `ffprobe`.

## Suggested next checks

1. Merge campaign video support to `master`, then verify a clean Poetry install
   resolves `Manager.video()` from the pinned dependency.
2. Inspect `hpc_campaign manager <archive> info` and movie playback in the
   campaign viewer.
3. Confirm behavior when time-variable replicas are remote or archived and no
   local replica is available.
