# InvaRadar

[![CI](https://github.com/KonkovDV/InvaRadar/actions/workflows/ci.yml/badge.svg)](https://github.com/KonkovDV/InvaRadar/actions/workflows/ci.yml)
[![Code: Apache-2.0](https://img.shields.io/badge/code-Apache--2.0-2F6B55)](LICENSE)
[![Data: CC BY 4.0](https://img.shields.io/badge/data-CC%20BY%204.0-E0A030)](LICENSE-DATA.md)

Repository: [KonkovDV/InvaRadar](https://github.com/KonkovDV/InvaRadar). Map: [konkovdv.github.io/InvaRadar](https://konkovdv.github.io/InvaRadar/). [По-русски](README.md).

InvaRadar finds giant hogweed (*Heracleum sosnowskyi*) and invasive goldenrods (*Solidago canadensis*, *S. gigantea*) from satellite data and turns the map into a work order: where the stand is, which control method the law allows there, and in which order a crew should visit. A repeat image checks the result and becomes the next season's label.

Prepared for the Moscow Ecology Award 2026, category "Digitalisation of environmental solutions". Konkov D. V. ([@KonkovDV](https://github.com/KonkovDV)).

## Results for Moscow (4,225 km², 10 m, 42.25 M pixels)

| | Hogweed | Goldenrod |
|---|---|---|
| Reports in the top 10 % of the map, 5 km spatial blocks | **25.0 %** (95 % CI 20.7–28.8), 2.5× random search | **32.5 %** (28.4–35.9), 3.3× |
| Reports in the top 1 % of the map | 2.5 % | **7.1 %**, 7× |
| New 2025–26 reports in the top 20 %, model trained on data up to 2024 | 38.4 % (n = 383) | 45.7 % (n = 346) |
| Hotspots / within 300 m of schools, kindergartens and playgrounds | 16,056 / 4,309 | 22,252 / 6,995 |
| Drone spraying allowed / ground spot treatment / mechanical only | 168 / 10,367 / 5,521 | 171 / 14,675 / 7,406 |

Citizen photos against look-alikes: hogweed precision 86.7 % at 86.5 % recall, goldenrod 88.7 % and 88.7 %. At confidence 0.9 and above the model closes 68 % of reports itself, and 93.8 % of those calls name the right species.

UAV module on 263 aerial photos from the Moscow region (open Skoltech set, three cameras, the test camera kept out of training): ROC AUC 0.948. At the scouting threshold, max F2 taken from the other cameras, Dice is 0.71 and hogweed shows up on 216 of 251 frames (`make drone`, `docs/EXPERIMENTS.md`).

## Method

- **Features (265 per pixel):** AlphaEarth Foundations embeddings of the pixel and its 50, 150 and 450 m neighbourhoods; log distances to roads, railways, water and power lines; terrain hydrology — Priority-Flood depression filling (Barnes et al. 2014), D8 flow accumulation, TWI and HAND (Rennó et al. 2008).
- **Model:** LightGBM with target-group background (Phillips et al. 2009), validated with 5 km spatial blocks and a forward-in-time test; cluster-bootstrap confidence intervals; area of applicability (Meyer & Pebesma 2021); stratified field-validation design (Olofsson et al. 2014).
- **Rust core:** mosaicking, features, terrain, GBDT inference bit-compatible with LightGBM (max |Δ| = 8.9e-16), hotspots, routes, sampling — a city-wide map in about 2 minutes on 4 vCPUs.
- **Law in code:** water protection zones by river length with no pesticides inside them (Water Code of the Russian Federation, art. 65, part 15, items 3 and 6); ground treatment only inside settlements and at least 700 m between drone spraying and settlements, water bodies and protected areas (sanitary rules СанПиН 2.1.3684-21, items 273 and 282 as amended on 12.02.2026); no pesticides on the grounds of schools and kindergartens; mechanical methods in protected areas; no digging near heritage sites.
- **UAV module:** frozen DINOv2 ViT-S/14 (Apache-2.0) patch features with 3×3 context and a linear probe, leave-one-camera-out validation; bloom index for flowering stands.
- **Tests:** 6 Rust and 28 Python tests, including 12 legal invariants on the published top-200 work orders and the web map.
- **Outputs in git:** metrics, queues, the top 200 work orders, the dissimilarity index, figures, and a web map of 3,000 hotspots. Wall-to-wall 10 m COGs and the full GeoParquet are produced by `make release` into `dist/release/` and are not committed.

## Quick start

```bash
git clone https://github.com/KonkovDV/InvaRadar && cd InvaRadar
pip install -e ".[dev]"
make core test
make all
```

Code: Apache-2.0. Outputs: CC BY 4.0. "The AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google DeepMind."
