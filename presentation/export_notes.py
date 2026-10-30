"""Speaker notes from the built deck → SPEAKER_NOTES.md, so the text never drifts from the slides.
usage: python export_notes.py InvaRadar_Ecopremia2026.pptx SPEAKER_NOTES.md"""
import sys

from pptx import Presentation

src, dst = sys.argv[1], sys.argv[2]
prs = Presentation(src)
out = ["# ИнваРадар — текст выступления", "",
       "Заметки докладчика по каждому слайду полной версии презентации. Слайды 1–20 — основное выступление "
       "(5–7 минут), 21–27 — приложение для вопросов. Файл создаётся из PPTX скриптом `export_notes.py`.", ""]
for i, slide in enumerate(prs.slides, 1):
    title = next((sh.text_frame.text for sh in slide.placeholders if sh.placeholder_format.type == 1), "") \
        if slide.placeholders else ""
    if not title:  # cover: the largest text on the slide
        texts = [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        title = "ИнваРадар" if any("ИнваРадар" == t.strip() for t in texts) else (texts[0] if texts else "")
    notes = slide.notes_slide.notes_text_frame.text.strip() if slide.has_notes_slide else ""
    out += [f"## {i}. {title.strip()}", "", notes or "—", ""]
open(dst, "w", encoding="utf-8").write("\n".join(out))
print(f"{len(prs.slides)} slides → {dst}")
