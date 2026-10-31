# Карточка данных: результаты ИнваРадара

Все файлы — под CC BY 4.0 с указанием первоисточников из [NOTICE](../NOTICE). Сплошные карты 10 м и GeoParquet всех очагов собирает `make release` в `dist/release/` (каталог STAC 1.1 и `SHA256SUMS` рядом). В git их нет: см. `.gitignore`. Индекс несходства, очереди, 200 нарядов и веб-карта лежат в репозитории.

## Растры

| Файл | Содержание | Формат |
|---|---|---|
| `invaradar_<вид>_likelihood_2025_10m_cog.tif` | процентиль ландшафта × 250 (0–250), 255 — нет данных; 6500 × 6500 пикселей, 10 м, EPSG:32637 | Cloud Optimized GeoTIFF, ZSTD, обзоры 2–16 |
| `invaradar_<вид>_dissimilarity_index_100m.tif` | индекс несходства для области применимости; порог в теге `aoa_threshold` | GeoTIFF, 100 м |
| `invaradar_variant_*_likelihood_2025_10m_cog.tif` | варианты для абляции рельефа | COG |

## Очаги

`invaradar_<вид>_hotspots_prescribed_2025.parquet` (GeoParquet, EPSG:4326; то же в GeoJSON). Одна строка — связная область (8-связность) пикселей с ландшафтным процентилем ≥ 0,98 размером от 400 м². Процентиль хранится с шагом 0,004 и округляется, поэтому порог фактически 0,978 и очаги покрывают около 2,2% площади.

| Поле | Смысл |
|---|---|
| `rank`, `priority` | место в очереди и балл: 100 × средний процентиль очага × (0,4 + 0,6 · экспозиция) × (0,6 + 0,4 · распространение) × (0,5 + 0,5 · размер). Это не вероятность присутствия |
| `mean_rank`, `max_rank` | средний и максимальный процентиль внутри очага |
| `area_m2`, `lat`, `lon` | площадь и точка внутри очага |
| `d_child_m`, `d_sensitive_m`, `d_road_m`, `d_rail_m`, `d_water_m`, `d_power_m` | расстояния до детских и социальных объектов, дорог, железных дорог, воды, ЛЭП |
| `exposure`, `spread`, `size_f` | множители приоритета |
| `dissimilarity`, `inside_aoa` | индекс несходства и признак области применимости |
| `water_zone_m`, `in_water_zone` | ширина водоохранной зоны по ВК РФ ст. 65 (50 / 100 / 200 м) и попадание в неё |
| `in_protected`, `child_org_territory`, `near_children`, `near_heritage` | ООПТ и парки; территория школы или детского сада; дети в 100 м; памятник в 50 м |
| `in_settlement`, `near_settlement_uav`, `near_reserve_or_water_uav` | очаг в населённом пункте; ближе 700 м к жилью; ближе 700 м к ООПТ или водоёму (СанПиН п. 282 для беспилотников) |
| `method`, `legal_basis`, `follow_up_years` | рецепт работ, основание и срок наблюдения |

## Таблицы в репозитории (`outputs/<вид>/`)

| Файл | Содержание |
|---|---|
| `metrics.json` | метрики пространственной проверки и теста во времени, важность признаков, сводка очагов |
| `uncertainty.json` | 95% доверительные интервалы метрик и подъём над случайным обходом |
| `enrich_summary.json` | область применимости, сводка предписаний, дизайн полевой выборки |
| `survey_queue_2025.csv` | очередь обследования со всеми расстояниями |
| `work_orders_top200_2025.csv` | 200 первых нарядов с методом и основанием |
| `validation_sample.csv`, `.geojson` | 250 точек стратифицированной полевой выборки |
| `route_top25_2025.geojson`, `route_district_2025.geojson` | маршруты обследования |
| `exp_labels.json` | эксперимент с устойчивыми очагами (борщевик) |
| `outputs/photo/metrics.json` | качество классификатора фото |
| `outputs/drone/benchmark.json`, `dinov2s_probe.joblib` | проверка модуля БПЛА на реальных аэрофото и обученный классификатор |

## Происхождение

AlphaEarth Foundations 2025 (Google DeepMind), наблюдения iNaturalist (экспорт open data, октябрь 2026), Overture Maps release 2026-10-21.0, Copernicus DEM GLO-30. Обработка — код этого репозитория, версия 1.2.0.

## Как читать растр

```python
import geopandas as gpd, rasterio
with rasterio.open("dist/release/invaradar_heracleum_likelihood_2025_10m_cog.tif") as ds:
    window = ds.read(1, window=((3000, 3512), (3000, 3512)))   # читает только нужные тайлы
hot = gpd.read_parquet("dist/release/invaradar_heracleum_hotspots_prescribed_2025.parquet")
```
