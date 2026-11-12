import json

import numpy as np
from invaradar_pro.events import EventLog

# --- журнал ----------------------------------------------------------------------------------------

def test_chain_detects_tampering(tmp_path):
    p = tmp_path / "log.jsonl"
    log = EventLog(p)
    for i in range(5):
        log.append(f"c{i % 2}", "signal_received", {"id": "m", "role": "model", "kind": "system"},
                   {"i": i, "t": (1, 2)}, at=f"2027-05-0{i + 1}T10:00:00+00:00")
    assert log.verify() == (True, None)
    assert EventLog(p).verify() == (True, None)
    assert EventLog(p).events("c0")[0].payload["t"] == [1, 2]
    lines = p.read_text(encoding="utf-8").splitlines()
    ev = json.loads(lines[2])
    ev["payload"]["i"] = 99
    lines[2] = json.dumps(ev, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert EventLog(p).verify() == (False, 2)


# --- право -----------------------------------------------------------------------------------------

PEST = {"ground_herbicide_spot", "ground_herbicide_boom", "aerial_uav_herbicide"}


def test_water_zone_bans_pesticides_with_citation(engine, safe_ctx):
    d = engine.decide({**safe_ctx, "water_zone_m": 100.0})
    assert PEST <= set(d.prohibited)
    assert all("vk65-water-zone" in d.prohibited[m] for m in PEST)
    assert any(c["rule"] == "vk65-water-zone" and c["verified"] for c in d.citations)


def test_settlement_bans_uav_and_adds_time_window(engine, safe_ctx):
    d = engine.decide({**safe_ctx, "in_settlement": True})
    assert "aerial_uav_herbicide" in d.prohibited
    assert "ground_herbicide_spot" in d.allowed
    reqs = engine.requirements_for(d, "ground_herbicide_spot")
    assert any("22:00" in r for r in reqs) and any("5 дней" in r for r in reqs)
    assert not any("22:00" in r for r in engine.requirements_for(d, "mowing"))


def test_children_and_unknown_layers_fail_safe(engine, safe_ctx):
    assert PEST <= set(engine.decide({**safe_ctx, "child_org_territory": True}).prohibited)
    assert PEST <= set(engine.decide({**safe_ctx, "d_child_m": 60.0}).prohibited)
    d = engine.decide({**safe_ctx, "water_zone_m": None})
    assert PEST <= set(d.prohibited) and "context_incomplete" in d.flags


def test_heritage_switches_to_umbels_and_cover(engine, safe_ctx):
    d = engine.decide({**safe_ctx, "near_heritage": True, "area_m2": 50.0})
    assert {"root_cut", "digging"} <= set(d.prohibited)
    assert d.recommended[0] == "umbel_removal"


def test_uav_allowed_only_far_from_everything(engine, safe_ctx):
    d = engine.decide({**safe_ctx, "area_m2": 20_000.0})
    assert "aerial_uav_herbicide" in d.recommended
    assert "aerial_uav_herbicide" in engine.decide({**safe_ctx, "d_settlement_m": None}).prohibited
    assert "aerial_uav_herbicide" in engine.decide({**safe_ctx, "uav_flights_restricted": True}).prohibited


def test_jurisdiction_gate(engine, safe_ctx):
    ok = engine.decide(safe_ctx)
    assert not ok.requires_legal_review and any("369-ПП" in o["text"] for o in ok.obligations)
    assert engine.decide({**safe_ctx, "jurisdiction": "unknown"}).requires_legal_review
    mo = engine.decide({**safe_ctx, "jurisdiction": "moscow_oblast"})
    assert mo.requires_legal_review and "jurisdiction_unverified" in mo.flags


def test_moscow_scope_and_an_untied_fishery_distance(engine, safe_ctx):
    solidago = engine.decide({**safe_ctx, "taxon": "solidago"})
    assert solidago.requires_legal_review and "solidago_clause_3_2" in solidago.flags
    protected = engine.decide({**safe_ctx, "in_protected": True})
    assert protected.requires_legal_review and "oopt_scope" in protected.flags
    edge = engine.decide({**safe_ctx, "near_jurisdiction_boundary": True})
    assert edge.requires_legal_review and "jurisdiction_boundary" in edge.flags
    canal = engine.decide({**safe_ctx, "water_zone_unknown": True})
    assert PEST <= set(canal.prohibited)
    # The 177147 grid ties the three 700 m distances. An untied fishery distance still bans the drone.
    far = {"d_settlement_m": 1500.0, "d_drinking_water_m": 2000.0, "d_protected_m": 2000.0, "d_fishery_water_m": 100.0}
    assert "aerial_uav_herbicide" in engine.decide({**safe_ctx, **far}).prohibited


def test_invariants_on_random_contexts(engine, safe_ctx):
    rng = np.random.default_rng(1)
    for _ in range(500):
        ctx = dict(safe_ctx)
        for k in ("in_protected", "child_org_territory", "near_heritage", "in_settlement", "in_zso"):
            ctx[k] = [True, False, None][rng.integers(3)]
        for k in ("water_zone_m", "d_child_m", "d_settlement_m", "area_m2"):
            ctx[k] = [None, float(rng.uniform(0, 1500)), 0.0][rng.integers(3)]
        ctx["taxon"] = ["heracleum", "solidago"][rng.integers(2)]
        d = engine.decide(ctx)
        cited = {c["rule"] for c in d.citations}
        assert all(set(rules) <= cited for rules in d.prohibited.values())
        assert d.recommended and set(d.recommended) <= set(d.allowed)
        if (ctx["water_zone_m"] or 0) > 0 or ctx["child_org_territory"] or ctx["in_zso"]:
            assert PEST <= set(d.prohibited)
        if ctx["in_settlement"]:
            assert "aerial_uav_herbicide" in d.prohibited
        if any(ctx[k] is None for k in ("water_zone_m", "child_org_territory", "d_child_m", "in_protected", "in_zso")):
            assert PEST <= set(d.prohibited)
