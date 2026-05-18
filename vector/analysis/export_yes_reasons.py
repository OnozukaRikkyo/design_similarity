#!/usr/bin/env python3
"""
Yes 判定かつ指定類似度以上のペアを全フィールド付きで CSV に出力する。

入力:
    class/{CLASS}/rank_judgments/{sim_func}/all.jsonl

出力:
    vector/output/{CLASS}/{sim_func}/yes_sim{threshold}_reasons.csv

実行:
    python vector/analysis/export_yes_reasons.py --class D18
    python vector/analysis/export_yes_reasons.py --class D18 --min-sim 0.9
    python vector/analysis/export_yes_reasons.py --class D10 --sim cosine_faiss
"""

import argparse
import csv
import json
from pathlib import Path

CLASS_BASE = Path("/mnt/eightthdd/uspto/class")
OUT_BASE   = Path("/home/sonozuka/design_similarity/vector/output")

FIELDS = [
    "source", "target", "type",
    "rank", "n_candidates", "similarity",
    "judgment", "confidence", "reason",
    "source_image", "target_image",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Yes 判定かつ指定類似度以上のペアを CSV に出力する"
    )
    parser.add_argument("--class", dest="target_class", default="D18", metavar="CLASS")
    parser.add_argument("--sim",   default="cosine_numpy",
                        choices=["cosine_numpy", "cosine_faiss"])
    parser.add_argument("--min-sim", type=float, default=0.8,
                        help="コサイン類似度の下限（デフォルト: 0.8）")
    args = parser.parse_args()

    in_path = CLASS_BASE / args.target_class / "rank_judgments" / args.sim / "all.jsonl"
    if not in_path.exists():
        raise FileNotFoundError(
            f"{in_path} が見つかりません。先に join_judgments.py を実行してください。"
        )

    recs = [json.loads(l) for l in in_path.read_text().splitlines() if l.strip()]
    filtered = [
        r for r in recs
        if r["judgment"] == "Yes" and r["similarity"] >= args.min_sim
    ]
    filtered.sort(key=lambda r: (r["rank"], -r["similarity"]))

    threshold_str = f"{args.min_sim:.2f}".replace(".", "")
    out_path = (
        OUT_BASE / args.target_class / args.sim
        / f"yes_sim{threshold_str}_reasons.csv"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(filtered)

    print(f"出力: {out_path}")
    print(f"件数: {len(filtered)} 件  (judgment=Yes, similarity >= {args.min_sim})")


if __name__ == "__main__":
    main()
