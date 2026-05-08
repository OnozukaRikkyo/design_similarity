#!/usr/bin/env python3
"""
パイプライン連続実行スクリプト。

実行順序:
    STEP 1  : build_edge_list.py
    STEP 2a : extract_cited_image_pairs.py   (STEP 1 の出力に依存)
    STEP 2b : plot_indegree.py               (STEP 1 の出力に依存、任意)
    STEP 2c : add_class_to_edge_list.py      (STEP 1 の出力に依存、任意)
    STEP 3  : judge_cited_pairs.py           (STEP 2a の出力に依存)
    STEP 4  : extract_yes_pairs.py           (STEP 3 の出力に依存)

使い方:
    python run_pipeline.py                        # 全ステップ全年
    python run_pipeline.py 2007 2008              # 指定年のみ
    python run_pipeline.py --from-step 2a         # STEP 2a から再開
    python run_pipeline.py --to-step 3            # STEP 3 まで実行
    python run_pipeline.py --skip 2b 2c           # 分析サイドブランチをスキップ
    python run_pipeline.py --type front           # STEP 3 の図タイプ固定
    python run_pipeline.py --no-resume            # STEP 3 を最初から実行
    python run_pipeline.py --rebuild              # キャッシュを再構築
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# ステップ定義（順序が実行順序）
# ---------------------------------------------------------------------------
# (step_id, label, script, accepts_years)
# accepts_years=False のスクリプトには年引数を渡さない
STEPS: list[tuple[str, str, str, bool]] = [
    ("1",  "共引用エッジリスト構築",      "build_edge_list.py",              True),
    ("2a", "画像ペア抽出",                "extract_cited_image_pairs.py",    True),
    ("2b", "次数分布可視化",              "plot_indegree.py",                True),
    ("2c", "意匠分類の付与",              "add_class_to_edge_list.py",       True),
    ("3",  "Gemini 類似判定",             "judge_cited_pairs.py",            True),
    ("4",  "Yes 判定ペアの抽出・可視化",  "extract_yes_pairs.py",            False),
]

STEP_IDS = [s[0] for s in STEPS]


def step_index(step_id: str) -> int:
    return STEP_IDS.index(step_id)


# ---------------------------------------------------------------------------
# ステップごとの引数構築
# ---------------------------------------------------------------------------
def build_args(step_id: str, years: list[str], accepts_years: bool, opts: argparse.Namespace) -> list[str]:
    args: list[str] = [*years] if accepts_years else []

    if step_id == "2a" and opts.rebuild:
        args.append("--rebuild")

    if step_id == "3":
        if opts.img_type:
            args += ["--type", opts.img_type]
        if opts.no_resume:
            args.append("--no-resume")

    if step_id == "2c" and opts.rebuild:
        args.append("--rebuild")

    return args


# ---------------------------------------------------------------------------
# 1ステップ実行
# ---------------------------------------------------------------------------
def run_step(step_id: str, label: str, script: str, extra_args: list[str]) -> bool:
    sep = "=" * 60
    print(f"\n{sep}")
    print(f"  STEP {step_id}  {label}")
    print(sep)

    cmd = [sys.executable, str(SCRIPT_DIR / script), *extra_args]
    print(f"  実行: {' '.join(cmd)}\n")

    t0 = time.time()
    result = subprocess.run(cmd)
    elapsed = time.time() - t0

    if result.returncode != 0:
        print(f"\n[ERROR] STEP {step_id} が終了コード {result.returncode} で失敗しました。")
        return False

    print(f"\n  完了 ({elapsed:.1f} 秒)")
    return True


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="USPTO 意匠特許パイプラインを連続実行する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年 (例: 2007 2008)。省略時は各スクリプトのデフォルト（全年）。",
    )
    parser.add_argument(
        "--from-step", metavar="STEP", default="1", choices=STEP_IDS,
        help=f"開始ステップ (default: 1)。選択肢: {', '.join(STEP_IDS)}",
    )
    parser.add_argument(
        "--to-step", metavar="STEP", default="4", choices=STEP_IDS,
        help=f"終了ステップ (default: 4)。選択肢: {', '.join(STEP_IDS)}",
    )
    parser.add_argument(
        "--skip", metavar="STEP", nargs="+", default=[], choices=STEP_IDS,
        help="スキップするステップ (例: --skip 2b 2c)",
    )
    # STEP 3 (judge_cited_pairs.py) のオプション
    parser.add_argument(
        "--type", dest="img_type",
        choices=["front", "overview", "perspective"], default=None,
        help="[STEP 3] 使用する図タイプ (省略時: front > overview > perspective)",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="[STEP 3] 既存の出力を無視して最初から処理し直す",
    )
    # STEP 2a・2c のキャッシュ再構築
    parser.add_argument(
        "--rebuild", action="store_true",
        help="[STEP 2a, 2c] インデックスキャッシュを再構築する",
    )
    opts = parser.parse_args()

    # 実行対象ステップを確定
    from_idx = step_index(opts.from_step)
    to_idx   = step_index(opts.to_step)
    if from_idx > to_idx:
        parser.error(f"--from-step ({opts.from_step}) は --to-step ({opts.to_step}) より前である必要があります。")

    target_steps = [
        (sid, label, script, accepts_years)
        for sid, label, script, accepts_years in STEPS
        if from_idx <= step_index(sid) <= to_idx and sid not in opts.skip
    ]

    # 実行前サマリー
    skipped = set(opts.skip)
    print("=" * 60)
    print("  パイプライン実行計画")
    print("=" * 60)
    for sid, label, _, _ in STEPS:
        in_range = from_idx <= step_index(sid) <= to_idx
        status = "実行" if (in_range and sid not in skipped) else "スキップ"
        print(f"  STEP {sid:2s}  {label:28s}  [{status}]")
    print()
    if opts.years:
        print(f"  対象年: {' '.join(opts.years)}")
    else:
        print("  対象年: 全年（各スクリプトのデフォルト）")
    print()

    # ステップを順に実行
    total_t0 = time.time()
    for sid, label, script, accepts_years in target_steps:
        extra = build_args(sid, opts.years, accepts_years, opts)
        ok = run_step(sid, label, script, extra)
        if not ok:
            sys.exit(1)

    total = time.time() - total_t0
    print(f"\n{'=' * 60}")
    print(f"  全ステップ完了  (合計 {total:.1f} 秒)")
    print("=" * 60)


if __name__ == "__main__":
    main()