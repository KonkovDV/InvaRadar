from datetime import date

import pytest
from invaradar_pro.events import GENESIS, Event
from invaradar_pro.workflow import Case, State, TransitionError, apply, followup_schedule

MODEL = {"id": "m", "role": "model", "kind": "system"}
AGENT = {"id": "a", "role": "agent", "kind": "agent"}
CREW = {"id": "crew", "role": "crew", "kind": "human"}
LAWYER = {"id": "law", "role": "lawyer", "kind": "human"}
INSP = {"id": "insp", "role": "inspector", "kind": "human", "name": "И."}
CTR = {"id": "ctr", "role": "contractor", "kind": "human"}
SYS = {"id": "system", "role": "system", "kind": "system"}


def at(s):
    return f"{s}T10:00:00+00:00"


def to_approved(store, engine, ctx, cid="c1"):
    store.act(cid, "signal_received", MODEL, {"taxon": ctx["taxon"], "lat": 55.6, "lon": 37.6, "area_m2": ctx["area_m2"]},
              at=at("2027-04-20"))
    store.act(cid, "field_result", CREW, {"present": True, "photos": ["sha"]}, at=at("2027-04-25"))
    store.act(cid, "order_drafted", AGENT, {"decision": engine.decide(ctx).to_dict()}, at=at("2027-04-26"))
    store.act(cid, "order_approved", INSP, {"signer": "И.", "method": "mowing", "due": "2027-06-30"}, at=at("2027-04-28"))
    store.act(cid, "work_started", CTR, {}, at=at("2027-05-05"))


def report(store, cid="c1", seed=True, verdict="pass", day="2027-05-20", method="mowing"):
    store.act(cid, "work_reported", CTR, {"method_used": method, "evidence": [{"sha256": "x"}], "verdict": verdict,
                                          "seed_set_prevented": seed}, at=at(day))


def test_full_cycle_to_closed(store, engine, safe_ctx):
    to_approved(store, engine, safe_ctx)
    report(store)
    store.act("c1", "work_accepted", INSP, {}, at=at("2027-05-22"))
    store.act("c1", "monitoring_scheduled", SYS, {"schedule": ["2027-06-12"]}, at=at("2027-05-22"))
    for y in (2027, 2028, 2029):
        store.act("c1", "followup", CREW, {"season": y, "regrowth": False, "photos": ["p"]}, at=at(f"{y}-08-10"))
    with pytest.raises(TransitionError, match="чистых сезонов 2"):
        store.act("c1", "case_closed", INSP, {}, at=at("2029-09-01"))
    store.act("c1", "followup", CREW, {"season": 2030, "regrowth": False, "photos": ["p"]}, at=at("2030-08-10"))
    store.act("c1", "case_closed", INSP, {}, at=at("2030-09-01"))
    c = store.case("c1")
    assert c.state == State.CLOSED and c.clean_seasons == 3 and c.blocked == 1
    assert store.log.verify()[0]


def test_seeded_needs_five_seasons(store, engine, safe_ctx):
    to_approved(store, engine, safe_ctx)
    report(store, seed=False)
    store.act("c1", "work_accepted", INSP, {}, at=at("2027-05-22"))
    store.act("c1", "monitoring_scheduled", SYS, {"schedule": ["x"]}, at=at("2027-05-22"))
    for y in (2028, 2029, 2030):
        store.act("c1", "followup", CREW, {"season": y, "regrowth": False, "photos": ["p"]}, at=at(f"{y}-08-10"))
    with pytest.raises(TransitionError, match="нужно 5"):
        store.act("c1", "case_closed", INSP, {}, at=at("2030-09-01"))


