PY ?= python3
export PYTHONPATH := src

.PHONY: install test demo verify consistency top10 api lawcheck reproduce realdata

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest

demo:
	$(PY) -m invaradar_pro demo --out out_demo

verify:
	$(PY) -m invaradar_pro verify out_demo/events.jsonl

consistency:
	$(PY) -m invaradar_pro consistency --csv data/sample/heracleum_work_orders_top200_2025.csv --taxon heracleum
	$(PY) -m invaradar_pro consistency --csv data/sample/solidago_work_orders_top200_2025.csv --taxon solidago

lawcheck:
	$(PY) -c "import json; from invaradar_pro.law_check import run; r = run(); r.pop('counterexamples', None); print(json.dumps(r, ensure_ascii=False, indent=2))"

top10:
	$(PY) analysis/top10_path.py

# нужна сеть: iNaturalist API и публичные COG AlphaEarth (около 2 ГБ трафика на год признаков); pip install requests zstandard pyproj lightgbm pandas pyarrow
realdata:
	$(PY) analysis/realdata/retro_forecast.py
	$(PY) analysis/evidence_bench.py

reproduce:
	$(PY) analysis/reproduce.py

api:
	uvicorn invaradar_pro.api:app --reload
