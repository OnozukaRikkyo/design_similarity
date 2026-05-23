"""
distinct ペアを reason キーワードで「完全一致」「高類似」「類似」に3分類する。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
前処理フロー（本スクリプトは split_same_id.py と独立して同じ入力を使用）:

  extract_yes_pairs.py
      ↓ {backend}_yes_pairs/          ←【共通入力 JSONL】
      ↓ {backend}_yes_image_pair/     ←【共通入力 画像】
      ├─ split_same_id.py → {backend}/same/jsonl/        （同一特許IDペア）
      │                   → {backend}/same/images/
      └─ split_by_reason.py → {backend}/exact_match/jsonl/    （identical 等）
                            → {backend}/exact_match/images/
                            → {backend}/high_similar/jsonl/   （substantially identical 等）
                            → {backend}/high_similar/images/
                            → {backend}/similar/jsonl/        （通常類似ペア）
                            → {backend}/similar/images/
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

分類ルール（先に高類似を判定し、substantially identical が exact_match に
混入するのを防ぐ）:

  [高類似] HIGH_SIMILAR_PATTERNS にヒット → high_similar
  [完全一致] EXACT_PATTERNS にヒット      → exact_match
  [類似]     どちらにもヒットしない        → similar

入力:
  {backend}_yes_pairs/{year}.jsonl   (extract_yes_pairs.py の出力)
  {backend}_yes_image_pair/          (extract_yes_pairs.py の出力画像)

出力（入力元は削除しない）:
  {backend}/exact_match/jsonl/{year}.jsonl
  {backend}/exact_match/images/
  {backend}/high_similar/jsonl/{year}.jsonl
  {backend}/high_similar/images/
  {backend}/similar/jsonl/{year}.jsonl
  {backend}/similar/images/
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

INPUT_JSONL_DIR = _YES_PAIR_BASE / f"{BACKEND}_yes_pairs"
INPUT_IMG_DIR   = _YES_PAIR_BASE / f"{BACKEND}_yes_image_pair"

_OUT_BASE = _YES_PAIR_BASE / BACKEND

EXACT_JSONL_DIR        = _OUT_BASE / "exact_match"  / "jsonl"
EXACT_IMG_DIR          = _OUT_BASE / "exact_match"  / "images"
HIGH_SIMILAR_JSONL_DIR = _OUT_BASE / "high_similar" / "jsonl"
HIGH_SIMILAR_IMG_DIR   = _OUT_BASE / "high_similar" / "images"
SIMILAR_JSONL_DIR      = _OUT_BASE / "similar"      / "jsonl"
SIMILAR_IMG_DIR        = _OUT_BASE / "similar"      / "images"

# ─── 完全一致パターン ────────────────────────────────────────────────────────
# "identical" 単体を含む（"substantially identical" は先に高類似で捕捉される）。
EXACT_PATTERNS: list[str] = [
    r"\bindistinguishable\b",
    r"\bno\s+discernible\s+differences?\b",
    r"\bidentical\b",
]

# ─── 高類似パターン ──────────────────────────────────────────────────────────
# substantially identical を含む表現や「同一構成」を示すフレーズ。
# EXACT_PATTERNS より先にチェックすることで substantially identical を分離する。
HIGH_SIMILAR_PATTERNS: list[str] = [
    r"\bsubstantially\s+identical\b",
    r"\bmatching\s+proportions?\b",
    r"\bmatching\s+patterns?\b",
    r"\bsame\s+(?:overall\s+)?configuration\b",
    r"\bsame\s+arrangement\b",
    r"\bsame\s+silhouette\b",
    r"\bsame\s+overall\s+shape\b",
]

_EXACT_COMPILED        = [re.compile(p, re.IGNORECASE) for p in EXACT_PATTERNS]
_HIGH_SIMILAR_COMPILED = [re.compile(p, re.IGNORECASE) for p in HIGH_SIMILAR_PATTERNS]


# ---------------------------------------------------------------------------
# パターンマッチ
# ---------------------------------------------------------------------------
def _matched_patterns(reason: str, compiled: list[re.Pattern]) -> list[str]:
    return [pat.pattern for pat in compiled if pat.search(reason)]


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
# 処理済みペアのロード
# ---------------------------------------------------------------------------
def load_done_pairs(*jsonl_dirs: Path) -> set[tuple[str, str]]:
    """出力済み JSONL から処理済み (source, target) ペアを収集する。"""
    done = set()
    for d in jsonl_dirs:
        if not d.exists():
            continue
        for p in d.glob("*.jsonl"):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        done.add((rec["source"], rec["target"]))
                    except (json.JSONDecodeError, KeyError):
                        pass
    return done


# ---------------------------------------------------------------------------
# 年別 JSONL 処理
# ---------------------------------------------------------------------------
def process_year(jsonl_path: Path, done_pairs: set[tuple[str, str]]) -> dict:
    year = jsonl_path.stem

    records = []
    with open(jsonl_path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if (rec["source"], rec["target"]) not in done_pairs:
                    records.append(rec)
            except json.JSONDecodeError as e:
                print(f"  [WARN] parse error {jsonl_path.name}:{lineno}: {e}", file=sys.stderr)

    exact_list, high_similar_list, similar_list = [], [], []

    for rec in records:
        reason = rec.get("reason", "")

        # 高類似を先にチェック（substantially identical を exact に混入させない）
        hs_hits = _matched_patterns(reason, _HIGH_SIMILAR_COMPILED)
        if hs_hits:
            rec["matched_patterns"] = hs_hits
            high_similar_list.append(rec)
            continue

        ex_hits = _matched_patterns(reason, _EXACT_COMPILED)
        if ex_hits:
            rec["matched_patterns"] = ex_hits
            exact_list.append(rec)
            continue

        similar_list.append(rec)

    # JSONL 書き出し（追記）
    def _append_jsonl(path: Path, recs: list[dict]) -> None:
        with open(path, "a", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    _append_jsonl(EXACT_JSONL_DIR        / f"{year}.jsonl", exact_list)
    _append_jsonl(HIGH_SIMILAR_JSONL_DIR / f"{year}.jsonl", high_similar_list)
    _append_jsonl(SIMILAR_JSONL_DIR      / f"{year}.jsonl", similar_list)

    # 画像コピー（入力元は削除しない）
    n_img_exact = n_img_hs = n_img_similar = n_img_missing = 0

    for rec in exact_list:
        if _copy_image(rec["source"], rec["target"], EXACT_IMG_DIR):
            n_img_exact += 1
        else:
            n_img_missing += 1

    for rec in high_similar_list:
        if _copy_image(rec["source"], rec["target"], HIGH_SIMILAR_IMG_DIR):
            n_img_hs += 1
        else:
            n_img_missing += 1

    for rec in similar_list:
        if _copy_image(rec["source"], rec["target"], SIMILAR_IMG_DIR):
            n_img_similar += 1
        else:
            n_img_missing += 1

    return {
        "year":         year,
        "total":        len(records),
        "exact":        len(exact_list),
        "high_similar": len(high_similar_list),
        "similar":      len(similar_list),
        "img_exact":    n_img_exact,
        "img_hs":       n_img_hs,
        "img_similar":  n_img_similar,
        "img_missing":  n_img_missing,
    }


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    if not INPUT_JSONL_DIR.exists():
        print(f"入力ディレクトリが見つかりません: {INPUT_JSONL_DIR}", file=sys.stderr)
        sys.exit(1)

    for d in (EXACT_JSONL_DIR,        EXACT_IMG_DIR,
              HIGH_SIMILAR_JSONL_DIR, HIGH_SIMILAR_IMG_DIR,
              SIMILAR_JSONL_DIR,      SIMILAR_IMG_DIR):
        d.mkdir(parents=True, exist_ok=True)

    jsonl_files = sorted(INPUT_JSONL_DIR.glob("*.jsonl"))
    if not jsonl_files:
        print(f"JSONL ファイルが見つかりません: {INPUT_JSONL_DIR}", file=sys.stderr)
        sys.exit(1)

    done_pairs = load_done_pairs(EXACT_JSONL_DIR, HIGH_SIMILAR_JSONL_DIR, SIMILAR_JSONL_DIR)
    print(f"スキップ対象（処理済みペア）: {len(done_pairs):,} 件")

    results = [process_year(p, done_pairs) for p in jsonl_files]

    totals = {k: sum(r[k] for r in results)
              for k in ("total", "exact", "high_similar", "similar",
                        "img_exact", "img_hs", "img_similar", "img_missing")}

    print(f"\n{'年':>6}  {'合計':>6}  {'完全一致':>8}  {'高類似':>6}  {'類似':>6}")
    print("-" * 44)
    for r in results:
        print(f"{r['year']:>6}  {r['total']:>6,}  {r['exact']:>8,}  "
              f"{r['high_similar']:>6,}  {r['similar']:>6,}")
    print("-" * 44)
    print(f"{'合計':>6}  {totals['total']:>6,}  {totals['exact']:>8,}  "
          f"{totals['high_similar']:>6,}  {totals['similar']:>6,}")

    print(f"\n画像コピー: 完全一致={totals['img_exact']}枚  高類似={totals['img_hs']}枚"
          f"  類似={totals['img_similar']}枚  画像なし={totals['img_missing']}件")

    print(f"\n  完全一致 JSONL → {EXACT_JSONL_DIR}")
    print(f"  完全一致 画像  → {EXACT_IMG_DIR}")
    print(f"  高類似 JSONL   → {HIGH_SIMILAR_JSONL_DIR}")
    print(f"  高類似 画像    → {HIGH_SIMILAR_IMG_DIR}")
    print(f"  類似 JSONL     → {SIMILAR_JSONL_DIR}")
    print(f"  類似 画像      → {SIMILAR_IMG_DIR}")


if __name__ == "__main__":
    # 再実行する場合は出力ディレクトリを事前に削除:
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/exact_match
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/high_similar
    #   rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/similar
    # ※ 入力 (qwen_yes_pairs / qwen_yes_image_pair) は削除しないこと
    main()