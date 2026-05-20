#!/usr/bin/env python3
"""
パイプライン状態チェック

qwen_similarity_results/ と all.jsonl の状態を確認し、
実行が必要なコマンドを出力する。

実行:
    python check_pipeline_state.py
    python check_pipeline_state.py --class D10
"""

import argparse
import json
from collections import Counter
from pathlib import Path

QWEN_DIR   = Path("/mnt/eightthdd/uspto/qwen_similarity_results")
CLASS_BASE = Path("/mnt/eightthdd/uspto/class")


def check_qwen(years: list[str]) -> tuple[dict[str, int], bool]:
    """各年の判定件数と、all.jsonl より新しいファイルが存在するかを返す。"""
    counts: dict[str, int] = {}
    for year in years:
        fp = QWEN_DIR / f"{year}.jsonl"
        counts[year] = sum(1 for l in fp.read_text().splitlines() if l.strip()) if fp.exists() else 0
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="パイプライン状態チェック")
    parser.add_argument("--class", dest="target_class", default="D18", metavar="CLASS")
    parser.add_argument("--sim", default="cosine_numpy",
                        choices=["cosine_numpy", "cosine_faiss"])
    args = parser.parse_args()

    rank_dir  = CLASS_BASE / args.target_class / "rank_results" / args.sim
    all_jsonl = CLASS_BASE / args.target_class / "rank_judgments" / args.sim / "all.jsonl"

    issues: list[str] = []

    # ---- rank_results の存在確認 ----
    rank_files = sorted(rank_dir.glob("[0-9]*.jsonl")) if rank_dir.exists() else []
    years = [f.stem for f in rank_files]

    print(f"=== クラス: {args.target_class}  類似度: {args.sim} ===\n")

    if not rank_files:
        print(f"[ERROR] rank_results が見つかりません: {rank_dir}")
        print("  → Step 1〜4 を実行してください:\n")
        print(f"    cd /home/sonozuka/design_similarity")
        print(f"    python vector/run_pipeline.py --class {args.target_class} --no-gpu")
        return

    print(f"rank_results: {years[0]}〜{years[-1]}  ({len(years)} 年分)\n")

    # ---- qwen_similarity_results の状態 ----
    qwen_counts = check_qwen(years)
    total_qwen  = sum(qwen_counts.values())
    done_years  = [y for y, c in qwen_counts.items() if c > 0]
    empty_years = [y for y, c in qwen_counts.items() if c == 0]

    print("--- qwen_similarity_results/ ---")
    for year, count in qwen_counts.items():
        status = "完了" if count > 0 else "未処理"
        print(f"  {year}.jsonl: {count:>6,} 件  [{status}]")
    print(f"  合計: {total_qwen:,} 件  (判定済み {len(done_years)} 年 / 未処理 {len(empty_years)} 年)\n")

    # ---- all.jsonl の状態 ----
    print("--- all.jsonl ---")
    if not all_jsonl.exists():
        print(f"  [MISSING] {all_jsonl}\n")
        issues.append("all.jsonl が存在しない")
    else:
        mtime = all_jsonl.stat().st_mtime

        # all.jsonl より新しい qwen ファイルがあるか
        stale_years = [
            y for y in done_years
            if (QWEN_DIR / f"{y}.jsonl").stat().st_mtime > mtime
        ]

        lines = [l for l in all_jsonl.read_text().splitlines() if l.strip()]
        counts = Counter(json.loads(l)["judgment"] for l in lines)
        import datetime
        mtime_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")

        print(f"  更新日時 : {mtime_str}")
        print(f"  合計     : {len(lines):,} 件")
        for label in ("Yes", "No", "Unknown"):
            print(f"    {label:<8}: {counts.get(label, 0):,} 件")

        if stale_years:
            print(f"\n  [STALE] all.jsonl より新しい qwen ファイルあり: {stale_years}")
            issues.append(f"qwen_similarity_results/ が更新されている ({', '.join(stale_years)})")
        else:
            print("\n  [OK] all.jsonl は最新です")

    # ---- 実行が必要なコマンド ----
    if issues:
        print("\n=== 実行が必要なコマンド ===\n")
        for i, issue in enumerate(issues, 1):
            print(f"  問題 {i}: {issue}")
        print()
        print("  cd /home/sonozuka/design_similarity")
        print(f"  python vector/run_pipeline.py --class {args.target_class} --steps 5 --no-resume")
    else:
        print("\n=== 対応不要 ===")


if __name__ == "__main__":
    main()