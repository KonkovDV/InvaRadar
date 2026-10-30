# syntax=docker/dockerfile:1.7
# Reproducible environment: Rust core + Python pipeline. Data is mounted at /work/data and /work/cache.
FROM rust:1.86-slim-bookworm AS core
WORKDIR /src/core-rs
COPY core-rs/ .
ENV RUSTFLAGS="-C target-cpu=x86-64-v3"
RUN rm -f .cargo/config.toml && cargo build --release

FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /work
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY invaradar/ invaradar/
RUN uv pip install --system -e .
COPY scripts/ scripts/
COPY tests/ tests/
COPY --from=core /src/core-rs/target/release/invaradar_core core-rs/target/release/invaradar_core
ENV INVARADAR_DATA=/work/data INVARADAR_CACHE=/work/cache INVARADAR_OUT=/work/outputs
CMD ["python", "scripts/pipeline.py", "heracleum"]
