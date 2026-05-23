#!/usr/bin/env python3
"""
ランク検索結果と LLM 類似判定を結合し、分析用の全件 JSONL を生成する（Step 5）。

毎回の分析スクリプトが結合処理を繰り返さずに済むよう、前処理として一括保存する。

入力:
    class/{CLASS}/rank_results/{sim_func}/{year}.jsonl
    qwen_similarity_results/{year}.jsonl            (LLM 判定)

出力:
    class/{CLASS}/rank_judgments/{sim_func}/all.jsonl
    1行 = 1 (ペア × タイプ) レコード（全年・全タイプ結合）

追加フィールド（元の rank_results フィールドに追記）:
    judgment      "Yes" / "No" / "Unknown"
    confidence    1〜5  (qwen 信頼度、Unknown 時は 0)
    reason        判定根拠テキスト
    source_image  source の当該タイプ画像パス
    target_image  target の当該タイプ画像パス

実行:
    python vector/join_judgments.py --class D18 --sim cosine_numpy
    python vector/join_judgments.py --class D10 --sim cosine_numpy --no-resume
"""

import argparse
import json
from pathlib import Path

from tqdm import tqdm

CLASS_BASE = Path("/mnt/eightthdd/uspto/class")
QWEN_DIR   = Path("/mnt/eightthdd/uspto/qwen_similarity_results")


def load_qwen(years: list[str]) -> dict[tuple[str, str], dict]:
    """qwen 判定結果を (source, target) → dict で返す。"""
    lookup: dict[tuple[str, str], dict] = {}
    for year in years:
        fp = QWEN_DIR / f"{year}.jsonl"
        if not fp.exists():
            continue
        for line in fp.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                lookup[(r["source"], r["target"])] = r
    return lookup



def main() -> None:
    parser = argparse.ArgumentParser(
        description="ランク検索結果と LLM 判定を結合して保存する"
    )
    parser.add_argument("--class", dest="target_class", default="D18", metavar="CLASS")
    parser.add_argument("--sim",   default="cosine_numpy",
                        choices=["cosine_numpy", "cosine_faiss"])
    parser.add_argument("--no-resume", action="store_true",
                        help="処理済みファイルを上書きする")
    args = parser.parse_args()

    rank_dir = CLASS_BASE / args.target_class / "rank_results" / args.sim
    out_dir  = CLASS_BASE / args.target_class / "rank_judgments" / args.sim
    out_path = out_dir / "all.jsonl"

    if not args.no_resume and out_path.exists():
        print(f"処理済み → スキップ ({out_path})")
        print("再生成するには --no-resume を指定してください。")
        return

    year_files = sorted(rank_dir.glob("[0-9]*.jsonl"))
    years = [f.stem for f in year_files]
    if not years:
        print(f"ランク結果が見つかりません: {rank_dir}")
        return

    print(f"対象クラス  : {args.target_class}")
    print(f"類似度関数  : {args.sim}")
    print(f"処理対象年  : {years}")

    print("Loading qwen judgments...")
    qwen = load_qwen(years)
    print(f"  {len(qwen):,} 件")

    out_dir.mkdir(parents=True, exist_ok=True)

    n_total = n_yes = n_no = n_unk = 0
    with open(out_path, "w") as fout:
        for year_f in tqdm(year_files, desc="年", unit="年"):
            for line in year_f.read_text().splitlines():
                if not line.strip():
                    continue
                r   = json.loads(line)
                key = (r["source"], r["target"])

                # LLM 判定
                q = qwen.get(key)
                r["judgment"]   = q["similarity"] if q else "Unknown"
                r["confidence"] = q.get("confidence", 0) if q else 0
                r["reason"]     = q.get("reason", "") if q else ""

                # 画像パス（rank_results から引き継ぎ）
                r["source_image"] = r.get("source_image")
                r["target_image"] = r.get("target_image")

                fout.write(json.dumps(r, ensure_ascii=False) + "\n")

                n_total += 1
                if r["judgment"] == "Yes":   n_yes += 1
                elif r["judgment"] == "No":  n_no  += 1
                else:                         n_unk += 1

    print(f"\n出力: {out_path}")
    print(f"  合計 {n_total:,} 件  Yes={n_yes:,}  No={n_no:,}  Unknown={n_unk:,}")


if __name__ == "__main__":
    main()
