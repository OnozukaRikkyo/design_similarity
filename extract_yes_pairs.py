"""
similarity_results の JSONL から similarity=Yes のレコードを抽出し、
- /mnt/eightthdd/uspto/yes_pair/{backend}_yes_pairs/{year}.jsonl
    : 年別 JSONL（特許メタデータ付き・1行1レコード）
- /mnt/eightthdd/uspto/yes_pair/{backend}_yes_image_pair/
    : source + target を横結合した画像
を保存する。

年は source 特許の CSV ファイル名（2007.csv → "2007"）で決定する。
CSV に存在しない場合は画像パスの /images/{year}/ から補完し、
それも取れなければ "unknown" に分類する。
"""

import csv
import json
import pickle
import re
import sys
import textwrap
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from image_processor import ImageProcessor

# ─── バックエンド選択（ここを編集して切り替える） ───────────────────────────
BACKEND = "qwen"   # "gemini" | "qwen"
# BACKEND = "gemini"   # "gemini" | "qwen"

CSV_DIR = Path("/mnt/eightthdd/uspto/data")

RESULTS_DIR = Path("/mnt/eightthdd/uspto/") / (
    "qwen_similarity_results" if BACKEND == "qwen" else "similarity_results"
)
_YES_PAIR_BASE     = Path("/mnt/eightthdd/uspto/yes_pair")
OUT_JSONL_DIR      = _YES_PAIR_BASE / f"{BACKEND}_yes_pairs"
OUT_IMG_DIR        = _YES_PAIR_BASE / f"{BACKEND}_yes_image_pair"
PATENT_INDEX_CACHE = _YES_PAIR_BASE / "_patent_index.pkl"

TARGET_H = 400  # 画像の表示高さ（px）


# ---------------------------------------------------------------------------
# 特許属性インデックス（id → {title, class, date, year}）
# ---------------------------------------------------------------------------
def build_patent_index(csv_dir: Path, cache_path: Path) -> dict[str, dict]:
    """全 CSV から {patent_id: {title, class, date, year}} を構築し pickle キャッシュする。"""
    if cache_path.exists():
        print(f"キャッシュから特許インデックスをロード: {cache_path}", flush=True)
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    print("特許インデックス構築中...", end=" ", flush=True)
    index: dict[str, dict] = {}
    for path in sorted(csv_dir.glob("*.csv")):
        year = path.stem  # "2007", "2008", ...
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("id", "").strip()
                if pid:
                    index[pid] = {
                        "title": row.get("title", "").strip(),
                        "class": row.get("class", "").strip(),
                        "date":  row.get("date",  "").strip(),
                        "year":  year,
                    }
    print(f"{len(index):,} 件")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"キャッシュ保存: {cache_path}")
    return index


def _year_from_images(record: dict) -> str:
    """画像パスの /images/{year}/ から年を抽出するフォールバック。"""
    for imgs in (record.get("source_images", {}), record.get("target_images", {})):
        for path in imgs.values():
            m = re.search(r"/images/(\d{4})/", path)
            if m:
                return m.group(1)
    return "unknown"


