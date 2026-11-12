"""Regional invasive-plant lists used by the work order.

Moscow city resolution 369-PP of 3 March 2026 is recorded from the GARANT card
(https://base.garant.ru/413816164/), checked on 30 October 2026. That card names group I as
including Sosnowsky's hogweed and both goldenrods. The Moscow oblast list was not checked
against an official text, so it stays unverified and does not authorise a duty.
"""
from __future__ import annotations

CHECKED_ON = "2026-10-30"

REGIMES = {
    "moscow_city": {
        "act": "Постановление Правительства Москвы от 03.03.2026 № 369-ПП",
        "url": "https://base.garant.ru/413816164/",
        "checked_on": CHECKED_ON,
        "verified": True,
        "taxa": frozenset({"heracleum", "solidago"}),
        "duty": "правообладатель или балансодержатель участка",
    },
    "moscow_oblast": {
        "act": "",
        "url": "",
        "checked_on": CHECKED_ON,
        "verified": False,
        "taxa": frozenset(),
        "duty": "",
    },
}

# Norms the work-order text cites. `verified` means the rule was read in an official or GARANT text.
NORMS = (
    {"id": "vk-65", "title": "Водный кодекс РФ", "article": "ст. 65", "verified": True, "checked_on": CHECKED_ON},
    {"id": "sanpin-272", "title": "СанПиН 2.1.3684-21", "article": "п. 272", "verified": True, "checked_on": CHECKED_ON},
    {"id": "sanpin-273", "title": "СанПиН 2.1.3684-21", "article": "п. 273", "verified": True, "checked_on": CHECKED_ON},
    {"id": "sanpin-282", "title": "СанПиН 2.1.3684-21", "article": "п. 282", "verified": True, "checked_on": CHECKED_ON},
    {"id": "fz-490-16", "title": "490-ФЗ", "article": "ст. 16", "verified": True, "checked_on": CHECKED_ON},
    {"id": "fz-73-36", "title": "73-ФЗ", "article": "ст. 36", "verified": True, "checked_on": CHECKED_ON},
    {"id": "fz-294", "title": "294-ФЗ", "article": "", "verified": True, "checked_on": CHECKED_ON},
    {"id": "moscow-369", "title": "369-ПП", "article": "", "verified": True, "checked_on": CHECKED_ON},
    {"id": "koap-moscow-4-17", "title": "КоАП Москвы", "article": "ч. 4 ст. 4.17", "verified": False, "checked_on": CHECKED_ON},
)


def listed_act(jurisdiction: str, taxon: str, protected: bool = False,
               boundary_m: float | None = None) -> str:
    """What the work order may say about a legal duty to control this taxon here.

    369-ПП names a species and applies on Moscow's green fund, not on protected areas.
    A point within 50 m of the city boundary in the jurisdiction file is too close to assign the duty.
    Appendix 2 clause 3.2 of 369-ПП is deferred to 2027-01-01 for goldenrod.
    """
    regime = REGIMES.get(jurisdiction)
    if regime is None:
        return "юрисдикция не определена"
    if boundary_m is not None and boundary_m < 50:
        return "участок ближе 50 м к границе юрисдикций: акт не применяется, пока юрист не сверит участок"
    if not regime["verified"]:
        return "перечень этой юрисдикции не сверен с официальным текстом"
    if taxon not in regime["taxa"]:
        return "вне обязательного перечня — по решению правообладателя"
    notes = []
    if protected:
        notes.append("порядок 369-ПП не действует на ООПТ, а слой охраны смешивает парк и резерват — нужен юрист")
    if taxon == "solidago":
        notes.append("пункт 3.2 приложения 2 для золотарников применяется с 01.01.2027, содержание пункта сверяет юрист")
    if not notes:
        return regime["act"]
    return regime["act"] + "; " + "; ".join(notes)
