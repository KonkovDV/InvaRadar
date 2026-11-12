"""Право как код: из контекста очага — разрешённые методы, запреты со ссылками, требования и обязанности.

Принципы:
1. Каждый запрет и каждое требование ссылается на норму или явно помечен как осторожность системы.
2. Нет данных — нет химии: неизвестный слой запрещает пестициды, а не разрешает их.
3. Обязанность правообладателя подставляется только из сверенного пакета юрисдикции.
   Иначе наряд уходит юристу (`requires_legal_review`), а утвердить его без юриста нельзя.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).with_name("rules")


def _missing(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))


def match(cond: dict, ctx: dict) -> bool:
    """Условие правила: все ключи через «и», `any` — список альтернатив через «или»."""
    for key, pred in (cond or {}).items():
        if key == "any":
            if not any(match(c, ctx) for c in pred):
                return False
            continue
        val = ctx.get(key)
        if isinstance(pred, dict):
            for op, ref in pred.items():
                if op == "missing":
                    if _missing(val) != bool(ref):
                        return False
                    continue
                if _missing(val):
                    return False
                ok = {
                    "gt": lambda: val > ref,
                    "gte": lambda: val >= ref,
                    "lt": lambda: val < ref,
                    "lte": lambda: val <= ref,
                    "eq": lambda: val == ref,
                    "in": lambda: val in ref,
                }[op]()
                if not ok:
                    return False
        elif _missing(val) or val != pred:
            return False
    return True


@dataclass
class Decision:
    taxon: str
    size_class: str
    jurisdiction: str
    allowed: list[str]
    recommended: list[str]
    prohibited: dict[str, list[str]]
    requirements: list[dict]
    obligations: list[dict]
    fired: list[str]
    citations: list[dict]
    flags: list[str] = field(default_factory=list)
    requires_legal_review: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class LawEngine:
    def __init__(self, rules_dir: str | Path | None = None):
        d = Path(rules_dir or RULES_DIR)
        doc = yaml.safe_load((d / "methods.yaml").read_text(encoding="utf-8"))
        self.methods: dict = doc["methods"]
        self.taxa: dict = doc["taxa"]
        self.size_limits: dict = doc["size_classes"]
        self.federal: dict = yaml.safe_load((d / "federal.yaml").read_text(encoding="utf-8"))
        self.jurisdictions: dict = {}
        for p in sorted(d.glob("*.yaml")):
            j = yaml.safe_load(p.read_text(encoding="utf-8"))
            if isinstance(j, dict) and "lists" in j:
                self.jurisdictions[j["pack"]] = j
        self._check_integrity()

    # --- справочники -------------------------------------------------------------------------
    def groups(self, method: str) -> list[str]:
        return self.methods[method]["groups"]

    def expand(self, items) -> list[str]:
        out: list[str] = []
        for it in items or []:
            if it.startswith("@"):
                out += [m for m, v in self.methods.items() if it[1:] in v["groups"]]
            elif it in self.methods:
                out.append(it)
            else:
                raise KeyError(f"неизвестный метод {it}")
        return list(dict.fromkeys(out))

    def _check_integrity(self) -> None:
        for r in self.federal["rules"]:
            assert r.get("cite"), f"правило {r['id']} без ссылки"
            self.expand(r.get("prohibit"))
            for key in r.get("require_if_method", {}):
                self.expand([key])
        for _taxon, v in self.taxa.items():
            for _size, plan in v["plan"].items():
                self.expand(plan)
            self.expand(v.get("heritage_fallback"))

    def size_class(self, area_m2) -> str:
        if _missing(area_m2):
            return "medium"
        if area_m2 < self.size_limits["small_lt_m2"]:
            return "small"
        if area_m2 >= self.size_limits["large_ge_m2"]:
            return "large"
        return "medium"

    # --- решение -------------------------------------------------------------------------------
    def decide(self, ctx: dict) -> Decision:
        taxon = ctx.get("taxon")
        if taxon not in self.taxa:
            raise ValueError(f"нет агротехники для вида {taxon!r}")
        prohibited: dict[str, list[str]] = {}
        requirements: list[dict] = []
        obligations: list[dict] = []
        fired: list[str] = []
        citations: list[dict] = []
        flags: list[str] = []
        review = False
        conditional: list[tuple[str, list[str], str]] = []

        for rule in self.federal["rules"]:
            if not match(rule.get("when", {}), ctx):
                continue
            fired.append(rule["id"])
            citations.append({"rule": rule["id"], "kind": rule["kind"], **rule["cite"]})
            for m in self.expand(rule.get("prohibit")):
                prohibited.setdefault(m, []).append(rule["id"])
            for text in rule.get("require", []):
                requirements.append({"text": text, "rule": rule["id"], "if_methods": None})
            for key, texts in rule.get("require_if_method", {}).items():
                for text in texts:
                    conditional.append((text, self.expand([key]), rule["id"]))
            if rule.get("obligation"):
                obligations.append({"text": rule["obligation"], "rule": rule["id"]})
                if rule["cite"].get("verified") is False:
                    review = True
            if rule.get("flag"):
                flags.append(rule["flag"])

        allowed = [m for m in self.methods if m not in prohibited]
        size = self.size_class(ctx.get("area_m2"))
        tx = self.taxa[taxon]
        plan = tx["plan"][size]
        recommended = [m for m in plan if m in allowed]
        if any(m in prohibited and "excavation" in self.groups(m) for m in plan):
            recommended = list(dict.fromkeys([m for m in tx["heritage_fallback"] if m in allowed] + recommended))
        if not recommended:
            recommended = [m for m in ("mowing", "umbel_removal") if m in allowed]

        for text, methods, rid in conditional:
            hit = [m for m in methods if m in allowed]
            if hit:
                requirements.append({"text": text, "rule": rid, "if_methods": hit})
        for text in tx["always"]:
            requirements.append({"text": text, "rule": f"agro-{taxon}", "if_methods": None})

        jur = ctx.get("jurisdiction") or "unknown"
        pack = self.jurisdictions.get(jur)
        if pack is None:
            flags.append("jurisdiction_unknown")
            review = True
        elif not pack.get("verified"):
            flags.append("jurisdiction_unverified")
            review = True
        else:
            listed = pack["lists"].get(taxon)
            if listed and listed.get("verified"):
                obligations.append({"text": f"Вид в перечне: {listed['act']}, {listed['ref']}", "rule": f"{jur}-list"})
                citations.append({"rule": f"{jur}-list", "kind": "norm", "act": listed["act"],
                                  "ref": listed["ref"], "verified": True})
            else:
                flags.append("taxon_not_listed")
                review = True
        if ctx.get("near_jurisdiction_boundary") is True:
            flags.append("jurisdiction_boundary")
            review = True
        if jur == "moscow_city" and ctx.get("in_protected") is True:
            flags.append("oopt_scope")
            review = True
        if jur == "moscow_city" and taxon == "solidago":
            flags.append("solidago_clause_3_2")
            review = True

        return Decision(taxon=taxon, size_class=size, jurisdiction=jur, allowed=allowed, recommended=recommended,
                        prohibited=prohibited, requirements=requirements, obligations=obligations, fired=fired,
                        citations=citations, flags=list(dict.fromkeys(flags)), requires_legal_review=review)

    def requirements_for(self, decision: dict | Decision, method: str) -> list[str]:
        d = decision.to_dict() if isinstance(decision, Decision) else decision
        return [r["text"] for r in d["requirements"] if r["if_methods"] is None or method in r["if_methods"]]

    def title(self, method: str) -> str:
        return self.methods[method]["title"]
