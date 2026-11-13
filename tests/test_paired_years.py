"""The committed paired comparison keeps the two images on one set of places."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "outputs" / "variants" / "paired_2025_minus_2024.json"


def test_the_paired_file_compares_2025_with_2024_on_the_same_new_places():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    assert data["protocol"]["difference"].startswith("capture of the 2025")
    assert data["protocol"]["n_boot"] == 2000
    assert data["observation_file"]["bytes"] == 327950715
    for taxon, n in (("heracleum", 216), ("solidago", 188)):
        got = data["taxa"][taxon]
        top = got["paired_2025_minus_2024"]["top20%"]
        assert top["n"] == n
        assert top["boot95"][0] <= top["diff"] <= top["boot95"][1]
        assert abs(top["diff"] - (top["capture_a"] - top["capture_b"])) < 1e-12
        assert all(got["agreement_with_stored_files"].values())
        assert got["columns"]["corridors_identical"] is True
        assert got["columns"]["embeddings_identical"] is False
        assert got["columns"]["nodata_rows_2024"] == 0
        assert got["columns"]["nodata_rows_2025"] == 0
    assert data["taxa"]["heracleum"]["terrain"] is True
    assert data["taxa"]["heracleum"]["columns"]["terrain_all_zero"] is False
    assert data["taxa"]["solidago"]["terrain"] is False
    assert data["taxa"]["solidago"]["columns"]["terrain_all_zero"] is True
