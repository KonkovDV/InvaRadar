"""Формальная проверка правил закона полным перебором контекстов (model checking).

Случайные тесты ловят ошибки с некоторой вероятностью. Перебор доказывает свойства на выбранной
сетке, не на всех мыслимых расстояниях. Область: тернарные флаги (истина / ложь / неизвестно),
расстояния (неизвестно / ближе порога / дальше порога), три класса размера. Три поля полосы 700 м
(питьевая вода, ООПТ, рыбохозяйственный водоём) в сетке по умолчанию ходят вместе: это 3^11 = 177 147.
Полное произведение, где эти три поля различаются, равно 1 594 323 и этой функцией не строится.

**Проверяемые свойства:**
- **P1 — ссылки:** у каждого запрета есть ссылка на норму или на правило системы.
- **P2 — безопасность химии:** водоохранная зона, ЗСО, детская организация, дети ближе 100 м и ООПТ
  исключают любые пестициды.
- **P3 — беспилотник:** населённый пункт, ООПТ, любое расстояние ближе 700 м, режим ограничения
  полётов и любое неизвестное значение исключают опрыскивание с беспилотника.
- **P4 — монотонность по неизвестному (отказ в безопасную сторону):** для любого контекста x и любого
  поля f, которое в x неизвестно, allowed(x) ⊆ allowed(x[f := v]) для каждого значения v.
  Неизвестное никогда не разрешает того, что известное значение могло бы запретить.
- **P5 — согласованность:** рекомендованное ⊆ разрешённого и не пусто.
- **O1–O3 — обязанности:**
  - проверка юристом нужна, когда пакет не сверен, вид не в перечне или это московский золотарник
    (пункт 3.2 приложения 2 к 369-ПП — с 01.01.2027). ООПТ и полоса 50 м у границы проверяются отдельными тестами;
  - 294-ФЗ подставляется по типу правообладателя;
  - КоАП подставляется только для граждан, юрлиц и обладателей сервитута.

Плюс покрытие правил: в скольких контекстах правило — единственная причина запрета (решающее).
"""
from __future__ import annotations

import itertools
from collections import Counter

from .law import LawEngine

TRI = (True, False, None)
FLAGS = ("in_protected", "child_org_territory", "near_heritage", "in_settlement", "in_zso", "uav_flights_restricted")
WATER = (None, 0.0, 50.0)
CHILD = (None, 50.0, 500.0)
DIST = (None, 300.0, 1500.0)
AREA = (50.0, 1000.0, 20000.0)


def _contexts(full_distances: bool = False):
    others_space = list(itertools.product(DIST, repeat=3)) if full_distances else [(d, d, d) for d in DIST]
    for flags in itertools.product(TRI, repeat=len(FLAGS)):
        for w, c, ds, others, a in itertools.product(WATER, CHILD, DIST, others_space, AREA):
            ctx = dict(zip(FLAGS, flags))
            ctx.update(water_zone_m=w, d_child_m=c, d_settlement_m=ds, d_drinking_water_m=others[0],
                       d_protected_m=others[1], d_fishery_water_m=others[2], area_m2=a,
                       taxon="heracleum", jurisdiction="moscow_city", holder_type="legal_entity")
            yield ctx


def _key(ctx: dict) -> tuple:
    return tuple(ctx[k] for k in FLAGS + ("water_zone_m", "d_child_m", "d_settlement_m", "d_drinking_water_m",
                                           "d_protected_m", "d_fishery_water_m", "area_m2"))


DOMAINS = {**{f: TRI for f in FLAGS}, "water_zone_m": WATER, "d_child_m": CHILD, "d_settlement_m": DIST}


