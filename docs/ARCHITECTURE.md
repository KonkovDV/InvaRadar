# Архитектура

```mermaid
flowchart LR
  subgraph Данные
    AEF[AlphaEarth Foundations<br/>эмбеддинги 10 м, COG]
    INAT[iNaturalist<br/>находки и фон]
    OV[Overture Maps<br/>дороги, вода, ЛЭП, застройка, школы]
    DEM[Copernicus DEM GLO-30]
    PH[фото жителей]
  end
  subgraph Rust-ядро
    MOS[мозаика блоков]
    CTX[контекст 50/150/450 м]
    EDT[расстояния до коридоров]
    TER[Priority-Flood → D8 → TWI, HAND]
    INF[инференс GBDT]
    HOT[очаги: связные компоненты]
    RT[маршрут: NN + 2-opt]
    STR[стратифицированная выборка]
  end
  subgraph Python
    TRAIN[LightGBM: шахматка 5 км,<br/>полоса 500 м, год метки]
    PRI[приоритет]
    LAW[правила: ВК РФ, СанПиН, 73-ФЗ]
    AOA[область применимости]
    VER[классификатор фото]
    UAV[библиотека БПЛА:<br/>DINOv2, nDSM, полётное задание<br/>в наряд не пишется]
  end
  AEF --> MOS --> CTX --> INF
  OV --> EDT --> INF
  DEM --> TER --> INF
  INAT --> TRAIN
  CTX --> TRAIN
  TRAIN -->|dump_model| INF
  INF --> HOT --> PRI --> LAW --> WO[наряды, очередь, маршрут]
  HOT --> RT --> WO
  INF --> STR --> VAL[полевая выборка]
  TRAIN --> AOA
  PH --> VER
```

## Почему так

- **Rust для всего, что касается каждого пикселя.** 42,25 млн пикселей × 265 признаков: признаки, рельеф и инференс считаются в одном многопоточном проходе (rayon). Сверка с LightGBM и сама карта — команда `scoremap`: контекст строится один раз. Пять коридоров читаются параллельно, порядок признаков тот же. Карта — около 2 минут на 4 vCPU после того, как мозаика уже в кэше.
- **Один код признаков для обучения и карты.** Точечные признаки и признаки карты считаются одной функцией ядра, а инференс сверяется с LightGBM на 2000 точек при каждом прогоне.
- **Python для статистики и права.** Перекрёстная проверка, интервалы, область применимости, правила обработки и картография — там, где важна читаемость и экосистема (geopandas, scikit-learn, LightGBM).
- **Облачные форматы.** Растры — Cloud Optimized GeoTIFF, векторы — GeoParquet, каталог — STAC 1.1: данные читаются по HTTP частями.

## Модули

| Путь | Назначение |
|---|---|
| `core-rs/src/main.rs` | команды `points`, `predict`, `score`, `scoremap`, `hotspots`, `route`, `strata`; чтение кэша float — одним проходом; 9 модульных тестов |
| `invaradar/aef.py` | индекс тайлов AlphaEarth, кэш блоков 1024 × 1024 × 64, деквантование |
| `invaradar/samples.py` | находки и фон из iNaturalist |
| `invaradar/splits.py` | шахматка 5 км, полоса 500 м только вокруг проверочных находок, разрез по году, индекс Бойса, процентиль ландшафта |
| `invaradar/legal.py` | перечни: 369-ПП только для сверенной юрисдикции, перечень области не подставляет обязанность |
| `invaradar/layers.py` | общие слои: детские объекты и населённые пункты — одни для очереди и для нарядов |
| `invaradar/priority.py` | приоритет очагов |
| `invaradar/queue.py` | кандидаты на осмотр → очередь, порядок обхода по прямой (общий код `pipeline.py` и `requeue.py`) |
| `invaradar/management.py` | водоохранные зоны и рецепты; один классификатор метода для сводки и веб-карты; канава — 50 м, не полоса 700 м |
| `invaradar/survey_protocol.py` | локальный рельеф и порог, снятый с других групп; в 265 признаков карты не входит |
| `invaradar/inat_api.py` | сообщения жителей в окне карты через API iNaturalist, если выгрузки нет на диске |
| `invaradar/drone.py` | библиотека: DINOv2, индекс цветения, TorchScript, фильтр nDSM, полигоны, полётное задание. Пайплайн наряда её не вызывает |
| `scripts/drone_benchmark.py` | проверка модуля БПЛА на 263 реальных аэрофото, камера исключается из обучения |
| `invaradar/style.py` | палитра и шрифты рисунков |
| `scripts/fetch_aef_index.py`, `fetch_inat.py`, `fetch_dem.py`, `fetch_overture.py`, `prefetch_aef.py`, `prep_dem.py` | загрузка и подготовка открытых данных |
| `scripts/pipeline.py` | полный прогон вида |
| `scripts/enrich.py` | область применимости, полевая выборка |
| `scripts/prescribe.py` | наряды: метод работ и правовое основание для каждого очага |
| `scripts/requeue.py` | пересчёт очереди и маршрута из готовых очагов без переобучения; `make requeue` после него пишет наряды и веб-карту |
| `scripts/export_web.py` | веб-карта: верхние очаги и сводка, те же классы методов, что в нарядах |
| `invaradar/model.py` | один лес для карты и для доверительных интервалов |
| `scripts/make_release.py` | ассеты релиза, каталог STAC, SHA256SUMS |
| `scripts/uncertainty.py` | доверительные интервалы; ранги из `oof_rank.f64`, если их записал тот же прогон |
| `scripts/render_maps.py`, `scripts/render_figures.py` | карты и научные рисунки |
| `scripts/train_photo_verifier.py` | классификатор фото |
| `presentation/build_submission.js` | презентация для подачи: 10 страниц A4 по Положению о премии |
| `presentation/build_deck.js` | полная презентация PowerPoint из `outputs/*.json` |