def test_human_gates_and_blocked_log(store, engine, safe_ctx):
    store.act("c1", "signal_received", MODEL, {"taxon": "heracleum", "lat": 55.6, "lon": 37.6}, at=at("2027-04-20"))
    with pytest.raises(TransitionError, match="уверенностью"):
        store.act("c1", "field_result", MODEL, {"present": True, "photos": ["s"], "verified_by": "ai_photo",
                                                "confidence": 0.7})
    store.act("c1", "field_result", MODEL, {"present": True, "photos": ["s"], "verified_by": "ai_photo", "confidence": 0.95})
    store.act("c1", "order_drafted", AGENT, {"decision": engine.decide({**safe_ctx, "water_zone_m": 50.0}).to_dict()})
    agent_as_inspector = {"id": "a", "role": "inspector", "kind": "agent"}
    with pytest.raises(TransitionError, match="только человек"):
        store.act("c1", "order_approved", agent_as_inspector, {"signer": "a", "method": "mowing", "due": "2027-06-30"})
    with pytest.raises(TransitionError, match="запрещён"):
        store.act("c1", "order_approved", INSP, {"signer": "И.", "method": "ground_herbicide_spot", "due": "2027-06-30"})
    assert store.case("c1").blocked == 3 and store.case("c1").state == State.ORDER_DRAFT


def test_legal_review_gate(store, engine, safe_ctx):
    store.act("c1", "signal_received", MODEL, {"taxon": "heracleum", "lat": 55.6, "lon": 37.6})
    store.act("c1", "field_result", CREW, {"present": True, "photos": ["s"]})
    store.act("c1", "order_drafted", AGENT, {"decision": engine.decide({**safe_ctx, "jurisdiction": "unknown"}).to_dict()})
    assert store.case("c1").state == State.LEGAL_REVIEW
    with pytest.raises(TransitionError):
        store.act("c1", "order_approved", INSP, {"signer": "И.", "method": "mowing", "due": "2027-06-30"})
    with pytest.raises(TransitionError, match="открытых"):
        store.act("c1", "legal_cleared", LAWYER, {"note": "n", "jurisdiction": "x",
                                                  "decision": engine.decide({**safe_ctx, "jurisdiction": "unknown"}).to_dict()})
    store.act("c1", "legal_cleared", LAWYER, {"note": "по границе", "jurisdiction": "moscow_city",
                                              "decision": engine.decide(safe_ctx).to_dict()})
    store.act("c1", "order_approved", INSP, {"signer": "И.", "method": "mowing", "due": "2027-06-30"})
    assert store.case("c1").state == State.ORDER_APPROVED


def test_contractor_cannot_use_banned_method_or_accept_own_work(store, engine, safe_ctx):
    to_approved(store, engine, {**safe_ctx, "water_zone_m": 100.0})
    with pytest.raises(TransitionError, match="запрещённый метод"):
        report(store, method="ground_herbicide_boom")
    report(store, verdict="fail")
    insp_same_id = {"id": "ctr", "role": "inspector", "kind": "human"}
    with pytest.raises(TransitionError, match="не тот"):
        store.act("c1", "work_accepted", insp_same_id, {})
    with pytest.raises(TransitionError, match="причина"):
        store.act("c1", "work_accepted", INSP, {})
    store.act("c1", "work_rejected", INSP, {"reason": "фото не с места"})
    report(store, day="2027-05-27")
    store.act("c1", "work_accepted", INSP, {})
    assert store.case("c1").state == State.ACCEPTED


def test_relapse_resets_clean_seasons(store, engine, safe_ctx):
    to_approved(store, engine, safe_ctx)
    report(store)
    store.act("c1", "work_accepted", INSP, {}, at=at("2027-05-22"))
    store.act("c1", "monitoring_scheduled", SYS, {"schedule": ["x"]}, at=at("2027-05-22"))
    store.act("c1", "followup", CREW, {"season": 2028, "regrowth": False, "photos": ["p"]}, at=at("2028-06-10"))
    store.act("c1", "followup", CREW, {"season": 2028, "regrowth": True, "photos": ["p"]}, at=at("2028-08-10"))
    c = store.case("c1")
    assert c.state == State.RELAPSE and c.clean_seasons == 0


def test_replay_rejects_forged_but_rehashed_log(engine):
    forged = Event(0, "c1", "order_approved", INSP, at("2027-05-01"), {"signer": "x", "method": "mowing", "due": "d"},
                   GENESIS)
    forged = Event(**{**forged.__dict__, "hash": forged.compute_hash()})
    with pytest.raises(TransitionError, match="из состояния"):
        apply(Case(id="c1"), forged, engine.taxa)


def test_followup_schedule(engine):
    s = followup_schedule(date(2027, 6, 1), "heracleum", engine.taxa)
    assert s[:2] == ["2027-06-22", "2027-07-13"] and len(s) == 10 and s[-1] == "2031-08-10"
