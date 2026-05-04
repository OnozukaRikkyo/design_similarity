#!/usr/bin/env python3
"""
共引用エッジリストから、同じ図タイプの画像ペアを抽出する。

エッジの意味:
    source と target は同一出願審査で共に引用された意匠特許（類似とみなされる）。
    source < target でアルファベット順に正規化済み。

入力:
    /mnt/eightthdd/uspto/edge_list/{year}.csv        (build_edge_list.py の出力)
    /mnt/eightthdd/uspto/image_numpy_data_no_text/

出力:
    /mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl  (1行=1ユニークペア)
    フィールド:
        source          : 意匠ID (例: "D0535736")
        target          : 意匠ID (例: "D0543613", source < target)
        source_images   : {image_type: file_path, ...}  利用可能な全タイプ
        target_images   : {image_type: file_path, ...}  利用可能な全タイプ
        events          : [{patentApplicationNumber, officeActionDate,
                            officeActionCategory, citationCategoryCode,
                            examinerCitedReferenceIndicator,
                            applicantCitedExaminerReferenceIndicator,
                            workGroup, groupArtUnitNumber, techCenter}, ...]
                          同一ペアを繋いだ全出願のレコード（重複除去済み）

    出力条件: source と target が少なくとも1つの共通図タイプを持つ場合のみ
"""

import csv
import json
import pickle
import re
import sys
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
IMG_DATA_DIR = Path("/mnt/eightthdd/uspto/image_numpy_data_no_text")
EDGE_DIR     = Path("/mnt/eightthdd/uspto/edge_list")
OUT_DIR      = Path("/mnt/eightthdd/uspto/cited_image_pairs")
INDEX_CACHE  = OUT_DIR / "_image_index.pkl"

DESIGN_OFFSET = 10_000_000_000
IMAGE_TYPES   = ["front", "overview", "perspective"]

D_PATTERN = re.compile(r"D0*(\d+)", re.IGNORECASE)

EDGE_ATTRS = [
    "patentApplicationNumber",
    "officeActionDate",
    "officeActionCategory",
    "citationCategoryCode",
    "examinerCitedReferenceIndicator",
    "applicantCitedExaminerReferenceIndicator",
    "workGroup",
    "groupArtUnitNumber",
    "techCenter",
]


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def patent_id_int(did: str) -> int | None:
    """'D0543613' → 10000543613"""
    m = D_PATTERN.search(did)
    if not m:
        return None
    return DESIGN_OFFSET + int(m.group(1))


# ---------------------------------------------------------------------------
# グローバル画像インデックス構築
#
# 構造:
#   image_ids_{year}.npy          shape (N,) int64  : 全特許 ID
#   image_meta_{year}_{type}.npy  shape (M,) int32  : image_ids へのインデックス
#   image_files_{year}_{type}.txt M 行              : 対応する画像ファイルパス
#
# 出力: { patent_id_int: { image_type: file_path } }
# ---------------------------------------------------------------------------
def build_image_index(img_data_dir: Path, use_cache: bool = True) -> dict[int, dict[str, str]]:
    if use_cache and INDEX_CACHE.exists():
        print(f"キャッシュから画像インデックスをロード: {INDEX_CACHE}", flush=True)
        with open(INDEX_CACHE, "rb") as f:
            return pickle.load(f)

    print("画像インデックス構築中...", end=" ", flush=True)
    index: dict[int, dict[str, str]] = {}

    for id_file in sorted(img_data_dir.glob("image_ids_*.npy")):
        m = re.search(r"image_ids_(\d+)\.npy", id_file.name)
        if not m:
            continue
        year = m.group(1)
        ids = np.load(id_file)

        for img_type in IMAGE_TYPES:
            meta_file = img_data_dir / f"image_meta_{year}_{img_type}.npy"
            list_file  = img_data_dir / f"image_files_{year}_{img_type}.txt"
            if not meta_file.exists() or not list_file.exists():
                continue

            meta = np.load(meta_file)
            with open(list_file) as f:
                paths = f.read().splitlines()

            for idx, path in zip(meta, paths):
                pid = int(ids[idx])
                entry = index.setdefault(pid, {})
                if img_type not in entry:
                    entry[img_type] = path

    print(f"{len(index):,} 件の特許を登録")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(INDEX_CACHE, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"インデックスをキャッシュ: {INDEX_CACHE}")

    return index


# ---------------------------------------------------------------------------
# ペア抽出
# ---------------------------------------------------------------------------
def extract_pairs(edge_csv: Path, index: dict[int, dict[str, str]], out_jsonl: Path) -> None:
    print(f"処理中: {edge_csv.name}", end=" ... ", flush=True)
    n_skip_id = n_skip_img = 0

    # (source, target) → record を集約
    pairs: dict[tuple[str, str], dict] = {}

    with open(edge_csv, newline="", encoding="utf-8") as in_f:
        for row in csv.DictReader(in_f):
            src_pid = patent_id_int(row["source"])
            tgt_pid = patent_id_int(row["target"])
            if src_pid is None or tgt_pid is None:
                n_skip_id += 1
                continue

            src_imgs = index.get(src_pid, {})
            tgt_imgs = index.get(tgt_pid, {})

            if not any(t in tgt_imgs for t in src_imgs):
                n_skip_img += 1
                continue

            key = (row["source"], row["target"])
            if key not in pairs:
                pairs[key] = {
                    "source":        row["source"],
                    "target":        row["target"],
                    "source_images": src_imgs,
                    "target_images": tgt_imgs,
                    "events":        [],
                }

            event = {attr: row.get(attr, "") for attr in EDGE_ATTRS}
            # 同一イベントの重複を避ける（同一 appNo + date の行が複数ある場合）
            if event not in pairs[key]["events"]:
                pairs[key]["events"].append(event)

    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(out_jsonl, "w", encoding="utf-8") as out_f:
        for record in pairs.values():
            out_f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(
        f"ペア: {len(pairs):,}  "
        f"スキップ(ID不正): {n_skip_id:,}  "
        f"スキップ(画像なし): {n_skip_img:,}  "
        f"→ {out_jsonl}"
    )


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main(years: list[str] | None = None, rebuild_index: bool = False) -> None:
    index = build_image_index(IMG_DATA_DIR, use_cache=not rebuild_index)

    if years is None:
        edge_files = sorted(EDGE_DIR.glob("*.csv"))
    else:
        edge_files = [EDGE_DIR / f"{y}.csv" for y in years]

    for edge_csv in edge_files:
        if not edge_csv.exists():
            print(f"エッジリストが見つかりません: {edge_csv}", file=sys.stderr)
            continue
        out_jsonl = OUT_DIR / edge_csv.name.replace(".csv", ".jsonl")
        extract_pairs(edge_csv, index, out_jsonl)

    print("完了")


if __name__ == "__main__":
    # 使い方:
    #   python extract_cited_image_pairs.py            # 全年処理
    #   python extract_cited_image_pairs.py 2007 2008  # 指定年のみ
    #   python extract_cited_image_pairs.py --rebuild  # インデックス再構築
    args = sys.argv[1:]
    rebuild = "--rebuild" in args
    years = [a for a in args if a != "--rebuild"] or None
    main(years, rebuild_index=rebuild)