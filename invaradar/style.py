"""Shared look of figures and slides: palette and fonts (Literata, Golos Text, JetBrains Mono — SIL OFL 1.1)."""
from __future__ import annotations

from pathlib import Path

PAPER = "#F4F6F1"
INK = "#14231D"
FOREST = "#0F2A22"
MUTED = "#5B6B63"
MOSS = "#2F6B55"
SAGE = "#7F9B88"
AMBER = "#E0A030"
RUST = "#B4532A"
GOLD = "#D4B02A"
WATER = "#3D7EA6"
WATER_LIGHT = "#BFD3DA"
HOT = ["#F3D9A0", "#E0A030", "#C4561F", "#7A1E12"]

FONTS = Path(__file__).resolve().parents[1] / "presentation" / "fonts"


def use_fonts() -> None:
    """Register the deck fonts with matplotlib and make Golos Text the default."""
    import matplotlib as mpl
    from matplotlib import font_manager

    for f in FONTS.glob("*.ttf"):
        font_manager.fontManager.addfont(str(f))
    mpl.rcParams["font.family"] = "Golos Text"
    mpl.rcParams["axes.unicode_minus"] = False
    mpl.rcParams["mathtext.fontset"] = "dejavusans"  # Greek letters in formulas


def scale_bar(ax, x0: float, y0: float, length_m: float, label: str, color: str = INK, lw: float = 3.0) -> None:
    """Plain cartographic scale bar in map units (metres), on a paper halo so routes and data never cover it."""
    import matplotlib.patheffects as pe

    halo = [pe.withStroke(linewidth=lw + 4, foreground=PAPER)]
    ax.plot([x0, x0 + length_m], [y0, y0], color=color, lw=lw, solid_capstyle="butt", zorder=30, path_effects=halo)
    ax.text(x0 + length_m / 2, y0 + length_m * 0.06, label, ha="center", va="bottom", fontsize=11, color=color,
            fontfamily="JetBrains Mono", zorder=30, path_effects=[pe.withStroke(linewidth=4, foreground=PAPER)])
