#!/usr/bin/env python3
"""
指定クラスのペアのみフィルタして cited_image_pairs JSONL を出力する。

入力:
    /mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl
    /mnt/eightthdd/uspto/edge_list_with_class/{year}.csv

出力:
    /mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/{year}.jsonl

フィルタ条件: source と target の両方が指定クラスであるペアのみ。
出力レコードは入力の全フィールドをそのまま引き継ぎ、
source_class / target_class フィールドを追加する。

実行:
    # D18（デフォルト）
    python filter_pairs_by_class.py

    # 別クラスを指定
    python filter_pairs_by_class.py --class D5

    # 指定年のみ
    python filter_pairs_by_class.py 2007 2008 --class D18

    # 処理済みを上書き
    python filter_pairs_by_class.py --no-resume --class D18
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from tqdm import tqdm

# ---------------------------------------------------------------------------
# パス定数（クラス非依存部分）
# ---------------------------------------------------------------------------
PAIRS_DIR = Path("/mnt/eightthdd/uspto/cited_image_pairs")
CLASS_DIR = Path("/mnt/eightthdd/uspto/edge_list_with_class")
CLASS_BASE = Path("/mnt/eightthdd/uspto/class")


def out_dir(target_class: str) -> Path:
    return CLASS_BASE / target_class / "cited_image_pairs"


# ---------------------------------------------------------------------------
# クラスマップの構築
# ---------------------------------------------------------------------------
def load_class_map(year: str) -> dict[str, str]:
    """edge_list_with_class/{year}.csv から patent_id → class_code の辞書を構築する。"""
    class_map: dict[str, str] = {}
    csv_path = CLASS_DIR / f"{year}.csv"
    if not csv_path.exists():
        tqdm.write(f"[{year}] クラスCSVが見つかりません: {csv_path}", file=sys.stderr)
        return class_map
    with open(csv_path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            class_map[row["source"]] = row["source_class"]
            class_map[row["target"]] = row["target_class"]
    return class_map


# ---------------------------------------------------------------------------
# 年ごとの処理
# ---------------------------------------------------------------------------
def process_year(year: str, target_class: str, resume: bool = True) -> None:
    in_path  = PAIRS_DIR / f"{year}.jsonl"
    out_path = out_dir(target_class) / f"{year}.jsonl"

    if not in_path.exists():
        tqdm.write(f"[{year}] 入力ファイルなし: {in_path}")
        return

    lines = in_path.read_text(encoding="utf-8").splitlines()
    if not lines or all(l.strip() == "" for l in lines):
        tqdm.write(f"[{year}] 空ファイル → スキップ")
        return

    if resume and out_path.exists():
        tqdm.write(f"[{year}] 処理済み → スキップ ({out_path})")
        return

    class_map = load_class_map(year)
    if not class_map:
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)

    n_total = n_matched = 0
    with open(out_path, "w", encoding="utf-8") as out_f:
        with tqdm(
            lines,
            desc=year,
            unit="件",
            dynamic_ncols=True,
            leave=False,
        ) as pbar:
            for line in pbar:
                if not line.strip():
                    continue
                n_total += 1
                record = json.loads(line)
                src_class = class_map.get(record["source"])
                tgt_class = class_map.get(record["target"])
                if src_class != target_class or tgt_class != target_class:
                    continue
                record["source_class"] = src_class
                record["target_class"] = tgt_class
                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                n_matched += 1
                pbar.set_postfix(matched=n_matched)

    tqdm.write(
        f"[{year}] {target_class}: {n_matched:,} / 全体: {n_total:,} ペア"
        f"  → {out_path}"
    )


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="cited_image_pairs JSONL から指定クラスのペアだけを抽出する"
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年（例: 2007 2008）。省略時は全年を処理。",
    )
    parser.add_argument(
        "--class", dest="target_class", default="D18",
        metavar="CLASS",
        help="抽出するクラスコード（デフォルト: D18）",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="出力ファイルが存在しても上書きする（デフォルトはスキップ）",
    )
    args = parser.parse_args()

    years = args.years if args.years else [
        p.stem for p in sorted(PAIRS_DIR.glob("[0-9]*.jsonl"))
    ]

    print(f"対象クラス  : {args.target_class}")
    print(f"処理対象年  : {years}")
    print(f"再開モード  : {'有効（処理済みをスキップ）' if not args.no_resume else '無効（全件上書き）'}")
    print(f"出力先      : {out_dir(args.target_class)}\n")

    with tqdm(years, desc="全体", unit="年", position=0, leave=True) as pbar:
        for year in pbar:
            pbar.set_description(f"全体 [{year}]")
            process_year(year, args.target_class, resume=not args.no_resume)

    print("\n完了")


if __name__ == "__main__":
    main()
