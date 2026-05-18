#!/usr/bin/env python3
"""
クラス別ベクトル検索パイプライン 一括実行スクリプト

Step 1: filter_pairs_by_class.py  — クラス別ペア抽出
Step 2: build_class_vectors.py    — 画像ベクトル生成
Step 3: build_rank_index.py       — 全件インデックス構築
Step 4: compute_ranks.py          — ベクトルランク検索
Step 5: join_judgments.py         — ランク結果と LLM 判定の結合

前提条件（実行前に以下のディレクトリが存在すること）:
  /mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl
      → extract_cited_image_pairs.py（design_similarity/）が生成
  /mnt/eightthdd/uspto/edge_list_with_class/{year}.csv
      → add_class_to_edge_list.py（design_similarity/）が生成
  /mnt/eightthdd/uspto/cited_image_vectors/{type}/
      → build_cited_image_vectors.py（image_vector/）が生成（GPU 必須）

実行例:
  # D18 全ステップ（resume 有効）
  python vector/run_pipeline.py --class D18 --no-gpu

  # D10 を Step 3 から再開
  python vector/run_pipeline.py --class D10 --from-step 3

  # 特定ステップだけ実行
  python vector/run_pipeline.py --class D18 --steps 1 2

  # 全件上書き
  python vector/run_pipeline.py --class D18 --no-resume --no-gpu
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

STEPS = {
    1: ("filter_pairs_by_class.py", "クラス別ペア抽出"),
    2: ("build_class_vectors.py",   "画像ベクトル生成"),
    3: ("build_rank_index.py",      "全件インデックス構築"),
    4: ("compute_ranks.py",         "ベクトルランク検索"),
    5: ("join_judgments.py",        "ランク結果と LLM 判定の結合"),
}


def build_cmd(step: int, args: argparse.Namespace) -> list[str]:
    script = str(SCRIPT_DIR / STEPS[step][0])
    cmd = [sys.executable, script]

    # years（step 1, 2, 4 が受け付ける）
    if step in (1, 2, 4) and args.years:
        cmd.extend(args.years)

    cmd += ["--class", args.target_class]

    if args.no_resume:
        cmd.append("--no-resume")

    # step 2 のみ --no-gpu
    if step == 2 and args.no_gpu:
        cmd.append("--no-gpu")

    # step 4, 5 は --sim を受け付ける
    if step in (4, 5):
        cmd += ["--sim", args.sim]

    return cmd


def run_step(step: int, args: argparse.Namespace) -> bool:
    label = STEPS[step][1]
    cmd   = build_cmd(step, args)

    print(f"\n{'=' * 60}")
    print(f"  Step {step}: {label}")
    print(f"  {' '.join(cmd)}")
    print(f"{'=' * 60}\n")

    t0 = time.monotonic()
    result = subprocess.run(cmd)
    elapsed = time.monotonic() - t0

    if result.returncode != 0:
        print(f"\n[ERROR] Step {step} が終了コード {result.returncode} で失敗しました。", file=sys.stderr)
        return False

    print(f"\n[OK] Step {step} 完了 ({elapsed:.1f}s)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="クラス別ベクトル検索パイプラインを一括実行する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年（例: 2007 2008）。省略時は全年。",
    )
    parser.add_argument(
        "--class", dest="target_class", default="D18", metavar="CLASS",
        help="対象クラスコード（デフォルト: D18）",
    )
    parser.add_argument(
        "--sim", default="cosine_numpy",
        choices=["cosine_numpy", "cosine_faiss"],
        help="類似度計算バックエンド（デフォルト: cosine_numpy）",
    )
    parser.add_argument(
        "--no-gpu", action="store_true",
        help="Step 2 で GPU を使わない（既存ベクトルのコピーのみ）",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="処理済みファイルを上書きする（全ステップに適用）",
    )

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--steps", nargs="+", type=int, metavar="N",
        choices=list(STEPS.keys()),
        help="実行するステップ番号（例: --steps 1 2 3）",
    )
    group.add_argument(
        "--from-step", type=int, metavar="N",
        choices=list(STEPS.keys()),
        help="指定ステップ以降を実行（例: --from-step 3）",
    )

    args = parser.parse_args()

    # 実行するステップを決定
    if args.steps:
        target_steps = sorted(args.steps)
    elif args.from_step:
        target_steps = [s for s in STEPS if s >= args.from_step]
    else:
        target_steps = list(STEPS.keys())

    print(f"対象クラス  : {args.target_class}")
    print(f"類似度関数  : {args.sim}")
    print(f"GPU 使用    : {'無効 (--no-gpu)' if args.no_gpu else '有効'}")
    print(f"上書きモード: {'有効 (--no-resume)' if args.no_resume else '無効（resume）'}")
    print(f"実行ステップ: {target_steps}")
    if args.years:
        print(f"対象年      : {args.years}")

    total_start = time.monotonic()

    for step in target_steps:
        ok = run_step(step, args)
        if not ok:
            sys.exit(1)

    total = time.monotonic() - total_start
    print(f"\n{'=' * 60}")
    print(f"  全ステップ完了  合計: {total:.1f}s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
