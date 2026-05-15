"""
Yes 判定ペアから「完全一致」を示すレコードを 2 段階で除外する。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[第1段階] ID 同一除外  ← 本スクリプトで最初に実行（絶対除外）
  条件: id_diff <= ID_EXACT_THRESHOLD（デフォルト 0 = 完全一致のみ）
  JSONL → {backend}_same_id_pairs/{year}.jsonl
  画像  → {backend}_same_id_image_pair/  （yes_image_pair から移動）

[第2段階] キーワード除外
  条件: reason が EXACT_PATTERNS にヒット、または id_diff <= ID_DIFF_THRESHOLD
  JSONL → {backend}_exact_pairs/{year}.jsonl
  画像  → {backend}_exact_image_pair/  （yes_image_pair から移動）

[通過]
  JSONL → {backend}_distinct_pairs/{year}.jsonl
  画像  → {backend}_yes_image_pair/ に残留（移動なし）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

入力:
  {backend}_yes_pairs/{year}.jsonl   (extract_yes_pairs.py の出力)
  {backend}_yes_image_pair/          (extract_yes_pairs.py の出力画像)
"""

import json
import re
import shutil
import sys
from pathlib import Path

# ─── バックエンド選択（ここを編集して切り替える） ───────────────────────────
BACKEND = "qwen"   # "gemini" | "qwen"

# ─── 第1段階: ID 同一除外の閾値 ────────────────────────────────────────────
# id_diff <= この値のペアを絶対除外する。
#   0 = source と target が完全に同一 ID のペアのみ
#   5 = 連番登録バリアント（diff=1–5）も含めて除外する場合は 5 に変更
ID_EXACT_THRESHOLD: int = 0

# ─── 第2段階: キーワード除外 ──────────────────────────────────────────────
# id_diff <= この値も第2段階で除外する（0 にすると ID 差による除外を無効化）
ID_DIFF_THRESHOLD: int = 5

