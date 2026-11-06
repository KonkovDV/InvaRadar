"""Citizen-photo verifier: is this report really Heracleum sosnowskyi / Solidago, or a look-alike?

Frozen ImageNet-pretrained backbone (Ultralytics YOLO11-cls) → embeddings → multinomial logistic regression.
Evaluation is observer-disjoint (GroupKFold by observer_id): no photographer appears in both train and test,
so the score reflects new volunteers, not memorised cameras or places.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from invaradar.config import DATA, OUT

W = sys.argv[1] if len(sys.argv) > 1 else "yolo11s-cls.pt"
root = DATA / "photos"
idx = pd.read_csv(root / "index.csv")
idx["path"] = [root / g / f"{p}.jpg" for g, p in zip(idx.group, idx.photo_id)]
idx = idx[[p.exists() and p.stat().st_size > 2000 for p in idx.path]].reset_index(drop=True)
emb_f = OUT / "photo" / f"emb_{Path(W).stem}.npy"; emb_f.parent.mkdir(parents=True, exist_ok=True)
if emb_f.exists():
    E = np.load(emb_f)
else:
    from ultralytics import YOLO
    m = YOLO(W)
    E = []
    for i in range(0, len(idx), 64):
        E += [e.cpu().numpy() for e in m.embed([str(p) for p in idx.path[i:i + 64]], imgsz=320, verbose=False)]
        print(i, flush=True)
    E = np.stack(E); np.save(emb_f, E)
y = idx.group.to_numpy(); g = idx.observer_id.to_numpy()
labels = sorted(np.unique(y))
col = {lab: i for i, lab in enumerate(labels)}
clf = make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=3000, class_weight="balanced"))
oof = np.empty(len(y), dtype=object); proba = np.zeros((len(y), len(labels)))
for tr, te in GroupKFold(5).split(E, y, g):
    c = clf.fit(E[tr], y[tr])
    oof[te] = c.predict(E[te])
    pr = c.predict_proba(E[te])
    # A fold that never saw one class has fewer columns. Write them by class, not by position.
    order = [col[k] for k in c.named_steps["logisticregression"].classes_]
    proba[np.ix_(te, order)] = pr
rep = classification_report(y, oof, labels=labels, output_dict=True)
cm = confusion_matrix(y, oof, labels=labels)
# binary view used by moderators: "target invasive" vs "not"
for tgt in ("heracleum", "solidago"):
    yt = y == tgt; pt = oof == tgt
    tp = int((yt & pt).sum()); fp = int((~yt & pt).sum()); fn = int((yt & ~pt).sum())
    rep[f"{tgt}_binary"] = {"precision": tp / max(tp + fp, 1), "recall": tp / max(tp + fn, 1)}
# share of reports a moderator no longer needs to see: confident (p>=0.9) predictions and their accuracy
pmax = proba.max(1); conf = pmax >= 0.9
rep["auto_triage"] = {"share_auto": float(conf.mean()),
                      "accuracy_on_auto": float((oof[conf] == y[conf]).mean()) if conf.any() else None}
res = {"backbone": W, "n_images": int(len(y)), "classes": labels, "confusion_matrix": cm.tolist(), "report": rep,
       "split": "5-fold GroupKFold by observer_id (observer-disjoint)"}
json.dump(res, open(OUT / "photo" / "metrics.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
joblib.dump({"clf": clf.fit(E, y), "backbone": W, "classes": labels}, OUT / "photo" / "verifier.joblib")
print(json.dumps({k: res["report"][k] for k in ["accuracy", "macro avg", "heracleum_binary", "solidago_binary",
                                                  "auto_triage"]}, ensure_ascii=False, indent=1))
print(cm)
