"""Жизненный цикл очага: сигнал → осмотр → наряд по закону → работы с доказательствами → контроль → закрытие.

Состояние очага не хранится отдельно: оно каждый раз пересобирается из журнала событий.
Поэтому журнал — единственный источник правды, а повторный проход по нему заново
проверяет каждый переход (испорченный, но пересчитанный журнал тоже будет пойман).

Правила, которые закрывают швы между участниками:
- утверждает наряд, принимает работу и закрывает очаг только человек с нужной ролью;
- ИИ-агент может готовить черновики и назначать осмотры, но не подписывать;
- подрядчик не может применить метод, который закон запрещает на этом очаге;
- принимает работу не тот, кто её сдал;
- закрыть очаг можно только после нужного числа чистых сезонов (банк семян).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum

from .events import Event, EventLog


class State(StrEnum):
    SIGNAL = "signal"
    FIELD_CHECK = "field_check"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    LEGAL_REVIEW = "legal_review"
    ORDER_DRAFT = "order_draft"
    ORDER_APPROVED = "order_approved"
    IN_WORK = "in_work"
    WORK_REPORTED = "work_reported"
    REWORK = "rework"
    ACCEPTED = "accepted"
    MONITORING = "monitoring"
    RELAPSE = "relapse"
    CLOSED = "closed"


STATE_RU = {
    State.SIGNAL: "сигнал", State.FIELD_CHECK: "назначен осмотр", State.CONFIRMED: "подтверждён",
    State.REJECTED: "не подтверждён", State.LEGAL_REVIEW: "у юриста", State.ORDER_DRAFT: "проект наряда",
    State.ORDER_APPROVED: "наряд утверждён", State.IN_WORK: "в работе", State.WORK_REPORTED: "работы сданы",
    State.REWORK: "на доработке", State.ACCEPTED: "работы приняты", State.MONITORING: "контроль",
    State.RELAPSE: "рецидив", State.CLOSED: "закрыт",
}

AUTO_CONFIRM_MIN = 0.90
HUMAN_ONLY = {"legal_cleared", "order_approved", "work_rejected", "work_accepted", "case_closed"}
SYSTEM_ACTOR = {"id": "system", "role": "system", "kind": "system"}

ROLES: dict[str, set[str]] = {
    "signal_received": {"model", "citizen", "inspector", "dispatcher", "system"},
    "field_check_assigned": {"dispatcher", "inspector", "agent", "system"},
    "field_result": {"inspector", "crew", "botanist", "model"},
    "order_drafted": {"system", "agent", "inspector"},
    "legal_cleared": {"lawyer"},
    "order_approved": {"inspector", "official"},
    "work_started": {"contractor"},
    "work_reported": {"contractor"},
    "work_rejected": {"inspector", "official"},
    "work_accepted": {"inspector", "official"},
    "monitoring_scheduled": {"system", "agent", "inspector"},
    "followup": {"inspector", "crew", "botanist", "citizen", "model"},
    "case_closed": {"inspector", "official"},
    "blocked_attempt": {"system"},
}

SOURCES: dict[str, set] = {
    "signal_received": {None},
    "field_check_assigned": {State.SIGNAL},
    "field_result": {State.SIGNAL, State.FIELD_CHECK},
    "order_drafted": {State.CONFIRMED, State.RELAPSE},
    "legal_cleared": {State.LEGAL_REVIEW},
    "order_approved": {State.ORDER_DRAFT},
    "work_started": {State.ORDER_APPROVED},
    "work_reported": {State.IN_WORK, State.REWORK},
    "work_rejected": {State.WORK_REPORTED},
    "work_accepted": {State.WORK_REPORTED},
    "monitoring_scheduled": {State.ACCEPTED},
    "followup": {State.MONITORING},
    "case_closed": {State.MONITORING},
}

DEFAULT_MIN_CLEAN = {"no_seed": 3, "seeded": 5}


class TransitionError(ValueError):
    pass


@dataclass
class Case:
    id: str
    state: State | None = None
    taxon: str | None = None
    lat: float | None = None
    lon: float | None = None
    area_m2: float | None = None
    decision: dict | None = None
    order: dict | None = None
    contractor: str | None = None
    reporter: str | None = None
    evidence_verdict: str | None = None
    seed_set_prevented: bool | None = None
    treated_season: int | None = None
    clean: set[int] = field(default_factory=set)
    followups: list[tuple[int, str, bool]] = field(default_factory=list)
    blocked: int = 0
    history: list[Event] = field(default_factory=list)

    @property
    def clean_seasons(self) -> int:
        return len([s for s in self.clean if self.treated_season is None or s > self.treated_season])


def _need(p: dict, *keys: str) -> None:
    miss = [k for k in keys if p.get(k) in (None, "", [], {})]
    if miss:
        raise TransitionError("не хватает полей: " + ", ".join(miss))


def required_clean_seasons(case: Case, policy: dict | None) -> int:
    mc = ((policy or {}).get(case.taxon or "", {}) or {}).get("min_clean_seasons", DEFAULT_MIN_CLEAN)
    return int(mc["no_seed"] if case.seed_set_prevented else mc["seeded"])


def _guard(case: Case, et: str, actor: dict, p: dict, policy: dict | None) -> State:
    if et == "signal_received":
        _need(p, "taxon", "lat", "lon")
        return State.SIGNAL
    if et == "field_check_assigned":
        _need(p, "assignee")
        return State.FIELD_CHECK
    if et == "field_result":
        _need(p, "photos")
        if "present" not in p:
            raise TransitionError("нужен ответ: найден вид или нет")
        if actor.get("kind") != "human" and (p.get("verified_by") != "ai_photo"
                                             or float(p.get("confidence", 0)) < AUTO_CONFIRM_MIN):
            raise TransitionError("без человека — только проверка фото ИИ с уверенностью от 0,9")
        return State.CONFIRMED if p["present"] else State.REJECTED
    if et == "order_drafted":
        d = p.get("decision") or {}
        if not d.get("allowed"):
            raise TransitionError("в решении нет разрешённых методов")
        return State.LEGAL_REVIEW if d.get("requires_legal_review") else State.ORDER_DRAFT
    if et == "legal_cleared":
        _need(p, "note", "jurisdiction", "decision")
        if p["decision"].get("requires_legal_review"):
            raise TransitionError("после юриста в решении не должно остаться открытых правовых вопросов")
        return State.ORDER_DRAFT
    if et == "order_approved":
        _need(p, "signer", "method", "due")
        d = case.decision or {}
        if d.get("requires_legal_review"):
            raise TransitionError("наряд не прошёл юридическую проверку")
        if p["method"] not in d.get("allowed", []):
            why = ", ".join(d.get("prohibited", {}).get(p["method"], [])) or "нет в решении"
            raise TransitionError(f"метод «{p['method']}» запрещён для этого очага: {why}")
        return State.ORDER_APPROVED
    if et == "work_started":
        return State.IN_WORK
    if et == "work_reported":
        _need(p, "method_used", "evidence")
        if actor.get("id") != case.contractor:
            raise TransitionError("сдаёт работу подрядчик, который принял наряд")
        d = case.decision or {}
        if p["method_used"] not in d.get("allowed", []):
            why = ", ".join(d.get("prohibited", {}).get(p["method_used"], [])) or "нет в решении"
            raise TransitionError(f"применён запрещённый метод «{p['method_used']}»: {why}")
        if "seed_set_prevented" not in p:
            raise TransitionError("нужно указать, успели ли созреть семена")
        return State.WORK_REPORTED
    if et == "work_rejected":
        _need(p, "reason")
        return State.REWORK
    if et == "work_accepted":
        if actor.get("id") in (case.reporter, case.contractor):
            raise TransitionError("принимает работу не тот, кто её сдал")
        if case.evidence_verdict != "pass" and not p.get("override_reason"):
            raise TransitionError(f"доказательства: «{case.evidence_verdict}»; нужна причина ручного решения")
        return State.ACCEPTED
    if et == "monitoring_scheduled":
        _need(p, "schedule")
        return State.MONITORING
    if et == "followup":
        _need(p, "photos")
        if "season" not in p or "regrowth" not in p:
            raise TransitionError("нужны сезон и ответ об отрастании")
        return State.RELAPSE if p["regrowth"] else State.MONITORING
    if et == "case_closed":
        need = required_clean_seasons(case, policy)
        if case.clean_seasons < need:
            raise TransitionError(f"чистых сезонов {case.clean_seasons}, нужно {need}")
        cl = ((policy or {}).get(case.taxon or "", {}) or {}).get("closure")
        if cl is not None and case.treated_season is not None:
            from .eradication import ClosureParams, closure_check
            res = closure_check(case.followups, case.treated_season, not case.seed_set_prevented,
                                ClosureParams.from_policy(cl))
            if not res["ok"]:
                raise TransitionError(f"P(очаг жив) на следующий сезон {res['p_next']:.3f} выше порога {res['p_max']}")
        return State.CLOSED
    raise TransitionError(f"нет правила для «{et}»")


def next_state(case: Case, et: str, actor: dict, payload: dict, policy: dict | None = None) -> State | None:
    if et not in ROLES:
        raise TransitionError(f"неизвестное событие «{et}»")
    if actor.get("role") not in ROLES[et]:
        raise TransitionError(f"роль «{actor.get('role')}» не может выполнить «{et}»")
    if et == "blocked_attempt":
        return case.state
    if et in HUMAN_ONLY and actor.get("kind") != "human":
        raise TransitionError(f"«{et}» выполняет только человек")
    if case.state not in SOURCES[et]:
        raise TransitionError(f"из состояния «{case.state}» нельзя «{et}»")
    return _guard(case, et, actor, payload, policy)


def apply(case: Case, e: Event, policy: dict | None = None) -> Case:
    target = next_state(case, e.type, e.actor, e.payload, policy)
    p = e.payload
    if e.type == "signal_received":
        case.taxon, case.lat, case.lon, case.area_m2 = p["taxon"], p["lat"], p["lon"], p.get("area_m2")
    elif e.type in ("order_drafted", "legal_cleared"):
        case.decision = p["decision"]
    elif e.type == "order_approved":
        case.order = {"method": p["method"], "due": p["due"], "signer": p["signer"], "approved_at": e.at}
    elif e.type == "work_started":
        case.contractor = e.actor.get("id")
    elif e.type == "work_reported":
        case.reporter = e.actor.get("id")
        case.evidence_verdict = p.get("verdict")
        case.seed_set_prevented = bool(p["seed_set_prevented"])
    elif e.type == "work_rejected":
        case.evidence_verdict = None
    elif e.type == "work_accepted":
        case.treated_season = int(e.at[:4])
        case.clean = set()
        case.followups = []
    elif e.type == "followup":
        case.followups.append((int(p["season"]), e.actor.get("role", ""), bool(p["regrowth"])))
        if p["regrowth"]:
            case.clean = set()
        else:
            case.clean.add(int(p["season"]))
    elif e.type == "blocked_attempt":
        case.blocked += 1
    case.state = target
    case.history.append(e)
    return case


def followup_schedule(accepted: date, taxon: str, policy: dict) -> list[str]:
    """Даты контроля: в сезон работ — через 3 и 6 недель (отрастание), затем дважды за сезон."""
    f = policy[taxon]["followup"]
    out = [accepted + timedelta(days=int(d)) for d in f["first_season_days"]]
    for k in range(1, int(f["seasons"])):
        for md in f["later_season_dates"]:
            m, d = (int(x) for x in md.split("-"))
            out.append(date(accepted.year + k, m, d))
    return [d.isoformat() for d in out]


class CaseStore:
    """Очаги поверх журнала. Каждое действие проверяется, отказ тоже пишется в журнал."""

    def __init__(self, log: EventLog, policy: dict | None = None):
        self.log = log
        self.policy = policy

    def case(self, case_id: str) -> Case:
        c = Case(id=case_id)
        for e in self.log.events(case_id):
            apply(c, e, self.policy)
        if c.state is None:
            raise KeyError(case_id)
        return c

    def cases(self) -> dict[str, Case]:
        out: dict[str, Case] = {}
        for e in self.log:
            apply(out.setdefault(e.case_id, Case(id=e.case_id)), e, self.policy)
        return out

    def act(self, case_id: str, et: str, actor: dict, payload: dict, at: str | None = None,
            log_blocked: bool = True) -> Event:
        try:
            c = self.case(case_id)
        except KeyError:
            c = Case(id=case_id)
        try:
            next_state(c, et, actor, payload, self.policy)
        except TransitionError as err:
            if log_blocked and c.state is not None:
                self.log.append(case_id, "blocked_attempt", SYSTEM_ACTOR,
                                {"attempted": et, "by": actor, "reason": str(err)}, at=at)
            raise
        return self.log.append(case_id, et, actor, payload, at=at)
