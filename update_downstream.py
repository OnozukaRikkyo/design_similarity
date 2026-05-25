#!/usr/bin/env python3
"""
design_similarity パイプライン 一括実行スクリプト

【通常の更新（qwen_similarity_results/ が進んだとき）】
  cd /home/sonozuka/design_similarity
  python update_downstream.py

【新しいクラスや年を追加したとき（ベクトルインデックスから再構築）】
  python update_downstream.py --with-vector --no-gpu

【グラフ解析も含めて更新】
  python update_downstream.py --with-graph

【部分実行】
  python update_downstream.py --from-step G   # G 以降のみ
  python update_downstream.py --steps H F     # 指定ステップのみ
  python update_downstream.py --class D10     # 別クラス

─────────────────────────────────────────────────────────────────
実行順序と依存関係:

  [ベクトルインデックス（--with-vector 時のみ）]
  V1: vector/filter_pairs_by_class.py  → class/{CLASS}/cited_image_pairs/
  V2: vector/build_class_vectors.py    → class/{CLASS}/cited_image_vectors/
  V3: vector/build_rank_index.py       → class/{CLASS}/rank_index/
  V4: vector/compute_ranks.py          → class/{CLASS}/rank_results/

  [上流パイプライン（resume: 処理済みペアをスキップ）]
  A: extract_all_pairs.py              → all_pair/qwen_all_pairs/
  B: extract_yes_pairs.py              → yes_pair/qwen_yes_pairs/
  C: analysis/split_by_reason.py       → yes_pair/qwen/{exact_match,...}/

  [集計・可視化（全件上書き）]
  D: export_diagonal_csv.py            → output/diagonal_summary.csv     ← A,B,C に依存
  E: make_two_heatmaps.py              → output/heatmap_*.png            ← A,C に依存

  [ベクトル検索結合（全件上書き）]
  G: vector/join_judgments.py          → class/{CLASS}/rank_judgments/{SIM}/all.jsonl

  [分析・可視化（全件上書き）]  ← G に依存
  H: vector/analysis/rank_analysis.py  → vector/output/{CLASS}/{SIM}/
       sim_histogram_{type}.png        ← コサイン類似度分布
       rank_ccdf_{type}.png
       rank_scatter_{type}.png
       rank_density_{type}*.png
       high_sim_{type}_0950*.csv
  I: vector/analysis/export_yes_reasons.py      → yes_sim080_reasons.csv
  J: vector/analysis/export_non_exact_pairs.py  → rank_analysis/.../non_exact_pairs/

  [論文テーブル集計（全件上書き）]  ← D と G の両方に依存
  F: export_pipeline_counts.py         → output/pipeline_counts.csv

  [グラフ解析（--with-graph 時のみ）]  ← G に依存
  K: graph/graph_analysis.py           → graph/output/{CLASS}/triadic_scored.jsonl
  L: graph/extract_high_sim_triads.py  → graph/output/{CLASS}/high_sim_triads/
  M: graph/verify/wcc_scoring.py       → graph/output/{CLASS}/verify/
─────────────────────────────────────────────────────────────────
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent

# デフォルト実行順（依存関係に基づく。アルファベット順ではない）
STEPS_VECTOR  = ["V1", "V2", "V3", "V4"]
STEPS_DEFAULT = ["A", "B", "C", "D", "E", "G", "H", "I", "J", "F"]
STEPS_GRAPH   = ["K", "L", "M"]
ALL_STEPS     = STEPS_VECTOR + STEPS_DEFAULT + STEPS_GRAPH

STEP_LABELS = {
    "V1": "filter_pairs_by_class    → class/{CLASS}/cited_image_pairs/",
    "V2": "build_class_vectors      → class/{CLASS}/cited_image_vectors/",
    "V3": "build_rank_index         → class/{CLASS}/rank_index/",
    "V4": "compute_ranks            → class/{CLASS}/rank_results/",
    "A":  "extract_all_pairs        → all_pair/qwen_all_pairs/",
    "B":  "extract_yes_pairs        → yes_pair/qwen_yes_pairs/",
    "C":  "split_by_reason          → yes_pair/qwen/{exact_match,high_similar,similar}/",
    "D":  "export_diagonal_csv      → output/diagonal_summary.csv",
    "E":  "make_two_heatmaps        → output/heatmap_*.png",
    "G":  "join_judgments           → class/{CLASS}/rank_judgments/{SIM}/all.jsonl",
    "H":  "rank_analysis            → vector/output/{CLASS}/{SIM}/",
    "I":  "export_yes_reasons       → vector/output/{CLASS}/{SIM}/yes_sim080_reasons.csv",
    "J":  "export_non_exact_pairs   → rank_analysis/{CLASS}/{SIM}/non_exact_pairs/",
    "F":  "export_pipeline_counts   → output/pipeline_counts.csv",
    "K":  "graph_analysis           → graph/output/{CLASS}/triadic_scored.jsonl",
    "L":  "extract_high_sim_triads  → graph/output/{CLASS}/high_sim_triads/",
    "M":  "wcc_scoring              → graph/output/{CLASS}/verify/",
}


def run(cmd: list[str], cwd: Path = BASE) -> None:
    print(f"\n  $ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(cwd))
    if result.returncode != 0:
        print(f"\n[ERROR] 終了コード {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def label(step: str, cls: str, sim: str) -> str:
    return STEP_LABELS[step].replace("{CLASS}", cls).replace("{SIM}", sim)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="design_similarity パイプラインを一括実行する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--steps", nargs="+", choices=ALL_STEPS, metavar="STEP",
        help="実行するステップを個別指定（例: --steps G H F）",
    )
    parser.add_argument(
        "--from-step", choices=ALL_STEPS, metavar="STEP",
        help="指定ステップ以降を連続実行",
    )
    parser.add_argument(
        "--with-vector", action="store_true",
        help="ベクトルインデックス再構築（V1〜V4）を先頭に追加。新クラス・新年追加時のみ必要",
    )
    parser.add_argument(
        "--with-graph", action="store_true",
        help="グラフ解析（K〜M）を末尾に追加",
    )
    parser.add_argument(
        "--no-gpu", action="store_true",
        help="V2（build_class_vectors）で GPU を使わない（既存ベクトルのコピーのみ）",
    )
    parser.add_argument(
        "--class", dest="target_class", default="D18",
        help="対象クラス（Step V1〜V4, G〜M）。デフォルト: D18",
    )
    parser.add_argument(
        "--sim", default="cosine_numpy", choices=["cosine_numpy", "cosine_faiss"],
        help="類似度関数（Step V4, G〜M）。デフォルト: cosine_numpy",
    )
    args = parser.parse_args()
    cls = args.target_class
    sim = args.sim

    # 実行ステップを決定
    base_steps = (
        (STEPS_VECTOR if args.with_vector else [])
        + STEPS_DEFAULT
        + (STEPS_GRAPH if args.with_graph else [])
    )

    if args.from_step:
        idx = ALL_STEPS.index(args.from_step)
        target_steps = [s for s in ALL_STEPS[idx:] if s in base_steps]
    elif args.steps:
        target_steps = [s for s in ALL_STEPS if s in args.steps]
    else:
        target_steps = base_steps

    print("=" * 64)
    print("design_similarity パイプライン実行")
    print(f"実行ステップ : {' '.join(target_steps)}")
    print(f"クラス / 類似度: {cls} / {sim}")
    print("=" * 64)

    t0 = time.time()

    for step in target_steps:
        print(f"\n[Step {step}] {label(step, cls, sim)}")
        t_step = time.time()

        if step == "V1":
            run([sys.executable, "vector/filter_pairs_by_class.py", "--class", cls])

        elif step == "V2":
            cmd = [sys.executable, "vector/build_class_vectors.py", "--class", cls]
            if args.no_gpu:
                cmd.append("--no-gpu")
            run(cmd)

        elif step == "V3":
            run([sys.executable, "vector/build_rank_index.py", "--class", cls])

        elif step == "V4":
            run([sys.executable, "vector/compute_ranks.py", "--class", cls, "--sim", sim])

        elif step == "A":
            run([sys.executable, "extract_all_pairs.py"])

        elif step == "B":
            run([sys.executable, "extract_yes_pairs.py"])

        elif step == "C":
            run([sys.executable, "analysis/split_by_reason.py"])

        elif step == "D":
            run([sys.executable, "export_diagonal_csv.py"])

        elif step == "E":
            run([sys.executable, "make_two_heatmaps.py"])

        elif step == "G":
            run([
                sys.executable, "vector/join_judgments.py",
                "--class", cls, "--sim", sim, "--no-resume",
            ])

        elif step == "H":
            run([sys.executable, "vector/analysis/rank_analysis.py", "--class", cls, "--sim", sim])

        elif step == "I":
            run([sys.executable, "vector/analysis/export_yes_reasons.py", "--class", cls])

        elif step == "J":
            run([sys.executable, "vector/analysis/export_non_exact_pairs.py", "--class", cls])

        elif step == "F":
            run([sys.executable, "export_pipeline_counts.py"])

        elif step == "K":
            run([sys.executable, "graph/graph_analysis.py"])

        elif step == "L":
            run([sys.executable, "graph/extract_high_sim_triads.py"])

        elif step == "M":
            run([sys.executable, "graph/verify/wcc_scoring.py"])

        print(f"  [Step {step} 完了: {time.time() - t_step:.1f}s]")

    print(f"\n{'=' * 64}")
    print(f"完了: {time.time() - t0:.1f}s  ({' '.join(target_steps)})")
    print("=" * 64)


if __name__ == "__main__":
    main()
