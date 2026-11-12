"""Инструменты для ИИ-агента (формат tool use: name, description, input_schema).

Агент читает очаги, объясняет закон, готовит черновики и назначает осмотры. Подписать наряд,
принять работу или закрыть очаг он не может: такие вызовы возвращают запрос на подтверждение
человеком и ничего не меняют. Это не только настройка промпта — запрет стоит в workflow.py,
и тот же отказ получит любой не-человек, как бы его ни попросили.
"""
from __future__ import annotations

from .law import LawEngine
from .workflow import STATE_RU, CaseStore, TransitionError

_S = {"type": "string"}

TOOLS = [
    {"name": "list_cases", "description": "Список очагов с состоянием. Фильтр по состоянию необязателен.",
     "input_schema": {"type": "object", "properties": {"state": _S}}, "mutates": False, "human_gate": False},
    {"name": "get_case", "description": "Очаг: состояние, решение по закону, наряд, история.",
     "input_schema": {"type": "object", "properties": {"case_id": _S}, "required": ["case_id"]},
     "mutates": False, "human_gate": False},
    {"name": "explain_law", "description": "Почему метод разрешён или запрещён на очаге, со ссылками на нормы.",
     "input_schema": {"type": "object", "properties": {"case_id": _S, "method": _S}, "required": ["case_id", "method"]},
     "mutates": False, "human_gate": False},
    {"name": "assign_field_check", "description": "Назначить осмотр очага бригаде или инспектору.",
     "input_schema": {"type": "object", "properties": {"case_id": _S, "assignee": _S}, "required": ["case_id", "assignee"]},
     "mutates": True, "human_gate": False},
    {"name": "approve_order", "description": "Утвердить наряд. Выполняет только уполномоченный человек.",
     "input_schema": {"type": "object", "properties": {"case_id": _S, "method": _S, "due": _S},
                      "required": ["case_id", "method", "due"]}, "mutates": True, "human_gate": True},
    {"name": "accept_work", "description": "Принять работы по доказательствам. Выполняет только человек.",
     "input_schema": {"type": "object", "properties": {"case_id": _S}, "required": ["case_id"]},
     "mutates": True, "human_gate": True},
    {"name": "close_case", "description": "Закрыть очаг после чистых сезонов. Выполняет только человек.",
     "input_schema": {"type": "object", "properties": {"case_id": _S}, "required": ["case_id"]},
     "mutates": True, "human_gate": True},
]
_BY_NAME = {t["name"]: t for t in TOOLS}
_EVENT = {"approve_order": "order_approved", "accept_work": "work_accepted", "close_case": "case_closed"}


def tool_specs() -> list[dict]:
    """Описания для API модели: без служебных полей."""
    return [{k: t[k] for k in ("name", "description", "input_schema")} for t in TOOLS]


def dispatch(name: str, args: dict, actor: dict, store: CaseStore, engine: LawEngine) -> dict:
    tool = _BY_NAME.get(name)
    if tool is None:
        return {"status": "error", "error": f"нет инструмента {name}"}
    if tool["human_gate"] and actor.get("kind") != "human":
        return {"status": "needs_human_approval",
                "request": {"tool": name, "args": args, "requested_by": actor.get("id"),
                            "message": "Действие меняет обязанности людей: нужна подпись уполномоченного лица."}}
    try:
        if name == "list_cases":
            return {"status": "ok", "cases": [{"id": c.id, "state": str(c.state), "state_ru": STATE_RU.get(c.state)}
                                               for c in store.cases().values()
                                               if not args.get("state") or str(c.state) == args["state"]]}
        case = store.case(args["case_id"])
        if name == "get_case":
            return {"status": "ok", "case": {"id": case.id, "state": str(case.state), "taxon": case.taxon,
                                             "decision": case.decision, "order": case.order,
                                             "clean_seasons": case.clean_seasons, "events": len(case.history)}}
        if name == "explain_law":
            d = case.decision or {}
            m = args["method"]
            if m in d.get("prohibited", {}):
                cites = [c for c in d["citations"] if c["rule"] in d["prohibited"][m]]
                return {"status": "ok", "allowed": False, "because": cites}
            return {"status": "ok", "allowed": m in d.get("allowed", []), "requirements": engine.requirements_for(d, m)}
        if name == "assign_field_check":
            ev = store.act(case.id, "field_check_assigned", actor, {"assignee": args["assignee"]})
            return {"status": "ok", "event": ev.hash}
        payload = {k: v for k, v in args.items() if k != "case_id"}
        if name == "approve_order":
            payload["signer"] = actor.get("name") or actor.get("id")
        ev = store.act(case.id, _EVENT[name], actor, payload)
        return {"status": "ok", "event": ev.hash}
    except (TransitionError, KeyError) as err:
        return {"status": "rejected", "error": str(err)}
