"""Паспорт очага и отчёт программы в Markdown — то, что видит инспектор, подрядчик и жюри."""
from __future__ import annotations

from .law import LawEngine
from .workflow import STATE_RU, Case

EVENT_RU = {
    "signal_received": "сигнал", "field_check_assigned": "назначен осмотр", "field_result": "итог осмотра",
    "order_drafted": "проект наряда", "legal_cleared": "юрист снял вопросы", "order_approved": "наряд утверждён",
    "work_started": "работы начаты", "work_reported": "работы сданы", "work_rejected": "работы возвращены",
    "work_accepted": "работы приняты", "monitoring_scheduled": "график контроля", "followup": "контрольный осмотр",
    "case_closed": "очаг закрыт", "blocked_attempt": "попытка заблокирована",
}


def _who(actor: dict) -> str:
    return f"{actor.get('role')} ({actor.get('kind')}) {actor.get('id')}"


def case_passport(case: Case, engine: LawEngine) -> str:
    d = case.decision or {}
    lines = [f"# Паспорт очага {case.id}", "",
             f"- Вид: {engine.taxa.get(case.taxon, {}).get('title', case.taxon)}",
             f"- Координаты: {case.lat:.5f}, {case.lon:.5f}; площадь: {f'{case.area_m2 or 0:,.0f}'.replace(',', ' ')} м²",
             f"- Состояние: **{STATE_RU.get(case.state, case.state)}**",
             f"- Чистых сезонов после работ: {case.clean_seasons}"]
    cl = engine.taxa.get(case.taxon, {}).get("closure")
    if cl and case.treated_season is not None:
        from .eradication import ClosureParams, closure_check
        r = closure_check(case.followups, case.treated_season, not case.seed_set_prevented, ClosureParams.from_policy(cl))
        lines.append(f"- P(очаг жив) на следующий сезон: {r['p_next']:.3f} (порог закрытия {r['p_max']}; "
                     f"байесовская оценка по {len(case.followups)} осмотрам)")
    from .eradication import feasibility
    fz = feasibility(case.area_m2)
    lines.append(f"- Осуществимость ликвидации по площади ({fz['class']}): {fz['strategy']}")
    lines.append("")
    if d:
        lines += ["## Что разрешено по закону", "",
                  f"Юрисдикция: {d['jurisdiction']}; класс размера: {d['size_class']}.", "",
                  "| Метод | Статус | Основание |", "|---|---|---|"]
        for m in engine.methods:
            if m in d["prohibited"]:
                lines.append(f"| {engine.title(m)} | запрещён | {', '.join(d['prohibited'][m])} |")
            elif m in d["recommended"]:
                lines.append(f"| {engine.title(m)} | рекомендован | агротехника вида |")
            else:
                lines.append(f"| {engine.title(m)} | разрешён | запретов нет; не в плане для этого размера |")
        lines += ["", "## Требования к работам", ""]
        method = (case.order or {}).get("method")
        reqs = engine.requirements_for(d, method) if method else [r["text"] for r in d["requirements"]]
        lines += [f"- {t}" for t in reqs]
        if d["obligations"]:
            lines += ["", "## Обязанности и ответственность", ""] + [f"- {o['text']}" for o in d["obligations"]]
        lines += ["", "## Ссылки", ""]
        for c in d["citations"]:
            mark = {True: "сверено", False: "НЕ сверено", None: "правило системы"}[c.get("verified")]
            lines.append(f"- `{c['rule']}` — {c['act']}, {c['ref']} ({mark})")
        if d["flags"]:
            lines += ["", "Флаги: " + ", ".join(f"`{f}`" for f in d["flags"])]
    if case.order:
        lines += ["", "## Наряд", "",
                  f"Метод: {engine.title(case.order['method'])}. Срок: {case.order['due']}. Утвердил: {case.order['signer']}."]
    lines += ["", "## Журнал", "", "| Дата | Событие | Кто | Хеш |", "|---|---|---|---|"]
    for e in case.history:
        extra = f" — {e.payload.get('reason')}" if e.type in ("blocked_attempt", "work_rejected") else ""
        lines.append(f"| {e.at[:10]} | {EVENT_RU.get(e.type, e.type)}{extra} | {_who(e.actor)} | `{e.hash[:12]}` |")
    lines += ["", "Карта и наряд не являются основанием для штрафа: решение принимает уполномоченное лицо "
              "по акту обследования."]
    return "\n".join(lines) + "\n"


def program_report(kpi: dict, title: str = "Отчёт программы") -> str:
    rows = [f"# {title}", "", "| Показатель | Значение |", "|---|---|"]
    names = {
        "cases": "Очагов в работе", "signal_to_check_days_median": "Дней от сигнала до осмотра (медиана)",
        "confirm_rate": "Доля подтверждённых при осмотре", "ai_autoconfirm_share": "Доля подтверждений ИИ по фото",
        "order_to_report_days_median": "Дней от наряда до сдачи (медиана)",
        "first_pass_acceptance": "Приняты с первого раза", "relapse_rate_per_followup": "Отрастание на контроль",
        "closed_share_of_approved": "Закрыто от утверждённых", "blocked_attempts": "Заблокированных действий",
        "blocked_prohibited_method": "из них — запрещённый метод", "treated_area_ha": "Обработано, га",
        "herbicide_l_per_ha": "Гербицид, л/га", "chain_ok": "Журнал цел",
    }
    for k, name in names.items():
        rows.append(f"| {name} | {kpi.get(k)} |")
    rows += ["", f"Состояния: {kpi['by_state']}", "", f"Голова журнала: `{kpi['chain_head']}`"]
    if kpi.get("overdue_orders"):
        rows += ["", "Просрочены: " + ", ".join(kpi["overdue_orders"])]
    return "\n".join(rows) + "\n"
