"""Показатели программы — только из журнала событий, без ручного ввода.

Те же определения стоят в docs/05_SCIENCE_VALIDATION.md и в KPI пилота.
"""
from __future__ import annotations

from datetime import date, datetime
from statistics import median

from .events import EventLog
from .workflow import CaseStore, State


def _d(s: str) -> date:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date() if "T" in s else date.fromisoformat(s[:10])


def compute(store: CaseStore, today: str | None = None) -> dict:
    log: EventLog = store.log
    cases = store.cases()
    first: dict[tuple[str, str], str] = {}
    for e in log:
        first.setdefault((e.case_id, e.type), e.at)

    def days(a: str, b: str) -> list[int]:
        return [(_d(first[(c, b)]) - _d(first[(c, a)])).days for c in cases if (c, a) in first and (c, b) in first]

    fr = [e for e in log if e.type == "field_result"]
    fu = [e for e in log if e.type == "followup"]
    rep = [e for e in log if e.type == "work_reported"]
    accepted = {e.case_id for e in log if e.type == "work_accepted"}
    rejected = {e.case_id for e in log if e.type == "work_rejected"}
    approved = {e.case_id for e in log if e.type == "order_approved"}
    blocked = [e for e in log if e.type == "blocked_attempt"]
    ref = _d(today) if today else date.today()
    overdue = [c.id for c in cases.values() if c.state in (State.ORDER_APPROVED, State.IN_WORK, State.REWORK)
               and c.order and _d(c.order["due"]) < ref]
    area = sum(float(e.payload.get("treated_area_m2") or 0) for e in rep) / 10_000
    herb = sum(float(e.payload.get("herbicide_l") or 0) for e in rep)
    s2c = days("signal_received", "field_result")
    o2w = days("order_approved", "work_reported")
    by_state: dict[str, int] = {}
    for c in cases.values():
        by_state[str(c.state)] = by_state.get(str(c.state), 0) + 1
    return {
        "cases": len(cases),
        "by_state": dict(sorted(by_state.items())),
        "signal_to_check_days_median": median(s2c) if s2c else None,
        "confirm_rate": round(sum(bool(e.payload.get("present")) for e in fr) / len(fr), 3) if fr else None,
        "ai_autoconfirm_share": round(sum(e.actor.get("kind") != "human" for e in fr) / len(fr), 3) if fr else None,
        "order_to_report_days_median": median(o2w) if o2w else None,
        "first_pass_acceptance": round(len(accepted - rejected) / len(accepted), 3) if accepted else None,
        "overdue_orders": overdue,
        "relapse_rate_per_followup": round(sum(bool(e.payload.get("regrowth")) for e in fu) / len(fu), 3) if fu else None,
        "closed_share_of_approved": round(sum(c.state == State.CLOSED for c in cases.values()) / len(approved), 3) if approved else None,
        "blocked_attempts": len(blocked),
        "blocked_prohibited_method": sum("запрещ" in e.payload.get("reason", "") for e in blocked),
        "herbicide_l_per_ha": round(herb / area, 3) if area else None,
        "treated_area_ha": round(area, 3),
        "chain_ok": log.verify()[0],
        "chain_head": log.head,
        "merkle_root": log.merkle().root().hex() if len(log) else None,
    }
