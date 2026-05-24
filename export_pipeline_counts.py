#!/usr/bin/env python3
"""
論文テーブル "Summary counts for the citation-judgment-retrieval pipeline"
の元データ CSV を生成する。

出力: output/pipeline_counts.csv

動的に取得する値:
  - diagonal_summary.csv         → 引用ペア数・MLLM類似ペア数
  - rank_index/perspective/      → D18ユニーク特許数
  - rank_judgments/.../all.jsonl → D18 citation-pair 総数・perspective 内訳

静的な値（IMPACT データセット定数）はスクリプト内に直書きする。
"""

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
BASE        = Path(__file__).resolve().parent
CLASS_BASE  = Path("/mnt/eightthdd/uspto/class")

DIAGONAL_CSV  = BASE / "output" / "diagonal_summary.csv"
RANK_INDEX    = CLASS_BASE / "D18" / "rank_index" / "perspective" / "patent_ids.npy"
ALL_JSONL     = CLASS_BASE / "D18" / "rank_judgments" / "cosine_numpy" / "all.jsonl"
OUT_PATH      = BASE / "output" / "pipeline_counts.csv"

# ---------------------------------------------------------------------------
# IMPACT データセット定数（変更不要）
# ---------------------------------------------------------------------------
IMPACT_PATENTS  = 435_101
IMPACT_FIGURES  = 3_609_805
IMPACT_YEAR_MIN = 2007
IMPACT_YEAR_MAX = 2022
EMBED_DIM       = 2048


# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------
def load_diagonal() -> pd.DataFrame:
    return pd.read_csv(DIAGONAL_CSV)


def load_rank_index_count() -> int:
    return len(np.load(RANK_INDEX))


def load_all_jsonl_counts() -> tuple[int, Counter]:
    """(total_records, perspective_judgment_counter) を返す。"""
    records = [
        json.loads(l)
        for l in ALL_JSONL.read_text().splitlines()
        if l.strip()
    ]
    persp_cnt = Counter(
        r["judgment"] for r in records if r.get("type") == "perspective"
    )
    return len(records), persp_cnt


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    diag        = load_diagonal()
    unique_pats = load_rank_index_count()
    total_recs, persp_cnt = load_all_jsonl_counts()

    ref_within  = int(diag["reference_diagonal"].sum())
    ref_cross   = int(diag["reference_cross_class"].sum())
    sim_within  = int(diag["similar_diagonal"].sum())
    sim_cross   = int(diag["similar_cross_class"].sum())

    rows = [
        # --- IMPACT dataset ---
        ("IMPACT dataset",                        "U.S. design patents",       IMPACT_PATENTS),
        ("IMPACT dataset",                        "Publication years",          f"{IMPACT_YEAR_MIN}--{IMPACT_YEAR_MAX}"),
        ("IMPACT dataset",                        "Patent drawing figures",     IMPACT_FIGURES),
        ("IMPACT metadata",                       "Image format",               "TIF"),
        ("IMPACT metadata",                       "View types",                 "Perspective/orthographic"),
        # --- 引用ペア ---
        ("Full examiner-citation reference set",  "Citation pairs, all classes", ref_within + ref_cross),
        ("Full examiner-citation reference set",  "Within-class pairs",          ref_within),
        ("Full examiner-citation reference set",  "Cross-class pairs",           ref_cross),
        # --- MLLM 類似ペア ---
        ("MLLM-judged similar pairs",             "Total",                       sim_within + sim_cross),
        ("MLLM-judged similar pairs",             "Within-class pairs",          sim_within),
        ("MLLM-judged similar pairs",             "Cross-class pairs",           sim_cross),
        # --- D18 埋め込みインデックス ---
        ("D18 embedding index",                   "Unique patents",              unique_pats),
        ("D18 embedding index",                   "Citation-pair records",       total_recs),
        ("D18 embedding index",                   "Embedding dimension",         EMBED_DIM),
        # --- Retrieval evaluation（Yes / No のみ）---
        ("Retrieval evaluation, perspective view","MLLM-similar pairs",          persp_cnt["Yes"]),
        ("Retrieval evaluation, perspective view","MLLM-non-similar pairs",      persp_cnt["No"]),
        # --- Scatter-plot analysis（Yes / No / Unknown 全て）---
        ("Scatter-plot analysis, D18",            "Similar pairs",               persp_cnt["Yes"]),
        ("Scatter-plot analysis, D18",            "Non-similar pairs",           persp_cnt["No"]),
        ("Scatter-plot analysis, D18",            "Unknown or unparsed pairs",   persp_cnt["Unknown"]),
    ]

    df = pd.DataFrame(rows, columns=["stage", "item", "count"])
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    print(f"Saved → {OUT_PATH}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
