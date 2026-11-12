import hashlib

import numpy as np
from invaradar_pro.eradication import (
    ClosureParams,
    belief_after,
    closure_check,
    optimal_threshold,
    predict,
    update_clean,
)
from invaradar_pro.events import EventLog
from invaradar_pro.merkle import (
    MerkleTree,
    leaf_hash,
    signed_tree_head,
    verify_consistency,
    verify_inclusion,
    verify_tree_head,
)
from invaradar_pro.validation import (
    capture_report,
    nearest_dist,
    new_sites_mask,
    nndm_diagnostic,
    retro_forecast_verdict,
)

# --- Меркл (RFC 9162) ------------------------------------------------------------------------------

def test_rfc_known_values():
    assert MerkleTree().root().hex() == hashlib.sha256(b"").hexdigest()
    assert leaf_hash(b"").hex() == "6e340b9cffb37a989ca544e6bb780a2c78901d3fb33738768511a30617afa01d"


def test_all_inclusion_and_consistency_proofs():
    t = MerkleTree([f"событие {i}".encode() for i in range(33)])
    for n in range(1, 34):
        root = t.root(n)
        for i in range(n):
            pr = t.inclusion_proof(i, n)
            assert verify_inclusion(leaf_hash(f"событие {i}".encode()), i, n, pr, root)
            assert not verify_inclusion(leaf_hash(b"chuzhoe"), i, n, pr, root)
        for m in range(1, n + 1):
            assert verify_consistency(m, n, t.root(m), root, t.consistency_proof(m, n))
            if m < n:
                assert not verify_consistency(m, n, hashlib.sha256(b"x").digest(), root, t.consistency_proof(m, n))


def test_log_rewrite_breaks_consistency(tmp_path):
    log = EventLog()
    actor = {"id": "s", "role": "system", "kind": "system"}
    for i in range(10):
        log.append("c", "x", actor, {"i": i}, at="2027-05-01T10:00:00+00:00")
    t1 = log.merkle()
    old_root = t1.root(6)
    forged = MerkleTree([log.leaf_bytes(i) if i != 3 else b"forged" for i in range(10)])
    assert not verify_consistency(6, 10, old_root, forged.root(), forged.consistency_proof(6))
    assert verify_consistency(6, 10, old_root, t1.root(), t1.consistency_proof(6))
    sth = signed_tree_head(t1, b"demo-key", "2027-05-02T00:00:00Z")
    assert verify_tree_head(sth, b"demo-key") and not verify_tree_head({**sth, "tree_size": 9}, b"demo-key")


# --- байесовское закрытие ----------------------------------------------------------------------

def test_belief_updates():
    assert update_clean(0.5, 0.0) == 0.5 and update_clean(0.5, 1.0) == 0.0
    assert predict(0.0, 0.5, 0.02) == 0.02
    prm = ClosureParams()
    p_crew = belief_after([(2028, "crew", False)], 2027, False, prm)
    p_cit = belief_after([(2028, "citizen", False)], 2027, False, prm)
    assert p_crew < p_cit < prm.p0_no_seed
    assert belief_after([(2028, "crew", True)], 2027, False, prm) == 1.0


def test_three_clean_seasons_close_like_nys_dec():
    prm = ClosureParams()
    hist = [(y, r, False) for y in (2028, 2029, 2030) for r in ("crew", "crew")]
    assert closure_check(hist, 2027, False, prm)["ok"]
    assert not closure_check(hist[:2], 2027, True, prm)["ok"]  # семена осыпались: одного сезона мало


def test_optimal_threshold_monotone_in_escape_cost():
    lo = optimal_threshold(ClosureParams(cost_escape=30_000.0))
    hi = optimal_threshold(ClosureParams(cost_escape=300_000.0))
    assert 0 < hi["p_star"] < lo["p_star"] <= 1
    assert hi["clean_seasons_after_treatment"] >= lo["clean_seasons_after_treatment"]
    seeded = optimal_threshold(ClosureParams(), seeded=True)
    assert seeded["seasons_including_treatment_year"] >= optimal_threshold(ClosureParams())["seasons_including_treatment_year"]


# --- ретро-прогноз и NNDM ------------------------------------------------------------------------

def test_retro_forecast_tools():
    rng = np.random.default_rng(0)
    land = rng.random(20_000)
    good = np.clip(rng.beta(8, 1.2, 400), 0, 1)
    rep = capture_report(good, land, blocks=rng.integers(0, 40, 400), n_boot=300)
    assert rep["top20%"]["capture"] > 0.5 and "сильный" in retro_forecast_verdict(rep)
    bad = capture_report(rng.random(400), land, n_boot=10)
    assert "не подтверждён" in retro_forecast_verdict(bad)
    old = np.array([[0.0, 0.0], [1000.0, 0.0]])
    new = np.array([[100.0, 0.0], [3000.0, 0.0]])
    assert new_sites_mask(new, old, 500.0).tolist() == [False, True]
    assert np.allclose(nearest_dist(new, old), [100.0, 2000.0])


def test_nndm_detects_clustered_cv():
    rng = np.random.default_rng(1)
    train = rng.normal(0, 2000, (300, 2))
    pred = rng.uniform(-20_000, 20_000, (2000, 2))
    clustered_cv = nearest_dist(train[:150] + rng.normal(0, 50, (150, 2)), train[150:])
    d = nndm_diagnostic(pred, train, clustered_cv)
    assert "не похожа" in d["verdict"] and d["pred_median_m"] > d["cv_median_m"]
