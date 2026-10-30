# InvaRadar — one command per stage. `make all` reproduces every number in outputs/ and in the deck.
PY ?= python3
CORE := core-rs/target/release/invaradar_core

.PHONY: all core test lint data heracleum solidago variants enrich requeue uncertainty figures drone deck release clean

all: core data heracleum solidago variants enrich uncertainty figures

core:
	cd core-rs && cargo build --release

test: core
	cd core-rs && cargo test --release
	$(PY) -m pytest

lint:
	ruff check .
	cd core-rs && cargo fmt --check && cargo clippy --release --all-targets -- -D warnings

data:
	$(PY) scripts/fetch_aef_index.py
	$(PY) scripts/fetch_inat.py obs
	$(PY) scripts/prefetch_aef.py 2025
	$(PY) scripts/fetch_overture.py
	$(PY) scripts/fetch_dem.py
	$(PY) scripts/prep_dem.py

heracleum: core
	$(PY) scripts/pipeline.py heracleum

solidago: core
	$(PY) scripts/pipeline.py solidago --no-terrain

variants: core
	$(PY) scripts/pipeline.py heracleum --no-terrain --variant no_terrain
	$(PY) scripts/pipeline.py solidago --variant terrain

enrich:
	$(PY) scripts/enrich.py heracleum
	$(PY) scripts/enrich.py solidago
	$(PY) scripts/prescribe.py heracleum
	$(PY) scripts/prescribe.py solidago
	$(PY) scripts/exp_labels.py heracleum

# after a change of context layers, priority or legal rules: rebuild queues and work orders without retraining
requeue: core
	$(PY) scripts/requeue.py heracleum
	$(PY) scripts/requeue.py solidago
	$(PY) scripts/prescribe.py heracleum
	$(PY) scripts/prescribe.py solidago
	$(PY) scripts/render_maps.py heracleum

uncertainty:
	$(PY) scripts/uncertainty.py heracleum
	$(PY) scripts/uncertainty.py solidago

figures:
	$(PY) scripts/render_maps.py heracleum
	$(PY) scripts/render_figures.py

# UAV module on real aerial photos (open Heracleum dataset, Moscow region): DINOv2 + linear probe, leave-one-camera-out
# git clone https://github.com/DLopatkin/Heracleum-Dataset ../Heracleum-Dataset && pip install -e ".[drone]"
HERACLEUM_DATASET ?= ../Heracleum-Dataset
drone:
	$(PY) scripts/drone_benchmark.py $(HERACLEUM_DATASET)

# both decks: the 10-page A4 submission (Положение о премии) and the full 27-slide version; PDFs via LibreOffice
deck:
	cd presentation && npm ci && $(PY) prepare_assets.py \
	  && node build_submission.js assets InvaRadar_Ecopremia2026_podacha.pptx \
	  && node build_deck.js assets InvaRadar_Ecopremia2026.pptx \
	  && soffice --headless --convert-to pdf InvaRadar_Ecopremia2026_podacha.pptx InvaRadar_Ecopremia2026.pptx \
	  && $(PY) export_notes.py InvaRadar_Ecopremia2026.pptx SPEAKER_NOTES.md

release:
	$(PY) scripts/make_release.py

clean:
	rm -rf outputs/*/tmp outputs/variants/*/tmp
