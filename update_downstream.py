#!/usr/bin/env python3
"""
judge_cited_pairs.py が出力を更新したとき、下流データを一括更新する。

年指定不要。新しい年のデータは自動検出される（glob ベース）。
処理済みペアのスキップ（resume）は各スクリプト側で実装済み。

実行順序と依存関係:
  [上流パイプライン]
  A: extract_all_pairs.py       → all_pair/qwen_all_pairs/            resume
  B: extract_yes_pairs.py       → yes_pair/qwen_yes_pairs/ + 画像      resume
  C: analysis/split_by_reason.py→ yes_pair/qwen/{exact_match,...}/     resume
  D: export_diagonal_csv.py     → output/diagonal_summary.csv          全件上書き（A/B/C に依存）
  E: make_two_heatmaps.py       → output/heatmap_*.png                 全件上書き（A/B/C に依存）

  [ベクトル検索パイプライン]
  G: vector/join_judgments.py   → class/D18/rank_judgments/.../all.jsonl 全件上書き
  H: vector/analysis/rank_analysis.py       → vector/output/D18/       全件上書き（G に依存）
  I: vector/analysis/export_yes_reasons.py  → vector/output/D18/       全件上書き（G に依存）
  J: vector/analysis/export_non_exact_pairs.py → rank_analysis/.../non_exact/ 全件上書き（G に依存）

  [集計（D と G 両方に依存するため最後に実行）]
  F: export_pipeline_counts.py  → output/pipeline_counts.csv           全件上書き（D・G に依存）

  [グラフ解析パイプライン（--with-graph 指定時のみ）]
  K: graph/graph_analysis.py    → graph/output/D18/triadic_scored.jsonl 全件上書き（G に依存）
  L: graph/extract_high_sim_triads.py → graph/output/D18/high_sim_triads/ 全件上書き（K に依存）
  M: graph/verify/wcc_scoring.py      → graph/output/D18/verify/       全件上書き（K に依存）

使い方:
  cd /home/sonozuka/design_similarity

  python update_downstream.py                    # Step A→J を全実行（デフォルト）
  python update_downstream.py --with-graph       # Step A→M を全実行（グラフ解析含む）
  python update_downstream.py --steps A B C      # 指定ステップのみ
  python update_downstream.py --from-step G      # G 以降を連続実行
  python update_downstream.py --class D10        # 別クラスを指定（Step G〜J/M に反映）
  python update_downstream.py --sim cosine_faiss # 類似度関数を指定

注意:
  - Step A〜C は resume（処理済みペアをスキップ）。何度実行しても重複しない。
  - Step D〜M は毎回全件上書き。
  - 新しい年（2022 が完了した場合など）は自動で拾われる。追加設定不要。
  - ベクトル rank_results が存在する年だけ Step G に反映される（現在 2007〜2022）。
  - Step F（pipeline_counts.csv）は Step D と Step G 両方に依存するため最後に実行される。
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent

# F は D（diagonal_summary.csv）と G（all.jsonl）両方に依存するため G→J の後に実行
STEPS_DEFAULT = ["A", "B", "C", "D", "E", "G", "H", "I", "J", "F"]
STEPS_GRAPH   = ["K", "L", "M"]
ALL_STEPS     = STEPS_DEFAULT + STEPS_GRAPH

STEP_LABELS = {
    "A": "extract_all_pairs        → all_pair/qwen_all_pairs/",
    "B": "extract_yes_pairs        → yes_pair/qwen_yes_pairs/ + 画像",
    "C": "split_by_reason          → yes_pair/qwen/{exact_match,high_similar,similar}/",
    "D": "export_diagonal_csv      → output/diagonal_summary.csv",
    "E": "make_two_heatmaps        → output/heatmap_*.png",
    "F": "export_pipeline_counts   → output/pipeline_counts.csv",
    "G": "join_judgments           → class/{CLASS}/rank_judgments/{SIM}/all.jsonl",
    "H": "rank_analysis            → vector/output/{CLASS}/",
    "I": "export_yes_reasons       → vector/output/{CLASS}/yes_sim080_reasons.csv",
    "J": "export_non_exact_pairs   → rank_analysis/{CLASS}/{SIM}/non_exact_pairs/",
    "K": "graph_analysis           → graph/output/{CLASS}/triadic_scored.jsonl",
    "L": "extract_high_sim_triads  → graph/output/{CLASS}/high_sim_triads/",
    "M": "wcc_scoring              → graph/output/{CLASS}/verify/",
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
        description="judge_cited_pairs.py 更新後の下流データを一括更新する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--steps", nargs="+", choices=ALL_STEPS, metavar="STEP",
        help="実行するステップ (A〜M)。省略時は A〜J。",
    )
    parser.add_argument(
        "--from-step", choices=ALL_STEPS, metavar="STEP",
        help="指定ステップ以降を連続実行。",
    )
    parser.add_argument(
        "--with-graph", action="store_true",
        help="グラフ解析ステップ K〜M も実行する。",
    )
    parser.add_argument(
        "--class", dest="target_class", default="D18",
        help="対象クラス（Step G〜M）。デフォルト: D18",
    )
    parser.add_argument(
        "--sim", default="cosine_numpy", choices=["cosine_numpy", "cosine_faiss"],
        help="類似度関数（Step G〜M）。デフォルト: cosine_numpy",
    )
    args = parser.parse_args()
    cls = args.target_class
    sim = args.sim

    base_steps = STEPS_DEFAULT + (STEPS_GRAPH if args.with_graph else [])

    if args.from_step:
        target_steps = ALL_STEPS[ALL_STEPS.index(args.from_step):]
        target_steps = [s for s in target_steps if s in base_steps]
    elif args.steps:
        target_steps = [s for s in ALL_STEPS if s in args.steps]
    else:
        target_steps = base_steps

    print("=" * 64)
    print("下流データ一括更新")
    print(f"実行ステップ : {' '.join(target_steps)}")
    print(f"クラス / 類似度: {cls} / {sim}")
    print("=" * 64)

    t0 = time.time()

    for step in target_steps:
        print(f"\n[Step {step}] {label(step, cls, sim)}")
        t_step = time.time()

        if step == "A":
            run([sys.executable, "extract_all_pairs.py"])

        elif step == "B":
            run([sys.executable, "extract_yes_pairs.py"])

        elif step == "C":
            run([sys.executable, "analysis/split_by_reason.py"])

        elif step == "D":
            run([sys.executable, "export_diagonal_csv.py"])

        elif step == "E":
            run([sys.executable, "make_two_heatmaps.py"])

        elif step == "F":
            run([sys.executable, "export_pipeline_counts.py"])

        elif step == "G":
            run([
                sys.executable, "vector/join_judgments.py",
                "--class", cls, "--sim", sim, "--no-resume",
            ])

        elif step == "H":
            run([sys.executable, "vector/analysis/rank_analysis.py", "--class", cls])

        elif step == "I":
            run([sys.executable, "vector/analysis/export_yes_reasons.py", "--class", cls])

        elif step == "J":
            run([sys.executable, "vector/analysis/export_non_exact_pairs.py", "--class", cls])

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