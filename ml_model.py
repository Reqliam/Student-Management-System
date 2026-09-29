import os
import csv
import math

import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import train_test_split

DATASET_PATH = "Engineering_Student_Semester_Data_500.csv"
MODEL_CACHE  = {"key": None, "model": None}
FEATURE_COLS = [
    "prev_sgpa", "prev_sem", "next_sem",
    "avg_sgpa", "last_delta", "trend3", "volatility",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def clamp(v):
    return round(max(0.0, min(10.0, v)), 2)


def safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def features(prev_sgpa, prev_sem, history):
    h = [float(v) for v in history if v is not None] or [float(prev_sgpa)]
    rm = sum(h[-4:]) / len(h[-4:])
    return {
        "prev_sgpa":  float(prev_sgpa),
        "prev_sem":   float(prev_sem),
        "next_sem":   float(prev_sem) + 1,
        "avg_sgpa":   sum(h) / len(h),
        "last_delta": (h[-1] - h[-2]) if len(h) >= 2 else 0.0,
        "trend3":     ((h[-1] - h[-3]) / 2) if len(h) >= 3
                      else ((h[-1] - h[-2]) if len(h) >= 2 else 0.0),
        "volatility": math.sqrt(
            sum((v - rm) ** 2 for v in h[-4:]) / len(h[-4:])
        ),
    }


# ── Data loading ──────────────────────────────────────────────────────────────

def _csv_rows():
    if not os.path.exists(DATASET_PATH):
        return []
    rows = []
    with open(DATASET_PATH, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [h.strip() for h in reader.fieldnames]
        for row in reader:
            row = {
                k.strip(): v.strip() if isinstance(v, str) else v
                for k, v in row.items()
            }
            s = [safe_float(row.get(f"S{i}_SGPA")) for i in range(1, 9)]
            for i in range(1, 8):
                if s[i - 1] is None or s[i] is None:
                    continue
                r = features(s[i - 1], i, s[:i])
                r["target"] = s[i]
                rows.append(r)
    return rows


def _db_rows(db):
    rows = []
    by = {}
    for r in db.execute(
        "SELECT student_id,semester_no,score FROM student_scores "
        "ORDER BY student_id,semester_no"
    ).fetchall():
        by.setdefault(r["student_id"], []).append(
            (int(r["semester_no"]), float(r["score"]))
        )
    for hist in by.values():
        h = []
        for i in range(len(hist) - 1):
            sn, sc = hist[i]
            h.append(sc)
            r = features(sc, sn, h)
            r["target"] = hist[i + 1][1]
            rows.append(r)
    return rows


# ── Model ─────────────────────────────────────────────────────────────────────

def get_model(db):
    key = (
        ("csv", os.path.getmtime(DATASET_PATH))
        if os.path.exists(DATASET_PATH)
        else ("db", db.execute("SELECT COUNT(*) FROM student_scores").fetchone()[0])
    )
    if MODEL_CACHE["key"] == key and MODEL_CACHE["model"]:
        return MODEL_CACHE["model"]

    rows = _csv_rows() or _db_rows(db)
    null = {
        "model": None, "confidence": "Low",
        "mae": 0, "r2": 0, "samples": len(rows),
    }
    if len(rows) < 15:
        MODEL_CACHE.update({"key": key, "model": null})
        return null

    df = pd.DataFrame(rows)
    X  = df[FEATURE_COLS]
    y  = df["target"].to_numpy()
    rf = RandomForestRegressor(
        n_estimators=320, max_depth=14,
        min_samples_leaf=2, random_state=42, n_jobs=-1,
    )

    if len(df) >= 120:
        Xt, Xe, yt, ye = train_test_split(X, y, test_size=0.2, random_state=42)
        m = clone(rf); m.fit(Xt, yt); p = m.predict(Xe)
        mae = float(mean_absolute_error(ye, p))
        r2  = float(r2_score(ye, p))
    else:
        m = clone(rf); m.fit(X, y); p = m.predict(X)
        mae = float(mean_absolute_error(y, p))
        r2  = float(r2_score(y, p))

    fm = clone(rf); fm.fit(X, y)
    conf = (
        "High"   if len(rows) >= 2500 and mae <= 0.55 else
        "Medium" if len(rows) >= 500  and mae <= 0.95 else
        "Low"
    )
    bundle = {"model": fm, "confidence": conf, "mae": mae, "r2": r2, "samples": len(rows)}
    MODEL_CACHE.update({"key": key, "model": bundle})
    return bundle


def predict(prev_score, prev_sem, model, history=None):
    if prev_score is None:
        return None
    if model["model"] is None:
        return clamp(float(prev_score))
    f = features(float(prev_score), int(prev_sem), history or [float(prev_score)])
    return clamp(
        float(model["model"].predict(pd.DataFrame([f])[FEATURE_COLS])[0])
    )