def run(engine: LawEngine | None = None, full_distances: bool = False, max_examples: int = 3) -> dict:
    eng = engine or LawEngine()
    pest = set(eng.expand(["@pesticide"]))
    decisions: dict[tuple, frozenset] = {}
    fails: dict[str, list] = {p: [] for p in ("P1", "P2", "P3", "P4", "P5")}
    decisive: Counter = Counter()
    n = 0
    ctxs = list(_contexts(full_distances))
    for ctx in ctxs:
        d = eng.decide(ctx)
        n += 1
        allowed = frozenset(d.allowed)
        decisions[_key(ctx)] = allowed
        cited = {c["rule"] for c in d.citations}
        for m, rules in d.prohibited.items():
            if not set(rules) <= cited and len(fails["P1"]) < max_examples:
                fails["P1"].append({"ctx": ctx, "method": m})
            if len(rules) == 1:
                decisive[rules[0]] += 1
        risky = ((ctx["water_zone_m"] or 0) > 0 or ctx["in_zso"] or ctx["child_org_territory"]
                 or (ctx["d_child_m"] is not None and ctx["d_child_m"] < 100) or ctx["in_protected"])
        if risky and pest & allowed and len(fails["P2"]) < max_examples:
            fails["P2"].append({"ctx": ctx, "allowed": sorted(pest & allowed)})
        dists = [ctx[k] for k in ("d_settlement_m", "d_drinking_water_m", "d_protected_m", "d_fishery_water_m")]
        uav_bad = (ctx["in_settlement"] is not False or ctx["in_protected"] is not False
                   or ctx["uav_flights_restricted"] is not False or any(v is None or v < 700 for v in dists))
        if uav_bad and "aerial_uav_herbicide" in allowed and len(fails["P3"]) < max_examples:
            fails["P3"].append({"ctx": ctx})
        if (not d.recommended or not set(d.recommended) <= allowed) and len(fails["P5"]) < max_examples:
            fails["P5"].append({"ctx": ctx})
    # P4: монотонность по неизвестному — по всем полям с явной областью значений
    checked = 0
    for ctx in ctxs:
        for f, dom in DOMAINS.items():
            if ctx[f] is not None:
                continue
            base = decisions[_key(ctx)]
            for v in dom:
                if v is None:
                    continue
                filled = decisions.get(_key({**ctx, f: v}))
                if filled is None:
                    continue
                checked += 1
                if not base <= filled and len(fails["P4"]) < max_examples:
                    fails["P4"].append({"field": f, "value": v, "ctx": ctx, "extra": sorted(base - filled)})
    # O1–O3: обязанности
    ofails = []
    safe = {"area_m2": 1000.0, "water_zone_m": 0.0, "in_protected": False, "child_org_territory": False,
            "d_child_m": 900.0, "near_heritage": False, "in_settlement": False, "in_zso": False}
    duty = {"citizen", "legal_entity", "municipal", "regional", "federal", "servitude"}
    koap = {"citizen", "legal_entity", "servitude"}
    for jur, taxon, holder in itertools.product(("unknown", "moscow_city", "moscow_oblast"), ("heracleum", "solidago"),
                                                (None, "citizen", "legal_entity", "municipal", "servitude")):
        d = eng.decide({**safe, "jurisdiction": jur, "taxon": taxon, "holder_type": holder})
        pack = eng.jurisdictions.get(jur)
        listed = bool(pack and (pack["lists"].get(taxon) or {}).get("verified"))
        # Moscow goldenrod waits: 369-ПП appendix 2 clause 3.2 starts on 2027-01-01.
        expect_review = pack is None or not pack.get("verified") or not listed or (jur == "moscow_city" and taxon == "solidago")
        rules = {o["rule"] for o in d.obligations}
        if d.requires_legal_review != expect_review:
            ofails.append(("O1", jur, taxon, holder))
        if ("fz294-duty" in rules) != (holder in duty):
            ofails.append(("O2", jur, taxon, holder))
        if ("koap-8-7-2" in rules) != (holder in koap):
            ofails.append(("O3", jur, taxon, holder))
    rule_ids = [r["id"] for r in eng.federal["rules"]]
    return {
        "contexts": n, "monotonicity_pairs": checked,
        "properties": {p: ("ok" if not v else "FAIL") for p, v in fails.items()},
        "counterexamples": {p: v for p, v in fails.items() if v},
        "obligations": "ok" if not ofails else ofails,
        "decisive_contexts_by_rule": {r: int(decisive.get(r, 0)) for r in rule_ids},
        "never_decisive": [r for r in rule_ids if decisive.get(r, 0) == 0 and eng.federal["rules"][rule_ids.index(r)].get("prohibit")],
    }
