# Связь с InvaRadar

## Источник

- Репозиторий: https://github.com/KonkovDV/InvaRadar
- Проверенный коммит: `cdf3b95` («Share one forest between the map and the intervals, and recompute the label experiment with the map's L2»).
- Версия: 1.2.0, код — Apache-2.0, данные — CC BY 4.0.
- Снимок исходников без тяжёлых выходных данных: `upstream/InvaRadar-cdf3b95-src.zip`.

Клонировать полностью:

```bash
git clone https://github.com/KonkovDV/InvaRadar.git
```

```bash
git -C InvaRadar checkout cdf3b95
```

## Что проверено 07.11.2026

- **Python.** `pytest` в чистом окружении: все тесты прошли, 3 пропущены (нужны собранная программа ядра и полная таблица, которой нет в git).
- **Rust.** `cargo test --release` в `core-rs`: 9 из 9. Это снимок коммита `cdf3b95`, не текущее дерево.

## Что проверено 13.11.2026

- На `main` коммит `aad21d5`. Локальный `pytest` прошёл. Пропуски: полная таблица, которой нет в git, и тест, которому нужен fastapi.
- В `core-rs` 11 тестов. Замер полосы помечен `ignore`, CI его не запускает.
- https://konkovdv.github.io/InvaRadar/ отдаёт MapLibre GL JS 6.18.0 из `web/vendor/` и стиль OpenFreeMap. Растровых тайлов `tile.openstreetmap.org` на странице нет.

## Что Pro берёт из InvaRadar

| Файл InvaRadar | Куда в Pro | Поля |
|---|---|---|
| `outputs/<вид>/work_orders_top200_2025.csv` | `data/sample/<вид>_work_orders_top200_2025.csv` → `upstream.read_work_orders` | `rank`, `priority`, `lat`, `lon`, `area_m2`, `mean_rank`, `inside_aoa`, `water_zone_m`, `in_protected`, `child_org_territory`, `near_children`, `d_child_m`, `near_heritage`, `in_settlement`, `in_zso`, `jurisdiction`, `method`, `legal_basis` |
| `outputs/heracleum/validation_sample.csv` | `data/sample/heracleum_validation_sample.csv` → `sampling` | `stratum`, `x`, `y`, `stratum_px` |
| `outputs/<вид>/survey_queue_2025.csv` (полная очередь, 16 352 и 19 716 строк) | Тем же `read_work_orders` после добавления флагов закона | Колонки очереди без флагов закона: нужен прогон `make requeue` и `scripts/prescribe.py` |
| `outputs/photo/verifier.joblib` | Бот жителей (план) | Классификатор фото на 4 класса |

## Что уже исправлено в этом репозитории

1. **B-01, B-02, B-04.** В наряде подрезка 10–15 см, у крупных растений до 20 см. Срезанные зонтики уничтожают, грунт с очага не вывозят, технику чистят на участке. Тексты топ-200 и веб-карты приведены к рецепту. Ранги прогона 6 ноября не пересчитывались.
2. **I-03.** `scripts/photo_dataset.py` оставляет только CC0 и CC BY.
3. **A-05.** `boundaries/jurisdictions.geojson` и `invaradar/jurisdictions.py`. В топ-200 юрисдикция заполнена: борщевик 93 города и 107 области, золотарник 79 и 121. 369-ПП пишется только для города.
4. **A-02.** `scripts/pipeline.py --embedding-year` отделяет год эмбеддинга от года карты. Опубликованный прогон остаётся разрезом на одном снимке 2025 года. Пиксельный ретро-прогноз — в `analysis/results/TABLES.md`. Прогон на 265 признаках с эмбеддингом 2024 года записан в `outputs/variants/heracleum_retro2024/` и `outputs/variants/solidago_retro2024/`: 33,8% и 34,6% новых мест в верхних 20%. Ранги 6 ноября не заменены.

## Ретро-прогноз A-02: что уже посчитано в Pro и как сделать полную версию в InvaRadar

- **Сделано в Pro** (`analysis/realdata/retro_forecast.py`, разведочная версия 1a).
  - Данные: находки iNaturalist (исследовательский уровень, точность ≤ 50 м, открытая геоприватность) и эмбеддинги AlphaEarth 2023, 2024 и 2025 годов, прочитанные прямо из публичных COG.
  - Признаки: только пиксельные (64).
  - Обучение — на находках до 2024 года, проверка — на новых местах 2025–2026 годов.
  - Итоги — в научном отчёте, §5.8.
- **Полная версия на 265 признаках посчитана.** Она лежит в `outputs/variants/heracleum_retro2024/` и `outputs/variants/solidago_retro2024/`. Признаки — эмбеддинг 2024 года, обучение временной проверки — на метках до 31.12.2024, новые места 2025–2026 годов дальше 500 м. В верхних 20% площади 33,8% (27,8–40,3) и 34,6% (28,2–41,6). Ранги 6 ноября не заменены.
- Парный блочный бутстрэп этого варианта против снимка 2025 года на тех же точках не запускался. Опубликованные 34,7% и 41,5% остаются отдельным прогоном на одном снимке.
