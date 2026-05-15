"""
similarity_results の JSONL から全レコードを抽出し、
- /mnt/eightthdd/uspto/all_pair/{backend}_all_pairs/{year}.jsonl
    : 年別 JSONL（特許メタデータ付き・1行1レコード）
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
from collections import defaultdict
from pathlib import Path

# ─── バックエンド選択（ここを編集して切り替える） ───────────────────────────
BACKEND = "qwen"   # "gemini" | "qwen"

CSV_DIR = Path("/mnt/eightthdd/uspto/data")

RESULTS_DIR = Path("/mnt/eightthdd/uspto/") / (
    "qwen_similarity_results" if BACKEND == "qwen" else "similarity_results"
)
_ALL_PAIR_BASE     = Path("/mnt/eightthdd/uspto/all_pair")
OUT_JSONL_DIR      = _ALL_PAIR_BASE / f"{BACKEND}_all_pairs"
PATENT_INDEX_CACHE = _ALL_PAIR_BASE / "_patent_index.pkl"


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
        year = path.stem
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
    """
    try:
        return abs(int(src.lstrip("D")) - int(tgt.lstrip("D")))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# JSONL 処理（年別バケットに振り分け）
# ---------------------------------------------------------------------------
def process_file(
    jsonl_path: Path,
    jsonl_out_dir: Path,
    patent_index: dict[str, dict],
) -> int:
    """
    jsonl_path の全レコードを走査し、年別 JSONL として保存する。

    JSONL レコード形式:
      source, target,
      source_title, source_class, source_date,
      target_title, target_class, target_date,
      source_images, target_images, events,
      image_type_used, similarity, confidence, reason
    """
    buckets: dict[str, list[str]] = defaultdict(list)

    total = 0
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

            total += 1
            src = rec["source"]
            tgt = rec["target"]

            src_meta = patent_index.get(src, {})
            tgt_meta = patent_index.get(tgt, {})
            year     = src_meta.get("year") or _year_from_images(rec)

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
                "similarity":      rec.get("similarity", ""),
                "confidence":      rec.get("confidence", ""),
                "reason":          rec.get("reason", ""),
            }
            buckets[year].append(json.dumps(out_rec, ensure_ascii=False))

    for year, lines in sorted(buckets.items()):
        out_path = jsonl_out_dir / f"{year}.jsonl"
        with open(out_path, "a", encoding="utf-8") as fout:
            fout.write("\n".join(lines) + "\n")

    return total


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main():
    OUT_JSONL_DIR.mkdir(parents=True, exist_ok=True)

    patent_index = build_patent_index(CSV_DIR, PATENT_INDEX_CACHE)

    jsonl_files = sorted(RESULTS_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"JSONL ファイルが見つかりません: {RESULTS_DIR}")
        sys.exit(1)

    total = 0
    for path in jsonl_files:
        print(f"処理中: {path.name}")
        n = process_file(path, OUT_JSONL_DIR, patent_index)
        print(f"  → {n} 件")
        total += n

    jsonl_files_out = sorted(OUT_JSONL_DIR.glob("*.jsonl"))
    if jsonl_files_out:
        print("\n年別 JSONL:")
        for p in jsonl_files_out:
            n = sum(1 for _ in open(p, encoding="utf-8") if _.strip())
            print(f"  {p.name}: {n} 件")

    print(f"\n完了: 合計 {total} 件")
    print(f"  JSONL → {OUT_JSONL_DIR.resolve()}")


if __name__ == "__main__":
    main()
