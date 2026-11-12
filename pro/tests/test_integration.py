import json
from pathlib import Path

import pytest
from invaradar_pro.agent_tools import dispatch, tool_specs
from invaradar_pro.cli import check_upstream, main
from invaradar_pro.demo import run_demo
from invaradar_pro.upstream import read_work_orders

DATA = Path(__file__).resolve().parents[1] / "data" / "sample"

MODEL = {"id": "m", "role": "model", "kind": "system"}
AGENT = {"id": "a", "role": "agent", "kind": "agent"}


@pytest.mark.parametrize("taxon", ["heracleum", "solidago"])
def test_upstream_invariants(engine, taxon):
    rows = read_work_orders(DATA / f"{taxon}_work_orders_top200_2025.csv")
    res = check_upstream(rows, taxon, engine)
    assert res["rows"] == 200 and res["errors"] == []
    # Moscow city is a verified pack, so those orders do not wait for a lawyer.
    # Oblast and anything outside the polygons still do.
    def expects_review(r):
        if r.get("jurisdiction") != "moscow_city":
            return True
        return bool(taxon == "solidago" or r.get("in_protected") or r.get("near_jurisdiction_boundary"))
    assert sum(r.get("jurisdiction") == "moscow_city" for r in rows) > 0
    assert res["legal_review"] == sum(expects_review(r) for r in rows)


def test_agent_cannot_sign(store, engine, safe_ctx):
    store.act("c1", "signal_received", MODEL, {"taxon": "heracleum", "lat": 55.6, "lon": 37.6})
    store.act("c1", "field_result", {"id": "c", "role": "crew", "kind": "human"}, {"present": True, "photos": ["s"]})
    water = {**safe_ctx, "water_zone_m": 10.0}
    store.act("c1", "order_drafted", AGENT, {"context": water, "decision": engine.decide(water).to_dict()})
    n = len(store.log)
    r = dispatch("approve_order", {"case_id": "c1", "method": "mowing", "due": "2027-06-30"}, AGENT, store, engine)
    assert r["status"] == "needs_human_approval" and len(store.log) == n
    why = dispatch("explain_law", {"case_id": "c1", "method": "ground_herbicide_spot"}, AGENT, store, engine)
    assert why["allowed"] is False and why["because"][0]["act"] == "Водный кодекс РФ"
    assert {t["name"] for t in tool_specs()} >= {"approve_order", "explain_law"}


def test_prove_refuses_a_broken_chain(tmp_path):
    log = tmp_path / "events.jsonl"
    from invaradar_pro.events import EventLog
    EventLog(log).append("c1", "signal_received", {"id": "m", "role": "model", "kind": "system"}, {"n": 1})
    lines = log.read_text(encoding="utf-8").splitlines()
    ev = json.loads(lines[0])
    ev["payload"]["n"] = 2
    log.write_text(json.dumps(ev, ensure_ascii=False) + "\n", encoding="utf-8")
    assert main(["prove", str(log), "--seq", "0"]) == 1


def test_demo_end_to_end(tmp_path):
    s = run_demo(tmp_path / "demo")
    states = set(s["states"].values())
    assert s["chain_ok"] and {"closed", "rejected", "monitoring"} <= states
    assert s["kpi"]["blocked_prohibited_method"] >= 2 and s["kpi"]["first_pass_acceptance"] < 1
    sp = s["spread"]
    assert sp["new_cells"] > 100 and sp["capture_model"]["top10%"] > sp["capture_suitability_only"]["top10%"]
    assert s["corridor"]["segments_with_foci"] >= 4
    for f in ("events.jsonl", "kpi.json", "report.md", "story.md", "corridor_audit.csv", "spread_demo.json",
              "sampling_demo.json"):
        assert (tmp_path / "demo" / f).exists()
    assert len(list((tmp_path / "demo" / "passports").glob("*.md"))) == s["cases"]
    log = tmp_path / "demo" / "events.jsonl"
    assert main(["verify", str(log)]) == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    ev = json.loads(lines[10])
    ev["actor"]["id"] = "someone-else"
    lines[10] = json.dumps(ev, ensure_ascii=False)
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert main(["verify", str(log)]) == 1


def test_api(engine, safe_ctx):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from invaradar_pro.api import create_app
    c = TestClient(create_app(engine=engine))
    h = {"X-Actor-Id": "m", "X-Actor-Role": "model", "X-Actor-Kind": "system"}
    assert c.post("/cases/c1/events", json={"type": "signal_received",
                                            "payload": {"taxon": "heracleum", "lat": 55.6, "lon": 37.6}}, headers=h).status_code == 200
    crew = {"X-Actor-Id": "c", "X-Actor-Role": "crew", "X-Actor-Kind": "human"}
    c.post("/cases/c1/events", json={"type": "field_result", "payload": {"present": True, "photos": ["s"]}}, headers=crew)
    dec = c.post("/law/decide", json=safe_ctx).json()
    agent = {"X-Actor-Id": "a", "X-Actor-Role": "agent", "X-Actor-Kind": "agent"}
    assert c.post("/cases/c1/events", json={"type": "order_drafted", "payload": {"context": safe_ctx, "decision": dec}},
                  headers=agent).status_code == 200
    bot = {"X-Actor-Id": "a", "X-Actor-Role": "inspector", "X-Actor-Kind": "agent"}
    r = c.post("/cases/c1/events", json={"type": "order_approved",
                                         "payload": {"signer": "a", "method": "mowing", "due": "2027-06-30"}}, headers=bot)
    assert r.status_code == 403
    assert c.get("/cases/c1/passport").status_code == 200
    assert c.get("/health").json()["ok"] is True
