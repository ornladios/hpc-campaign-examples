PYTHON ?= python
CONFIG ?= ensembles/simple.json
RUN_ROOT ?= $(CURDIR)/runs
MOVIE_OUTPUT_DIR ?= $(RUN_ROOT)/movies
ARCHIVE ?= /Users/dpn/ORNL_Dropbox/campaign-store/mhd_orszag_tang_runs_full.aca
BUILD_DIR ?= build
PRIMARY_VARS ?= pressure,rho,speed,current_z
DERIVED_VARS ?= div_b,grad_pressure_abs,grad_rho_abs
STREAMLINE_VARS ?= velocity,magnetic
SCALAR_PRIMARY_VARS ?= pressure,rho,speed,current_z
SCALAR_DERIVED_VARS ?= div_b,grad_pressure_abs,grad_rho_abs
SCALAR_FIELD_DTYPE ?= float32
SCALAR_FIELD_DTYPE_ARG = $(if $(SCALAR_FIELD_DTYPE),--dtype $(SCALAR_FIELD_DTYPE),)

.PHONY: all env build runs create visualizations movies heatmaps primary-heatmaps derived-heatmaps streamlines scalar-fields scalar-primary-fields scalar-derived-fields vis-pressure vis-streamlines verify

all: runs create visualizations verify

env:
	$(PYTHON) -c "import hpc_campaign.config as c; print(c.__file__, c.ACA_VERSION)"
	$(PYTHON) -c "import adios2, matplotlib; print('adios2', adios2.__version__)"

build:
	cmake -S . -B $(BUILD_DIR) -DOT_ENABLE_MPI=OFF
	cmake --build $(BUILD_DIR) -j

runs: build
	$(PYTHON) scripts/run_ensembles.py \
		--binary ./$(BUILD_DIR)/ot_mhd \
		--config $(CONFIG) \
		--output-dir $(RUN_ROOT)

create:
	$(PYTHON) scripts/add_adios_files_to_campaign.py \
		$(RUN_ROOT) \
		--archive $(ARCHIVE) \
		--withDerived \
		--withStats \
		--forceDerived \
		--forceStats \
		--recreate \
		--showInfo

visualizations: movies heatmaps streamlines scalar-fields

movies:
	$(PYTHON) scripts/render_adios_visualizations_to_campaign.py \
		--archive $(ARCHIVE) \
		--datasetPattern '*/output.bp' \
		--variable pressure \
		--data_root $(RUN_ROOT) \
		--allSteps \
		--movie \
		--movieOutputDir $(MOVIE_OUTPUT_DIR) \
		--replace \
		--showInfo

heatmaps: primary-heatmaps derived-heatmaps

primary-heatmaps:
	$(PYTHON) scripts/render_adios_visualizations_to_campaign.py \
		--archive $(ARCHIVE) \
		--datasetPattern '*/output.bp' \
		--variable $(PRIMARY_VARS) \
		--data_root $(RUN_ROOT) \
		--allSteps \
		--replace \
		--showInfo

derived-heatmaps:
	$(PYTHON) scripts/render_adios_visualizations_to_campaign.py \
		--archive $(ARCHIVE) \
		--datasetPattern '*/analysis.bp' \
		--variable $(DERIVED_VARS) \
		--data_root $(RUN_ROOT) \
		--allSteps \
		--replace \
		--showInfo

vis-pressure:
	$(PYTHON) scripts/render_adios_visualizations_to_campaign.py \
		--archive $(ARCHIVE) \
		--datasetPattern '*/output.bp' \
		--variable pressure \
		--data_root $(RUN_ROOT) \
		--allSteps \
		--replace \
		--showInfo

streamlines:
	$(PYTHON) scripts/render_adios_visualizations_to_campaign.py \
		--archive $(ARCHIVE) \
		--datasetPattern '*/output.bp' \
		--variable $(STREAMLINE_VARS) \
		--visType streamlines \
		--data_root $(RUN_ROOT) \
		--allSteps \
		--replace \
		--showInfo

vis-streamlines: streamlines

scalar-fields: scalar-primary-fields scalar-derived-fields

scalar-primary-fields:
	$(PYTHON) scripts/add_scalar_fields_to_campaign.py \
		--archive $(ARCHIVE) \
		--datasetPattern '*/output.bp' \
		--variable $(SCALAR_PRIMARY_VARS) \
		--data_root $(RUN_ROOT) \
		--allSteps \
		$(SCALAR_FIELD_DTYPE_ARG) \
		--replace \
		--showInfo

scalar-derived-fields:
	$(PYTHON) scripts/add_scalar_fields_to_campaign.py \
		--archive $(ARCHIVE) \
		--datasetPattern '*/analysis.bp' \
		--variable $(SCALAR_DERIVED_VARS) \
		--data_root $(RUN_ROOT) \
		--allSteps \
		$(SCALAR_FIELD_DTYPE_ARG) \
		--replace \
		--showInfo

verify:
	sqlite3 $(ARCHIVE) "select * from info;"
