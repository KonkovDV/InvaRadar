"""Markdown documents → PDF (A4) in the deck's typography, printed by headless Chromium (Playwright).
usage: python docs/build_pdfs.py            (needs `pip install markdown` and Node with `playwright`)"""
import json
import subprocess
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / "presentation" / "fonts"
DOCS = {
    "PLAN": ROOT / "docs" / "PLAN.md",
    "SCIENCE": ROOT / "docs" / "SCIENCE.md",
    "EXPERIMENTS": ROOT / "docs" / "EXPERIMENTS.md",
    "MODEL_CARD": ROOT / "docs" / "MODEL_CARD.md",
    "LANDSCAPE": ROOT / "docs" / "LANDSCAPE.md",
    "SOURCES": ROOT / "docs" / "SOURCES.md",
    "SPEAKER_NOTES": ROOT / "presentation" / "SPEAKER_NOTES.md",
}
CSS = """
@font-face { font-family: Literata; src: url('{F}/Literata-600.ttf'); font-weight: 600; }
@font-face { font-family: Literata; src: url('{F}/Literata-400Italic.ttf'); font-style: italic; }
@font-face { font-family: Golos; src: url('{F}/GolosText-400.ttf'); }
@font-face { font-family: Golos; src: url('{F}/GolosText-600.ttf'); font-weight: 600; }
@font-face { font-family: Mono; src: url('{F}/JetBrainsMono-400.ttf'); }
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
body { font-family: Golos, Arial, sans-serif; font-size: 10.5pt; line-height: 1.45; color: #14231D; }
h1, h2, h3 { font-family: Literata, Georgia, serif; font-weight: 600; color: #0F2A22; line-height: 1.2; }
h1 { font-size: 21pt; margin: 0 0 10pt; } h2 { font-size: 14pt; margin: 18pt 0 6pt; border-top: 1px solid #DCE3DD; padding-top: 10pt; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9pt; page-break-inside: auto; }
th { font-family: Mono, monospace; font-size: 7.5pt; text-transform: uppercase; letter-spacing: .04em; color: #2F6B55;
     text-align: left; border-bottom: 1.2px solid #2F6B55; padding: 4pt 5pt; }
td { border-bottom: .6px solid #DCE3DD; padding: 4pt 5pt; vertical-align: top; }
tr { page-break-inside: avoid; }
code, pre { font-family: Mono, monospace; font-size: 8.5pt; background: #EEF2EE; border-radius: 3px; }
code { padding: 0 3px; } pre { padding: 8pt; white-space: pre-wrap; }
a { color: #2F6B55; text-decoration: none; } em { font-family: Literata, Georgia, serif; font-style: italic; }
blockquote { border-left: 3px solid #E0A030; margin: 8pt 0; padding: 2pt 10pt; color: #5B6B63; }
"""
NODE = """
const { chromium } = require('playwright');
(async () => {
  const jobs = JSON.parse(process.argv[1]);
  const b = await chromium.launch();
  const p = await b.newPage();
  for (const [html, pdf] of jobs) {
    await p.goto('file://' + html, { waitUntil: 'networkidle' });
    await p.pdf({ path: pdf, format: 'A4', printBackground: true, preferCSSPageSize: true,
      displayHeaderFooter: true, headerTemplate: '<span></span>',
      footerTemplate: '<div style="font-size:7pt;color:#5B6B63;width:100%;text-align:center">ИнваРадар · <span class="pageNumber"></span> / <span class="totalPages"></span></div>' });
  }
  await b.close();
})();
"""

out = ROOT / "docs" / "pdf"; out.mkdir(exist_ok=True)
jobs = []
with tempfile.TemporaryDirectory() as tmp:
    for name, src in DOCS.items():
        body = markdown.markdown(src.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])
        html = Path(tmp) / f"{name}.html"
        html.write_text(f"<!doctype html><meta charset='utf-8'><style>{CSS.replace('{F}', FONTS.as_uri())}</style>{body}",
                        encoding="utf-8")
        jobs.append([str(html), str(out / f"{name}.pdf")])
    subprocess.run(["node", "-e", NODE, json.dumps(jobs)], check=True)
for _, pdf in jobs:
    print(pdf)
