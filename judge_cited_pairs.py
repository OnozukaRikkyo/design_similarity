#!/usr/bin/env python3
"""
共引用画像ペアに対して意匠類似判定を実行する。

入力:  /mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl
出力:  /mnt/eightthdd/uspto/similarity_results/{year}.jsonl

各レコードに image_type_used / similarity / confidence / reason を追加して出力。
中断した場合は --resume（デフォルト有効）で続きから再開できる。
"""

import argparse
import json
import re
import sys
import textwrap
import time
from pathlib import Path

from tqdm import tqdm

from PIL import Image, ImageDraw, ImageFont

from design_similarity import judge_similarity
from image_processor import ImageProcessor

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

    src_img = ImageProcessor.process_file(src_path).convert("RGB")
    tgt_img = ImageProcessor.process_file(tgt_path).convert("RGB")

    # 高さを揃えてリサイズ
    target_h = 400
    src_img  = src_img.resize((int(src_img.width  * target_h / src_img.height),  target_h))
    tgt_img  = tgt_img.resize((int(tgt_img.width  * target_h / tgt_img.height),  target_h))

    label_h  = 24
    padding  = 8

    try:
        font_label  = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
        font_result = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        font_conf   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except OSError:
        font_label = font_result = font_conf = ImageFont.load_default()

    total_w  = src_img.width + tgt_img.width + padding * 3
    # 1文字あたり約7px（DejaVuSans 12pt）で折り返し幅を推定
    wrap_chars = max(40, (total_w - padding * 2) // 7)

    line_h = 16
    if result:
        reason_lines = textwrap.wrap(result.get("reason", ""), width=wrap_chars)
        result_h = line_h + line_h * len(reason_lines) + padding
    else:
        reason_lines = []
        result_h = 0

    total_h = label_h + target_h + result_h + padding * 2

    canvas = Image.new("RGB", (total_w, total_h), (240, 240, 240))
    draw   = ImageDraw.Draw(canvas)

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
        color_map = {"Yes": (0, 140, 0), "No": (180, 0, 0)}
        color = color_map.get(str(result.get("similarity", "")), (80, 80, 80))
        y_res = y_img + target_h + padding // 2
        # 1行目: similarity + confidence（太字・判定色）
        conf_text = f"similarity: {result.get('similarity', '')}  confidence: {result.get('confidence', '')}"
        draw.text((padding, y_res), conf_text, fill=color, font=font_conf)
        y_res += line_h
        # 残行: reason（折り返し・グレー）
        for ln in reason_lines:
            draw.text((padding, y_res), ln, fill=(60, 60, 60), font=font_result)
            y_res += line_h

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
        tqdm.write(f"[debug] 画像出力先: {DEBUG_DIR}")

    # 処理済みペアを収集（resume 時）
    done_keys: set[tuple[str, str]] = set()
    if resume and out_path.exists():
        for line in open(out_path, encoding="utf-8"):
            r = json.loads(line)
            done_keys.add((r["source"], r["target"]))
        tqdm.write(f"[{year}] 再開: {len(done_keys):,} 件処理済み")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    lines   = open(in_path, encoding="utf-8").readlines()
    total   = len(lines)
    n_done  = n_skip = n_error = 0

    with open(out_path, "a" if (resume and out_path.exists()) else "w", encoding="utf-8") as out_f:
        with tqdm(total=total, desc=year, unit="件", dynamic_ncols=True) as pbar:
            for i, line in enumerate(lines, 1):
                record = json.loads(line)
                key = (record["source"], record["target"])

                if key in done_keys:
                    n_skip += 1
                    pbar.update(1)
                    continue

                pair = pick_common_type(record, img_type)
                if pair is None:
                    n_skip += 1
                    pbar.update(1)
                    continue

                type_used, src_path, tgt_path = pair
                tqdm.write(
                    f"[{year}] {i}/{total}  "
                    f"{record['source']} × {record['target']}  [{type_used}]"
                )

                RETRY_WAIT_SEC = 300
                MAX_RETRIES = 4
                for attempt in range(MAX_RETRIES + 1):
                    try:
                        result = judge_similarity(src_path, tgt_path)
                        record["image_type_used"] = type_used
                        record["similarity"]      = result["similarity"]
                        record["confidence"]      = result["confidence"]
                        record["reason"]          = result["reason"]
                        n_done += 1
                        tqdm.write(
                            f"  -> {result['similarity']} (confidence={result['confidence']}) | {result['reason']}"
                        )
                        if DEBUG:
                            save_debug_image(
                                src_path, tgt_path,
                                record["source"], record["target"],
                                type_used,
                                result=result,
                            )
                        break
                    except Exception as e:
                        err = str(e)
                        if "429" in err or "RESOURCE_EXHAUSTED" in err:
                            m = re.search(r"retry in ([\d.]+)s", err)
                            base = float(m.group(1)) + 5 if m else RETRY_WAIT_SEC
                            wait = base * (attempt + 1)
                            if attempt < MAX_RETRIES:
                                tqdm.write(f"  [429] クォータ超過。{wait:.1f}秒後にリトライ ({attempt + 1}/{MAX_RETRIES})...", file=sys.stderr)
                                time.sleep(wait)
                            else:
                                tqdm.write(f"  [ERROR] 429が{MAX_RETRIES}回続いたため終了します。", file=sys.stderr)
                                sys.exit(1)
                        elif "503" in err or "UNAVAILABLE" in err:
                            wait = RETRY_WAIT_SEC * (attempt + 1)
                            if attempt < MAX_RETRIES:
                                tqdm.write(f"  [503] サービス混雑。{wait:.1f}秒後にリトライ ({attempt + 1}/{MAX_RETRIES})...", file=sys.stderr)
                                time.sleep(wait)
                            else:
                                tqdm.write(f"  [ERROR] 503が{MAX_RETRIES}回続いたため終了します。", file=sys.stderr)
                                sys.exit(1)
                        else:
                            tqdm.write(f"  -> ERROR: {e}", file=sys.stderr)
                            sys.exit(1)

                out_f.write(json.dumps(record, ensure_ascii=False) + "\n")
                out_f.flush()  # 1件ごとに書き出し（中断時のデータ損失を防ぐ）

                pbar.update(1)
                pbar.set_postfix(done=n_done, skip=n_skip, err=n_error)

    tqdm.write(
        f"[{year}] 完了: 判定={n_done:,}  スキップ={n_skip:,}  エラー={n_error:,}  "
        f"-> {out_path}"
    )


# ---------------------------------------------------------------------------
# debug 画像の再生成（既存 JSONL から confidence/reason を描画）
# ---------------------------------------------------------------------------
def reannotate_debug(year: str) -> None:
    """similarity_results/{year}.jsonl を読み、debug 画像を confidence/reason 付きで再生成する。"""
    jsonl_path = OUT_DIR / f"{year}.jsonl"
    if not jsonl_path.exists():
        print(f"結果ファイルが見つかりません: {jsonl_path}", file=sys.stderr)
        return

    lines = jsonl_path.read_text(encoding="utf-8").splitlines()
    tqdm.write(f"[{year}] {len(lines):,} 件を再描画します -> {DEBUG_DIR}")

    for line in lines:
        record = json.loads(line)
        img_type   = record.get("image_type_used")
        src_images = record.get("source_images", {})
        tgt_images = record.get("target_images", {})

        if not img_type or img_type not in src_images or img_type not in tgt_images:
            continue

        result = {
            "similarity": record.get("similarity", ""),
            "confidence": record.get("confidence", ""),
            "reason":     record.get("reason", ""),
        }
        save_debug_image(
            src_images[img_type],
            tgt_images[img_type],
            record["source"],
            record["target"],
            img_type,
            result=result,
        )

    tqdm.write(f"[{year}] 再描画完了")


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
    parser.add_argument(
        "--reannotate", action="store_true",
        help="新規判定は行わず、既存の similarity_results から debug 画像を再生成する",
    )
    args = parser.parse_args()

    years = args.years if args.years else [
        p.stem for p in sorted((OUT_DIR if args.reannotate else JSONL_DIR).glob("[0-9]*.jsonl"))
    ]

    if args.reannotate:
        for year in years:
            reannotate_debug(year)
    else:
        for year in years:
            process_year(year, img_type=args.img_type, resume=not args.no_resume)


if __name__ == "__main__":
    main()
