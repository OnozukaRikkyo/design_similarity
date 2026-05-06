"""
similarity_results の JSONL から similarity=Yes のレコードを抽出し、
- debug/yes_json/  : 該当 JSON レコード（1ファイル1レコード）
- debug/yes_image_pair/ : source + target を横結合した画像
を保存する。
"""

import csv
import json
import pickle
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from image_processor import ImageProcessor


RESULTS_DIR  = Path("/mnt/eightthdd/uspto/similarity_results")
CSV_DIR      = Path("/mnt/eightthdd/uspto/data")
OUT_JSON_DIR = Path("debug/yes_json")
OUT_IMG_DIR  = Path("debug/yes_image_pair")
PATENT_INDEX_CACHE = Path("debug/_patent_index.pkl")

TARGET_H = 400  # 画像の表示高さ（px）


# ---------------------------------------------------------------------------
# 特許属性インデックス（id → {title, class}）
# ---------------------------------------------------------------------------
def build_patent_index(csv_dir: Path, cache_path: Path) -> dict[str, dict]:
    """全 CSV から {patent_id: {"title": ..., "class": ...}} を構築し pickle キャッシュする。"""
    if cache_path.exists():
        print(f"キャッシュから特許インデックスをロード: {cache_path}", flush=True)
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    print("特許インデックス構築中...", end=" ", flush=True)
    index: dict[str, dict] = {}
    for path in sorted(csv_dir.glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("id", "").strip()
                if pid:
                    index[pid] = {
                        "title": row.get("title", "").strip(),
                        "class": row.get("class", "").strip(),
                    }
    print(f"{len(index):,} 件")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"キャッシュ保存: {cache_path}")
    return index


# ---------------------------------------------------------------------------
# 画像ロード
# ---------------------------------------------------------------------------
def load_tif(path: str) -> Image.Image | None:
    try:
        img = ImageProcessor.process_file(path).convert("RGB")
        w = max(1, round(img.width * TARGET_H / img.height))
        return img.resize((w, TARGET_H), Image.LANCZOS)
    except (FileNotFoundError, UnidentifiedImageError, Exception) as e:
        print(f"  [WARN] 画像読み込み失敗: {path} ({e})", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# 画像結合（上部にタイトル・分類、下部に confidence/reason）
# ---------------------------------------------------------------------------
def concat_images(
    img_a: Image.Image,
    img_b: Image.Image,
    src_info: dict,
    tgt_info: dict,
    confidence: int | str = "",
    reason: str = "",
    gap: int = 10,
    padding: int = 8,
) -> Image.Image:
    try:
        font_header = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        font_sub    = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
        font_conf   = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
        font_reason = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
    except OSError:
        font_header = font_sub = font_conf = font_reason = ImageFont.load_default()

    img_h   = max(img_a.height, img_b.height)
    total_w = img_a.width + gap + img_b.width
    line_h  = 16

    # 上部ヘッダー: タイトル + 分類（各2行）
    header_h = line_h * 2 + padding

    # 下部テキスト: confidence + reason
    wrap_chars  = max(40, (total_w - padding * 2) // 7)
    reason_lines = textwrap.wrap(reason, width=wrap_chars) if reason else []
    footer_h = line_h + line_h * len(reason_lines) + padding if (confidence or reason) else 0

    total_h = header_h + img_h + footer_h
    canvas  = Image.new("RGB", (total_w, total_h), color=(245, 245, 245))
    draw    = ImageDraw.Draw(canvas)

    # --- 上部ヘッダー描画 ---
    # source 側（左）
    src_title = textwrap.shorten(src_info.get("title", ""), width=40, placeholder="…")
    src_class = src_info.get("class", "")
    draw.text((padding, padding),           src_title, fill=(20, 20, 120),  font=font_header)
    draw.text((padding, padding + line_h),  src_class, fill=(80, 80, 80),   font=font_sub)

    # target 側（右）
    tgt_x     = img_a.width + gap
    tgt_title = textwrap.shorten(tgt_info.get("title", ""), width=40, placeholder="…")
    tgt_class = tgt_info.get("class", "")
    draw.text((tgt_x + padding, padding),           tgt_title, fill=(20, 20, 120),  font=font_header)
    draw.text((tgt_x + padding, padding + line_h),  tgt_class, fill=(80, 80, 80),   font=font_sub)

    # 仕切り線
    draw.line([(tgt_x - gap // 2, 0), (tgt_x - gap // 2, total_h)], fill=(200, 200, 200), width=1)

    # --- 画像貼り付け ---
    y_img = header_h
    canvas.paste(img_a, (0,        y_img + (img_h - img_a.height) // 2))
    canvas.paste(img_b, (tgt_x,    y_img + (img_h - img_b.height) // 2))

    # --- 下部フッター描画 ---
    if confidence or reason:
        y = y_img + img_h + padding // 2
        draw.text((padding, y), f"confidence: {confidence}", fill=(0, 100, 0), font=font_conf)
        y += line_h
        for ln in reason_lines:
            draw.text((padding, y), ln, fill=(60, 60, 60), font=font_reason)
            y += line_h

    return canvas


# ---------------------------------------------------------------------------
# JSONL 処理
# ---------------------------------------------------------------------------
def process_file(
    jsonl_path: Path,
    json_out: Path,
    img_out: Path,
    patent_index: dict[str, dict],
) -> tuple[int, int]:
    found = skipped = 0
    with open(jsonl_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [WARN] JSON parse error {jsonl_path}:{lineno}: {e}", file=sys.stderr)
                continue

            if rec.get("similarity") != "Yes":
                continue

            found += 1
            src = rec["source"]
            tgt = rec["target"]
            stem = f"{src}__{tgt}"

            # JSON 保存
            (json_out / f"{stem}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            # 画像パス取得
            img_type = rec.get("image_type_used", "perspective")
            src_path = rec.get("source_images", {}).get(img_type)
            tgt_path = rec.get("target_images", {}).get(img_type)

            if not src_path or not tgt_path:
                print(f"  [WARN] 画像パス不明: {stem}", file=sys.stderr)
                skipped += 1
                continue

            img_a = load_tif(src_path)
            img_b = load_tif(tgt_path)
            if img_a is None or img_b is None:
                skipped += 1
                continue

            pair_img = concat_images(
                img_a, img_b,
                src_info=patent_index.get(src, {}),
                tgt_info=patent_index.get(tgt, {}),
                confidence=rec.get("confidence", ""),
                reason=rec.get("reason", ""),
            )
            pair_img.save(img_out / f"{stem}.png")

    return found, skipped


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    OUT_JSON_DIR.mkdir(parents=True, exist_ok=True)
    OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

    patent_index = build_patent_index(CSV_DIR, PATENT_INDEX_CACHE)

    jsonl_files = sorted(RESULTS_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"JSONL ファイルが見つかりません: {RESULTS_DIR}")
        sys.exit(1)

    total_found = total_skipped = 0
    for path in jsonl_files:
        print(f"処理中: {path.name}")
        found, skipped = process_file(path, OUT_JSON_DIR, OUT_IMG_DIR, patent_index)
        print(f"  → similarity=Yes: {found}件  (画像スキップ: {skipped}件)")
        total_found += found
        total_skipped += skipped

    print(f"\n完了: 合計 {total_found} 件の Yes レコード ({total_skipped} 件は画像スキップ)")
    print(f"  JSON  → {OUT_JSON_DIR.resolve()}")
    print(f"  画像  → {OUT_IMG_DIR.resolve()}")


if __name__ == "__main__":
    main()