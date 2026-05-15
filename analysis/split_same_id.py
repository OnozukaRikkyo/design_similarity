"""
Yes 判定ペアを「source == target（同一特許ID）」と「source != target（異なる特許ID）」に振り分ける。

  source / target フィールドの D 番号が完全一致するペアを same に、それ以外を distinct に分類。
  通常の引用ペアでは source != target のため、same は異常値・重複データの検出に相当する。

入力:
  {backend}_yes_pairs/{year}.jsonl   (extract_yes_pairs.py の出力)
  {backend}_yes_image_pair/          (extract_yes_pairs.py の出力画像)

出力（入力元は削除しない）:
  {backend}/same/jsonl/{year}.jsonl     ← 同一IDペア（matched_d_classes フィールド付き）
  {backend}/same/images/               ← 同一IDペア画像
  {backend}/distinct/jsonl/{year}.jsonl ← 異なるIDペア
  {backend}/distinct/images/           ← 異なるIDペア画像
"""

import json
import re
import shutil
import sys
from pathlib import Path

# ─── バックエンド選択（ここを編集して切り替える） ───────────────────────────
BACKEND = "qwen"   # "gemini" | "qwen"

# ─── パス設定 ───────────────────────────────────────────────────────────────
_YES_PAIR_BASE = Path("/mnt/eightthdd/uspto/yes_pair")

INPUT_JSONL_DIR   = _YES_PAIR_BASE / f"{BACKEND}_yes_pairs"
INPUT_IMG_DIR     = _YES_PAIR_BASE / f"{BACKEND}_yes_image_pair"

_OUT_BASE = _YES_PAIR_BASE / BACKEND

SAME_CLASS_JSONL_DIR = _OUT_BASE / "same"     / "jsonl"
SAME_CLASS_IMG_DIR   = _OUT_BASE / "same"     / "images"
DISTINCT_JSONL_DIR   = _OUT_BASE / "distinct" / "jsonl"
DISTINCT_IMG_DIR     = _OUT_BASE / "distinct" / "images"


# ---------------------------------------------------------------------------
# D クラス抽出
# ---------------------------------------------------------------------------
def extract_d_classes(class_str: str) -> set[str]:
    """
    "D 6480, D9564" → {"D0006480", "D0009564"}
    "D24115"        → {"D0024115"}
    スペースを除去して 7 桁ゼロパディングした完全 ID を返す。
    """
    result = set()
    for part in class_str.upper().split(","):
        cleaned = part.replace(" ", "")
        m = re.match(r"D(\d+)", cleaned)
        if m:
            result.add(f"D{m.group(1).zfill(7)}")
    return result


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def _copy_image(src: str, tgt: str, dst_dir: Path) -> bool:
    src_path = INPUT_IMG_DIR / f"{src}__{tgt}.png"
    if not src_path.exists():
        return False
    shutil.copy2(str(src_path), dst_dir / src_path.name)
    return True


# ---------------------------------------------------------------------------
# 年別 JSONL 処理
# ---------------------------------------------------------------------------
def process_year(jsonl_path: Path) -> dict:
    year = jsonl_path.stem

    records = []
    with open(jsonl_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [WARN] parse error {jsonl_path.name}:{lineno}: {e}", file=sys.stderr)

    same_class, distinct = [], []

    for rec in records:
        src_classes = extract_d_classes(rec.get("source", ""))
        tgt_classes = extract_d_classes(rec.get("target", ""))
        matched     = src_classes & tgt_classes

        if matched:
            rec["matched_d_classes"] = sorted(matched)
            same_class.append(rec)
        else:
            distinct.append(rec)

    # JSONL 書き出し（追記）
    def _append_jsonl(path: Path, recs: list[dict]) -> None:
        with open(path, "a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _append_jsonl(SAME_CLASS_JSONL_DIR / f"{year}.jsonl", same_class)
    _append_jsonl(DISTINCT_JSONL_DIR   / f"{year}.jsonl", distinct)

    # 画像コピー（入力元は削除しない）
    n_img_same = n_img_distinct = n_img_missing = 0
    for rec in same_class:
        if _copy_image(rec["source"], rec["target"], SAME_CLASS_IMG_DIR):
            n_img_same += 1
        else:
            n_img_missing += 1
    for rec in distinct:
        if _copy_image(rec["source"], rec["target"], DISTINCT_IMG_DIR):
            n_img_distinct += 1
        else:
            n_img_missing += 1

    return {
        "year":         year,
        "total":        len(records),
        "same_class":   len(same_class),
        "distinct":     len(distinct),
        "img_same":     n_img_same,
        "img_distinct": n_img_distinct,
        "img_missing":  n_img_missing,
    }


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    if not INPUT_JSONL_DIR.exists():
        print(f"入力ディレクトリが見つかりません: {INPUT_JSONL_DIR}", file=sys.stderr)
        sys.exit(1)

    for d in (SAME_CLASS_JSONL_DIR, SAME_CLASS_IMG_DIR,
              DISTINCT_JSONL_DIR,   DISTINCT_IMG_DIR):
        d.mkdir(parents=True, exist_ok=True)

    jsonl_files = sorted(INPUT_JSONL_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"JSONL ファイルが見つかりません: {INPUT_JSONL_DIR}", file=sys.stderr)
        sys.exit(1)

    results = [process_year(p) for p in jsonl_files]

    totals = {k: sum(r[k] for r in results)
              for k in ("total", "same_class", "distinct",
                        "img_same", "img_distinct", "img_missing")}

    print(f"\n{'年':>6}  {'合計':>6}  {'同一ID':>8}  {'異なるID':>10}")
    print("-" * 40)
    for r in results:
        print(f"{r['year']:>6}  {r['total']:>6,}  {r['same_class']:>12,}  {r['distinct']:>6,}")
    print("-" * 40)
    print(f"{'合計':>6}  {totals['total']:>6,}  {totals['same_class']:>12,}  {totals['distinct']:>6,}")

    print(f"\n画像コピー: 同一={totals['img_same']}枚  通過={totals['img_distinct']}枚"
          f"  画像なし={totals['img_missing']}件")
    print(f"\n  同一 JSONL  → {SAME_CLASS_JSONL_DIR}")
    print(f"  同一 画像   → {SAME_CLASS_IMG_DIR}")
    print(f"  通過 JSONL  → {DISTINCT_JSONL_DIR}")
    print(f"  通過 画像   → {DISTINCT_IMG_DIR}")


if __name__ == "__main__":
    # 再実行する場合は出力ディレクトリを事前に削除:
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/same
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/distinct
    main()