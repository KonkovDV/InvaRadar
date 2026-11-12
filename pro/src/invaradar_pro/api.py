"""HTTP API (FastAPI, необязательная зависимость: pip install -e '.[api]').

Запуск: uvicorn invaradar_pro.api:app --reload
Здесь роль берётся из заголовков X-Actor-*: так проще показать логику. В промышленной версии
роль и вид исполнителя приходят только из проверенного токена (OIDC, для госслужащих — ЕСИА),
а заголовки игнорируются.
"""
from __future__ import annotations

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import __version__
from .agent_tools import tool_specs
from .events import EventLog
from .kpi import compute
from .law import LawEngine
from .report import case_passport
from .workflow import STATE_RU, CaseStore, TransitionError


class EventIn(BaseModel):
    type: str
    payload: dict = {}


def create_app(store: CaseStore | None = None, engine: LawEngine | None = None) -> FastAPI:
    engine = engine or LawEngine()
    store = store or CaseStore(EventLog(), engine.taxa)
    app = FastAPI(title="ИнваРадар Pro", version=__version__)

    @app.get("/health")
    def health():
        ok, bad = store.log.verify()
        return {"ok": ok, "first_bad_event": bad, "events": len(store.log), "head": store.log.head}

    @app.get("/cases")
    def list_cases():
        return [{"id": c.id, "state": str(c.state), "state_ru": STATE_RU.get(c.state)} for c in store.cases().values()]

    @app.get("/cases/{case_id}")
    def get_case(case_id: str):
        try:
            c = store.case(case_id)
        except KeyError:
            raise HTTPException(404, "нет такого очага") from None
        return {"id": c.id, "state": str(c.state), "taxon": c.taxon, "decision": c.decision, "order": c.order,
                "clean_seasons": c.clean_seasons, "history": [e.hash for e in c.history]}

    @app.get("/cases/{case_id}/passport", response_class=PlainTextResponse)
    def passport(case_id: str):
        try:
            return case_passport(store.case(case_id), engine)
        except KeyError:
            raise HTTPException(404, "нет такого очага") from None

    @app.post("/cases/{case_id}/events")
    def post_event(case_id: str, ev: EventIn, x_actor_id: str = Header(...), x_actor_role: str = Header(...),
                   x_actor_kind: str = Header("human")):
        actor = {"id": x_actor_id, "role": x_actor_role, "kind": x_actor_kind}
        try:
            e = store.act(case_id, ev.type, actor, ev.payload)
        except TransitionError as err:
            msg = str(err)
            raise HTTPException(403 if ("только человек" in msg or "роль" in msg) else 409, msg) from err
        return {"seq": e.seq, "hash": e.hash, "state": str(store.case(case_id).state)}

    @app.post("/law/decide")
    def decide(ctx: dict):
        try:
            return engine.decide(ctx).to_dict()
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    @app.get("/kpi")
    def kpi():
        return compute(store)

    @app.get("/tools")
    def tools():
        return tool_specs()

    return app


app = create_app()