def _id_diff(src: str, tgt: str) -> int | None:
    """
    意匠特許 ID（例: D0534345）の数値部分の差の絶対値を返す。
    パース失敗時は None。
    連番（diff=1）の場合、同一出願人が同日に連続登録した設計バリアントの可能性が高い。
    """
    try:
        return abs(int(src.lstrip("D")) - int(tgt.lstrip("D")))
    except ValueError:
        return None


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

    header_h    = line_h * 2 + padding
    wrap_chars  = max(40, (total_w - padding * 2) // 7)
    reason_lines = textwrap.wrap(reason, width=wrap_chars) if reason else []
    footer_h    = line_h + line_h * len(reason_lines) + padding if (confidence or reason) else 0

    total_h = header_h + img_h + footer_h
    canvas  = Image.new("RGB", (total_w, total_h), color=(245, 245, 245))
    draw    = ImageDraw.Draw(canvas)

    src_title = textwrap.shorten(src_info.get("title", ""), width=40, placeholder="…")
    src_class = src_info.get("class", "")
    draw.text((padding, padding),          src_title, fill=(20, 20, 120), font=font_header)
    draw.text((padding, padding + line_h), src_class, fill=(80, 80, 80),  font=font_sub)

    tgt_x     = img_a.width + gap
    tgt_title = textwrap.shorten(tgt_info.get("title", ""), width=40, placeholder="…")
    tgt_class = tgt_info.get("class", "")
    draw.text((tgt_x + padding, padding),          tgt_title, fill=(20, 20, 120), font=font_header)
    draw.text((tgt_x + padding, padding + line_h), tgt_class, fill=(80, 80, 80),  font=font_sub)

    draw.line([(tgt_x - gap // 2, 0), (tgt_x - gap // 2, total_h)], fill=(200, 200, 200), width=1)

    y_img = header_h
    canvas.paste(img_a, (0,     y_img + (img_h - img_a.height) // 2))
    canvas.paste(img_b, (tgt_x, y_img + (img_h - img_b.height) // 2))

    if confidence or reason:
        y = y_img + img_h + padding // 2
        draw.text((padding, y), f"confidence: {confidence}", fill=(0, 100, 0), font=font_conf)
        y += line_h
        for ln in reason_lines:
            draw.text((padding, y), ln, fill=(60, 60, 60), font=font_reason)
            y += line_h

    return canvas


# ---------------------------------------------------------------------------
# JSONL 処理（年別バケットに振り分け）
# ---------------------------------------------------------------------------
def process_file(
    jsonl_path: Path,
    jsonl_out_dir: Path,
    img_out: Path,
    patent_index: dict[str, dict],
) -> tuple[int, int]:
    """
    jsonl_path の全レコードを走査し、similarity=Yes のものを
    年別 JSONL と画像ペアとして保存する。

    JSONL レコード形式:
      source, target,
      source_title, source_class, source_date,
      target_title, target_class, target_date,
      source_images, target_images, events,
      image_type_used, similarity, confidence, reason
    """
    # 年 → レコードリスト のバッファ（ファイルを一括オープンしないため）
    buckets: dict[str, list[str]] = defaultdict(list)

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

            src_meta = patent_index.get(src, {})
            tgt_meta = patent_index.get(tgt, {})
            year     = src_meta.get("year") or _year_from_images(rec)

            # 出力レコード（CSV メタデータを付加）
            out_rec = {
                "source":       src,
                "target":       tgt,
                "id_diff":      _id_diff(src, tgt),
                "source_title": src_meta.get("title", ""),
                "source_class": src_meta.get("class", ""),
                "source_date":  src_meta.get("date",  ""),
                "target_title": tgt_meta.get("title", ""),
                "target_class": tgt_meta.get("class", ""),
                "target_date":  tgt_meta.get("date",  ""),
                "source_images":   rec.get("source_images", {}),
                "target_images":   rec.get("target_images", {}),
                "events":          rec.get("events", []),
                "image_type_used": rec.get("image_type_used", ""),
                "similarity":      rec["similarity"],
                "confidence":      rec.get("confidence", ""),
                "reason":          rec.get("reason", ""),
            }
            buckets[year].append(json.dumps(out_rec, ensure_ascii=False))

            # 画像ペア保存
            img_type = rec.get("image_type_used", "perspective")
            src_path = rec.get("source_images", {}).get(img_type)
            tgt_path = rec.get("target_images", {}).get(img_type)

            if not src_path or not tgt_path:
                print(f"  [WARN] 画像パス不明: {src}__{tgt}", file=sys.stderr)
                skipped += 1
                continue

            img_a = load_tif(src_path)
            img_b = load_tif(tgt_path)
            if img_a is None or img_b is None:
                skipped += 1
                continue

            pair_img = concat_images(
                img_a, img_b,
                src_info=src_meta,
                tgt_info=tgt_meta,
                confidence=rec.get("confidence", ""),
                reason=rec.get("reason", ""),
            )
            pair_img.save(img_out / f"{src}__{tgt}.png")

    # 年別 JSONL に追記
    for year, lines in sorted(buckets.items()):
        out_path = jsonl_out_dir / f"{year}.jsonl"
        with open(out_path, "a", encoding="utf-8") as fout:
            fout.write("\n".join(lines) + "\n")

    return found, skipped


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    OUT_JSONL_DIR.mkdir(parents=True, exist_ok=True)
    OUT_IMG_DIR.mkdir(parents=True, exist_ok=True)

    patent_index = build_patent_index(CSV_DIR, PATENT_INDEX_CACHE)

    jsonl_files = sorted(RESULTS_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"JSONL ファイルが見つかりません: {RESULTS_DIR}")
        sys.exit(1)

    total_found = total_skipped = 0
    for path in jsonl_files:
        print(f"処理中: {path.name}")
        found, skipped = process_file(path, OUT_JSONL_DIR, OUT_IMG_DIR, patent_index)
        print(f"  → similarity=Yes: {found}件  (画像スキップ: {skipped}件)")
        total_found += found
        total_skipped += skipped

    # 年別の件数サマリ
    jsonl_files_out = sorted(OUT_JSONL_DIR.glob("*.jsonl"))
    if jsonl_files_out:
        print("\n年別 JSONL:")
        for p in jsonl_files_out:
            n = sum(1 for _ in open(p, encoding="utf-8") if _.strip())
            print(f"  {p.name}: {n}件")

    print(f"\n完了: 合計 {total_found} 件の Yes レコード ({total_skipped} 件は画像スキップ)")
    print(f"  JSONL → {OUT_JSONL_DIR.resolve()}")
    print(f"  画像  → {OUT_IMG_DIR.resolve()}")


if __name__ == "__main__":
    main()