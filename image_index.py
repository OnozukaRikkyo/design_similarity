#!/usr/bin/env python3
"""
特許画像インデックス: 特許 ID → 画像ファイルパスのマッピングを提供する共通ライブラリ。

正規データソース: /mnt/eightthdd/uspto/data/{year}.csv
  2007〜2022 年の全特許を網羅。
  id / file_names / fig_desc 列から特許 ID・D00000 画像パス・タイプを取得する。

タイプ判定ルール (image_vector_no_text.py の detect_type() と同一):
  perspective : fig_desc リストのいずれかに "perspective" を含む
  front       : perspective がなく "front (view|elevation|elevational|plan)" を含む
  overview    : 上記いずれにも該当しない場合にフォールバック

公開インターフェース:
  DESIGN_OFFSET                     int定数
  IMAGE_TYPES                       list[str]
  patent_id_int(did)                str → int | None
  detect_image_type(fig_desc_list)  list[str] → str
  load_image_index(rebuild=False)   dict[int, dict[str, str]]
"""

import ast
import pickle
import re
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
DATA_DIR     = Path("/mnt/eightthdd/uspto/data")
IMG_BASE_DIR = Path("/mnt/eightthdd/impact/images")
INDEX_CACHE  = Path("/mnt/eightthdd/uspto/_image_index.pkl")

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
DESIGN_OFFSET = 10_000_000_000
IMAGE_TYPES   = ["front", "overview", "perspective"]

_D_PATTERN = re.compile(r"D0*(\d+)", re.IGNORECASE)
_PERSP_RE  = re.compile(r"\bperspective\b", re.IGNORECASE)
_FRONT_RE  = re.compile(r"\bfront\s+(view|elevation|elevational|plan)\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# 公開ユーティリティ
# ---------------------------------------------------------------------------
def patent_id_int(did: str) -> int | None:
    """
    意匠特許 ID 文字列を整数キーに変換する。

    Examples
    --------
    'D0543613'  → 10_000_543_613
    'D543613'   → 10_000_543_613
    """
    m = _D_PATTERN.search(str(did))
    return (DESIGN_OFFSET + int(m.group(1))) if m else None


def detect_image_type(fig_desc_list: list[str]) -> str:
    """
    fig_desc リスト（1特許のすべての図説明）からタイプを判定する。

    image_vector_no_text.py の detect_type() と同一ロジック。
    タイプは常に 1 つ (perspective / front / overview のいずれか)。
    """
    for desc in fig_desc_list:
        if _PERSP_RE.search(str(desc)):
            return "perspective"
    for desc in fig_desc_list:
        if _FRONT_RE.search(str(desc)):
            return "front"
    return "overview"


# ---------------------------------------------------------------------------
# インデックス構築（内部）
# ---------------------------------------------------------------------------
def _build_index() -> dict[int, dict[str, str]]:
    print(f"画像インデックス構築中 (ソース: {DATA_DIR}) ...", flush=True)
    index: dict[int, dict[str, str]] = {}

    csv_files = sorted(DATA_DIR.glob("[0-9]*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"data CSV が見つかりません: {DATA_DIR}")

    for csv_file in csv_files:
        df = pd.read_csv(csv_file, usecols=["id", "file_names", "fig_desc"])
        n_added = 0

        for _, row in df.iterrows():
            pid = patent_id_int(str(row["id"]))
            if pid is None:
                continue
            try:
                fnames = ast.literal_eval(row["file_names"]) if pd.notna(row["file_names"]) else []
                fdesc  = ast.literal_eval(row["fig_desc"])   if pd.notna(row["fig_desc"])   else []
            except (ValueError, SyntaxError):
                continue
            if not fnames:
                continue

            fname  = fnames[0]                              # 常に D00000 を使用
            year   = fname.split("-")[1][:4]                # "USD0543613-20070529-D00000.TIF" → "2007"
            path   = str(IMG_BASE_DIR / year / fname)
            itype  = detect_image_type([str(d) for d in fdesc])
            index.setdefault(pid, {})[itype] = path
            n_added += 1

        print(f"  {csv_file.name}: {len(df):,} 件  ({n_added:,} 件登録)")

    print(f"合計 {len(index):,} 件の特許を登録")
    return index


# ---------------------------------------------------------------------------
# 公開インターフェース
# ---------------------------------------------------------------------------
def load_image_index(rebuild: bool = False) -> dict[int, dict[str, str]]:
    """
    特許画像インデックスをロードする。初回はキャッシュを作成する。

    Parameters
    ----------
    rebuild : bool
        True の場合キャッシュを無視して再構築する。

    Returns
    -------
    dict[int, dict[str, str]]
        { patent_id_int: { image_type: "/path/to/D00000.TIF" } }
        image_type は "front" / "overview" / "perspective" のいずれか。
    """
    if not rebuild and INDEX_CACHE.exists():
        print(f"キャッシュから画像インデックスをロード: {INDEX_CACHE}", flush=True)
        with open(INDEX_CACHE, "rb") as f:
            return pickle.load(f)

    index = _build_index()
    INDEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_CACHE, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"インデックスをキャッシュ: {INDEX_CACHE}")
    return index


# ---------------------------------------------------------------------------
# CLI (単体確認・再構築)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    rebuild = "--rebuild" in sys.argv
    idx = load_image_index(rebuild=rebuild)

    query_ids = [a for a in sys.argv[1:] if not a.startswith("-")]
    if query_ids:
        for did in query_ids:
            pid = patent_id_int(did)
            print(f"{did} → {idx.get(pid)}")
    else:
        types = {"front": 0, "overview": 0, "perspective": 0}
        for entry in idx.values():
            for t in entry:
                types[t] = types.get(t, 0) + 1
        print(f"\nfront={types['front']:,}  overview={types['overview']:,}  perspective={types['perspective']:,}")