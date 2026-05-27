#!/usr/bin/env python3
"""
各分類コードの対角値 (within-class) と非対角値合計 (cross-class) を CSV に出力する。
"""
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

REFERENCE_DIR = Path("/mnt/eightthdd/uspto/all_pair/qwen_all_pairs")
SIMILAR_DIRS = [
    Path("/mnt/eightthdd/uspto/yes_pair/qwen/exact_match"),
    Path("/mnt/eightthdd/uspto/yes_pair/qwen/high_similar"),
    Path("/mnt/eightthdd/uspto/yes_pair/qwen/similar"),
]
OUT_DIR = Path("output")


def parse_class(raw: str) -> str:
    m = re.match(r"D\s*0*(\d+)", str(raw).strip(), re.I)
    if not m:
        return "D??"
    n = int(m.group(1))
    if (1 <= n <= 34) or n == 99:
        return f"D{n:02d}"
    return "D??"


def load_class_pairs(roots: list[Path]) -> tuple[defaultdict, defaultdict]:
    pair_cnt = defaultdict(int)
    cls_cnt = defaultdict(int)
    for root in roots:
        for jpath in sorted(root.rglob("*.jsonl")):
            with open(jpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    sc = parse_class(rec.get("source_class", ""))
                    tc = parse_class(rec.get("target_class", ""))
                    if sc == "D??" or tc == "D??":
                        continue
                    pair_cnt[(sc, tc)] += 1
                    cls_cnt[sc] += 1
                    cls_cnt[tc] += 1
    return pair_cnt, cls_cnt


def build_df(pair_cnt: defaultdict, cls_cnt: defaultdict, label: str) -> pd.DataFrame:
    all_cls = sorted(cls_cnt.keys())
    rows = []
    for cls in all_cls:
        diagonal = pair_cnt[(cls, cls)]
        cross = sum(pair_cnt[(cls, c)] for c in all_cls if c != cls)
        rows.append({"class": cls, f"{label}_diagonal": diagonal, f"{label}_cross_class": cross})
    return pd.DataFrame(rows)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading reference data ...")
    pair_ref, cls_ref = load_class_pairs([REFERENCE_DIR])

    print("Loading similar data ...")
    pair_sim, cls_sim = load_class_pairs(SIMILAR_DIRS)

    df_ref = build_df(pair_ref, cls_ref, "reference")
    df_sim = build_df(pair_sim, cls_sim, "similar")

    df = pd.merge(df_ref, df_sim, on="class", how="outer").fillna(0).astype(
        {"reference_diagonal": int, "reference_cross_class": int,
         "similar_diagonal": int, "similar_cross_class": int}
    )

    out_path = OUT_DIR / "diagonal_summary.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved → {out_path}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
