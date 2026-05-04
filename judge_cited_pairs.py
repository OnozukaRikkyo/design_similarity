#!/usr/bin/env python3
"""
共引用画像ペアに対して意匠類似判定を実行する。

入力:  /mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl
出力:  /mnt/eightthdd/uspto/similarity_results/{year}.jsonl

各レコードに image_type_used / similarity / score / reason を追加して出力。
中断した場合は --resume（デフォルト有効）で続きから再開できる。
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from design_similarity import judge_similarity

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
JSONL_DIR = Path("/mnt/eightthdd/uspto/cited_image_pairs")
OUT_DIR   = Path("/mnt/eightthdd/uspto/similarity_results")
DEBUG_DIR = Path(__file__).parent / "debug" / "image"

DEBUG = True  # True にすると処理ペアを DEBUG_DIR に画像保存する

# 共通タイプが複数ある場合の優先順
IMAGE_TYPE_PRIORITY = ["front", "overview", "perspective"]


# ---------------------------------------------------------------------------
# 図タイプの選択
# ---------------------------------------------------------------------------
def pick_common_type(
    record: dict,
    prefer: str | None = None,
) -> tuple[str, str, str] | None:
    """
    source_images と target_images に共通する図タイプを選び
    (type, src_path, tgt_path) を返す。共通タイプがなければ None。
    prefer が指定された場合はそのタイプを最優先で試みる。
    """
    src = record["source_images"]
    tgt = record["target_images"]

    types_to_try = (
        [prefer] + [t for t in IMAGE_TYPE_PRIORITY if t != prefer]
        if prefer else IMAGE_TYPE_PRIORITY
    )
    for t in types_to_try:
        if t in src and t in tgt:
            return t, src[t], tgt[t]
    return None


# ---------------------------------------------------------------------------
# デバッグ画像の保存
# ---------------------------------------------------------------------------
def save_debug_image(
    src_path: str,
    tgt_path: str,
    source_id: str,
    target_id: str,
    img_type: str,
    result: dict | None = None,
) -> None:
    """
    source と target の画像を左右並べて debug/image/ に保存する。
    result が渡された場合は下部に similarity / score / reason を描画する。
    """
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)

    src_img = Image.open(src_path).convert("RGB")
    tgt_img = Image.open(tgt_path).convert("RGB")

    # 高さを揃えてリサイズ
    target_h = 400
    src_img  = src_img.resize((int(src_img.width  * target_h / src_img.height),  target_h))
    tgt_img  = tgt_img.resize((int(tgt_img.width  * target_h / tgt_img.height),  target_h))

    label_h  = 24
    result_h = 28 if result else 0
    padding  = 8
    total_w  = src_img.width + tgt_img.width + padding * 3
    total_h  = label_h + target_h + result_h + padding * 2

    canvas = Image.new("RGB", (total_w, total_h), (240, 240, 240))
    draw   = ImageDraw.Draw(canvas)

    try:
        font_label  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        font_result = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except OSError:
        font_label = font_result = ImageFont.load_default()

    # ラベル
    draw.text((padding, padding),                        source_id, fill=(30, 30, 30),  font=font_label)
    draw.text((src_img.width + padding * 2, padding),    target_id, fill=(30, 30, 30),  font=font_label)

    # 画像を貼り付け
    y_img = label_h + padding
    canvas.paste(src_img, (padding,                      y_img))
    canvas.paste(tgt_img, (src_img.width + padding * 2,  y_img))

    # 仕切り線
    x_div = src_img.width + padding + padding // 2
    draw.line([(x_div, padding), (x_div, total_h - padding)], fill=(180, 180, 180), width=1)

    # 判定結果
    if result:
        color_map = {"類似": (0, 140, 0), "非類似": (180, 0, 0), "要精査": (160, 100, 0)}
        color = color_map.get(result.get("similarity", ""), (80, 80, 80))
        text  = f"{result.get('similarity', '')}  score={result.get('score', '')}  {result.get('reason', '')}"
        draw.text((padding, y_img + target_h + padding // 2), text, fill=color, font=font_result)

    fname = f"{source_id}__{target_id}__{img_type}.png"
    canvas.save(DEBUG_DIR / fname)


# ---------------------------------------------------------------------------
# 年ごとの処理
# ---------------------------------------------------------------------------
def process_year(
    year: str,
    img_type: str | None = None,
    resume: bool = True,
) -> None:
    in_path  = JSONL_DIR / f"{year}.jsonl"
    out_path = OUT_DIR   / f"{year}.jsonl"

    if not in_path.exists():
        print(f"入力ファイルが見つかりません: {in_path}", file=sys.stderr)
        return

    if DEBUG:
        print(f"[debug] 画像出力先: {DEBUG_DIR}")

    # 処理済みペアを収集（resume 時）
    done_keys: set[tuple[str, str]] = set()
    if resume and out_path.exists():
        for line in open(out_path, encoding="utf-8"):
            r = json.loads(line)
            done_keys.add((r["source"], r["target"]))
        print(f"[{year}] 再開: {len(done_keys):,} 件処理済み")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines   = open(in_path, encoding="utf-8").readlines()
    total   = len(lines)
    n_done  = n_skip = n_error = 0

    with open(out_path, "a" if (resume and out_path.exists()) else "w", encoding="utf-8") as out_f:
        for i, line in enumerate(lines, 1):
            record = json.loads(line)
            key = (record["source"], record["target"])

            if key in done_keys:
                n_skip += 1
                continue

            pair = pick_common_type(record, img_type)
            if pair is None:
                n_skip += 1
                continue

            type_used, src_path, tgt_path = pair
            print(
                f"[{year}] {i}/{total}  "
                f"{record['source']} × {record['target']}  [{type_used}]",
                flush=True,
            )

            if DEBUG:
                save_debug_image(
                    src_path, tgt_path,
                    record["source"], record["target"],
                    type_used,
                )

            try:
                result = judge_similarity(src_path, tgt_path)
                record["image_type_used"] = type_used
                record["similarity"]      = result["similarity"]
                record["score"]           = result["score"]
                record["reason"]          = result["reason"]
                n_done += 1
                print(f"  -> {result['similarity']} (score={result['score']}) | {result['reason']}")
            except Exception as e:
                result = None
                record["error"] = str(e)
                n_error += 1
                print(f"  -> ERROR: {e}", file=sys.stderr)

            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
            out_f.flush()  # 1件ごとに書き出し（中断時のデータ損失を防ぐ）

    print(
        f"[{year}] 完了: 判定={n_done:,}  スキップ={n_skip:,}  エラー={n_error:,}  "
        f"-> {out_path}"
    )


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="共引用意匠ペアに対して Gemini で類似判定を実行する"
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年 (例: 2007 2008)。省略時は全年を処理。",
    )
    parser.add_argument(
        "--type", dest="img_type",
        choices=["front", "overview", "perspective"],
        default=None,
        help="使用する図タイプ (省略時: front > overview > perspective の優先順で選択)",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="出力ファイルが存在しても最初から処理し直す",
    )
    args = parser.parse_args()

    years = args.years if args.years else [
        p.stem for p in sorted(JSONL_DIR.glob("[0-9]*.jsonl"))
    ]

    for year in years:
        process_year(year, img_type=args.img_type, resume=not args.no_resume)


if __name__ == "__main__":
    main()