# 各要素は re.compile に渡す正規表現文字列。
# "substantially identical" は法的な類似性判断の常套句なので対象外。
EXACT_PATTERNS: list[str] = [
    # 設計全体が識別不能・同一であると述べる表現
    r"\bindistinguishable\b",
    r"\bare\s+identical\b",
    r"\bappear(?:s)?\s+identical\b",
    r"\blook(?:s)?\s+identical\b",
    r"\bseem(?:s)?\s+identical\b",
    r"\bidentical\s+design(?:s)?\b",
    r"\bidentical\s+in\s+every\b",
    r"\bidentical\s+in\s+all\b",
    r"\bthe\s+identical\b",
    # virtually / practically identical（全体的な同一性を示す副詞付き）
    r"\bvirtually\s+identical\b",
    r"\bnearly\s+identical\b",
    r"\bpractically\s+identical\b",
    r"\bessentially\s+identical\b",
    r"\beffectively\s+identical\b",
    # 完全コピー・複製を示す表現
    r"\bexact\s+(?:copy|replica|duplicate|match|same)\b",
    r"\bperfect\s+(?:copy|replica|duplicate|match)\b",
    # 「same design/product/model」系
    r"\bsame\s+design\b",
    r"\bsame\s+\w+\s+design\b",
    r"\bsame\s+\w+\s+model\b",
    r"\bsame\s+product\b",
    r"\bappear(?:s)?\s+to\s+be\s+the\s+same\b",
    r"\bseem(?:s)?\s+to\s+be\s+the\s+same\b",
    # 同一製品の異なる視点・状態（= 実質同一オブジェクト）
    r"\bdifferent\s+(?:views?|angles?|states?|perspectives?|orientations?)\s+of\s+the\s+same\b",
    # ほぼ区別不能
    r"\bvirtually\s+indistinguishable\b",
    r"\bnearly\s+indistinguishable\b",
    r"\bpractically\s+indistinguishable\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in EXACT_PATTERNS]


# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
_YES_PAIR_BASE = Path("/mnt/eightthdd/uspto/yes_pair")

INPUT_JSONL_DIR  = _YES_PAIR_BASE / f"{BACKEND}_yes_pairs"
INPUT_IMG_DIR    = _YES_PAIR_BASE / f"{BACKEND}_yes_image_pair"

SAME_ID_JSONL_DIR = _YES_PAIR_BASE / f"{BACKEND}_same_id_pairs"
SAME_ID_IMG_DIR   = _YES_PAIR_BASE / f"{BACKEND}_same_id_image_pair"

EXACT_JSONL_DIR  = _YES_PAIR_BASE / f"{BACKEND}_exact_pairs"
EXACT_IMG_DIR    = _YES_PAIR_BASE / f"{BACKEND}_exact_image_pair"

DISTINCT_JSONL_DIR = _YES_PAIR_BASE / f"{BACKEND}_distinct_pairs"
# 通過した画像は INPUT_IMG_DIR に残留するため専用ディレクトリなし


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def _img_name(src: str, tgt: str) -> str:
    return f"{src}__{tgt}.png"


def _move_image(src: str, tgt: str, dst_dir: Path) -> bool:
    """yes_image_pair から dst_dir へ画像を移動する。存在しない場合は False を返す。"""
    src_path = INPUT_IMG_DIR / _img_name(src, tgt)
    if not src_path.exists():
        return False
    shutil.move(str(src_path), dst_dir / src_path.name)
    return True


def _find_patterns(reason: str) -> list[str]:
    return [p.pattern for p in _COMPILED if p.search(reason)]


# ---------------------------------------------------------------------------
# 第1段階: ID 同一除外
# ---------------------------------------------------------------------------
def stage1_same_id(
    records: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    id_diff <= ID_EXACT_THRESHOLD のレコードを same_id として分離する。
    戻り値: (remaining, same_id_list)
    """
    remaining, same_id = [], []
    for rec in records:
        id_diff = rec.get("id_diff")
        if id_diff is not None and id_diff <= ID_EXACT_THRESHOLD:
            rec["excluded_reason"] = "same_id"
            same_id.append(rec)
        else:
            remaining.append(rec)
    return remaining, same_id


# ---------------------------------------------------------------------------
# 第2段階: キーワード除外
# ---------------------------------------------------------------------------
def stage2_keyword(
    records: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    EXACT_PATTERNS または id_diff <= ID_DIFF_THRESHOLD にヒットするレコードを分離する。
    戻り値: (distinct, exact_list)
    """
    distinct, exact = [], []
    for rec in records:
        reason   = rec.get("reason", "")
        matched  = _find_patterns(reason)
        id_diff  = rec.get("id_diff")
        id_hit   = (id_diff is not None and id_diff <= ID_DIFF_THRESHOLD)

        if matched or id_hit:
            if matched:
                rec["matched_patterns"] = matched
            if id_hit:
                rec["excluded_by_id_diff"] = True
            rec.setdefault("excluded_reason", "keyword_or_id_diff")
            exact.append(rec)
        else:
            distinct.append(rec)
    return distinct, exact


# ---------------------------------------------------------------------------
# 年別 JSONL 処理
# ---------------------------------------------------------------------------
def process_year(jsonl_path: Path) -> dict:
    """
    1 ファイルを処理してカウント辞書を返す。
    出力ファイルは追記モード（再実行前に出力ディレクトリを削除すること）。
    """
    year = jsonl_path.stem

    # --- 読み込み ---
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

    # --- 第1段階: ID 同一除外 ---
    remaining, same_id_list = stage1_same_id(records)

    # --- 第2段階: キーワード除外 ---
    distinct_list, exact_list = stage2_keyword(remaining)

    # --- JSONL 書き出し ---
    def _append_jsonl(path: Path, recs: list[dict]) -> None:
        with open(path, "a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _append_jsonl(SAME_ID_JSONL_DIR   / f"{year}.jsonl", same_id_list)
    _append_jsonl(EXACT_JSONL_DIR     / f"{year}.jsonl", exact_list)
    _append_jsonl(DISTINCT_JSONL_DIR  / f"{year}.jsonl", distinct_list)

    # --- 画像移動 ---
    n_img_same = n_img_exact = n_img_missing = 0

    for rec in same_id_list:
        moved = _move_image(rec["source"], rec["target"], SAME_ID_IMG_DIR)
        if moved:
            n_img_same += 1
        else:
            n_img_missing += 1

    for rec in exact_list:
        moved = _move_image(rec["source"], rec["target"], EXACT_IMG_DIR)
        if moved:
            n_img_exact += 1
        else:
            n_img_missing += 1

    return {
        "year":         year,
        "total":        len(records),
        "same_id":      len(same_id_list),
        "exact":        len(exact_list),
        "distinct":     len(distinct_list),
        "img_same":     n_img_same,
        "img_exact":    n_img_exact,
        "img_missing":  n_img_missing,
    }


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    if not INPUT_JSONL_DIR.exists():
        print(f"入力ディレクトリが見つかりません: {INPUT_JSONL_DIR}", file=sys.stderr)
        sys.exit(1)

    for d in (SAME_ID_JSONL_DIR, SAME_ID_IMG_DIR,
              EXACT_JSONL_DIR,   EXACT_IMG_DIR,
              DISTINCT_JSONL_DIR):
        d.mkdir(parents=True, exist_ok=True)

    jsonl_files = sorted(INPUT_JSONL_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"JSONL ファイルが見つかりません: {INPUT_JSONL_DIR}", file=sys.stderr)
        sys.exit(1)

    results = [process_year(p) for p in jsonl_files]

    # --- サマリ表示 ---
    totals = {k: sum(r[k] for r in results)
              for k in ("total", "same_id", "exact", "distinct", "img_same", "img_exact", "img_missing")}

    print(f"\n{'年':>6}  {'合計':>6}  {'同一ID':>6}  {'キーワード':>10}  {'通過':>6}")
    print("-" * 46)
    for r in results:
        print(f"{r['year']:>6}  {r['total']:>6,}  {r['same_id']:>6,}  {r['exact']:>10,}  {r['distinct']:>6,}")
    print("-" * 46)
    print(f"{'合計':>6}  {totals['total']:>6,}  {totals['same_id']:>6,}  {totals['exact']:>10,}  {totals['distinct']:>6,}")

    print(f"\n画像移動: 同一ID={totals['img_same']}枚  キーワード={totals['img_exact']}枚"
          f"  画像なし={totals['img_missing']}件")

    print(f"\n  同一ID JSONL  → {SAME_ID_JSONL_DIR}")
    print(f"  同一ID 画像   → {SAME_ID_IMG_DIR}")
    print(f"  除外 JSONL    → {EXACT_JSONL_DIR}")
    print(f"  除外 画像     → {EXACT_IMG_DIR}")
    print(f"  通過 JSONL    → {DISTINCT_JSONL_DIR}")
    print(f"  通過 画像     → {INPUT_IMG_DIR}  （残留）")


if __name__ == "__main__":
    # 再実行する場合は出力ディレクトリを事前に削除:
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen_same_id_pairs
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen_same_id_image_pair
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen_exact_pairs
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen_exact_image_pair
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen_distinct_pairs
    main()