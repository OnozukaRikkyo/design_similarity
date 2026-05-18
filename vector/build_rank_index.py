#!/usr/bin/env python3
"""
年別ベクトルを結合・重複排除し、ランク検索用インデックスを構築する。

年をまたいで同一特許が現れる場合は最初の出現のみ採用する。
ベクトルは L2 正規化してコサイン類似度を内積で計算できる形で保存する。

入力:
    class/{CLASS}/cited_image_vectors/{type}/
        patent_ids_{year}.npy
        vectors_{year}.npy
        file_paths_{year}.txt

出力:
    class/{CLASS}/rank_index/{type}/
        patent_ids.npy       (N,) int64   — ユニーク特許 ID（昇順）
        vectors_l2norm.npy   (N, D) float32 — L2 正規化済みベクトル
        file_paths.txt       N 行          — 元画像パス

実行:
    python build_rank_index.py --class D18
    python build_rank_index.py --class D10 --no-resume
"""

import argparse
from pathlib import Path

import numpy as np
from tqdm import tqdm

CLASS_BASE  = Path("/mnt/eightthdd/uspto/class")
IMAGE_TYPES = ("perspective", "front", "overview")


def build_index_for_type(
    vec_dir: Path,
    out_dir: Path,
    img_type: str,
    resume: bool,
) -> None:
    out_ids  = out_dir / "patent_ids.npy"
    out_vecs = out_dir / "vectors_l2norm.npy"
    out_fp   = out_dir / "file_paths.txt"

    year_files = sorted(vec_dir.glob("vectors_*.npy"))
    if not year_files:
        tqdm.write(f"  [{img_type}] ベクトルファイルなし → スキップ")
        return

    if resume and out_ids.exists():
        n = len(np.load(out_ids))
        tqdm.write(f"  [{img_type}] 処理済み ({n:,} 件) → スキップ")
        return

    all_ids: list[np.ndarray] = []
    all_vecs: list[np.ndarray] = []
    all_paths: list[str] = []

    for vf in year_files:
        year  = vf.stem.replace("vectors_", "")
        ids_f = vec_dir / f"patent_ids_{year}.npy"
        fp_f  = vec_dir / f"file_paths_{year}.txt"
        ids   = np.load(ids_f)
        vecs  = np.load(vf)
        paths = fp_f.read_text().splitlines() if fp_f.exists() else [""] * len(ids)
        all_ids.append(ids)
        all_vecs.append(vecs)
        all_paths.extend(paths)

    patent_ids = np.concatenate(all_ids)
    vectors    = np.concatenate(all_vecs, axis=0).astype(np.float32)

    # 重複排除: patent_id 昇順で最初の出現インデックスを採用
    _, first_idx = np.unique(patent_ids, return_index=True)
    patent_ids = patent_ids[first_idx]
    vectors    = vectors[first_idx]
    all_paths  = [all_paths[i] for i in first_idx]

    # L2 正規化（コサイン類似度 = 正規化後の内積）
    norms   = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms   = np.where(norms == 0, 1.0, norms)
    vectors = (vectors / norms).astype(np.float32)

    out_dir.mkdir(parents=True, exist_ok=True)
    np.save(out_ids,  patent_ids)
    np.save(out_vecs, vectors)
    out_fp.write_text("\n".join(all_paths))

    tqdm.write(
        f"  [{img_type}] {len(patent_ids):,} 件  "
        f"shape={vectors.shape}  → {out_dir}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="年別ベクトルを結合してランク検索用インデックスを構築する"
    )
    parser.add_argument(
        "--class", dest="target_class", default="D18", metavar="CLASS",
        help="対象クラスコード（デフォルト: D18）",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="処理済みファイルを上書きする",
    )
    args = parser.parse_args()

    vec_base = CLASS_BASE / args.target_class / "cited_image_vectors"
    idx_base = CLASS_BASE / args.target_class / "rank_index"

    print(f"対象クラス  : {args.target_class}")
    print(f"入力        : {vec_base}")
    print(f"出力        : {idx_base}\n")

    for img_type in tqdm(IMAGE_TYPES, desc="タイプ", unit="type"):
        build_index_for_type(
            vec_dir  = vec_base / img_type,
            out_dir  = idx_base / img_type,
            img_type = img_type,
            resume   = not args.no_resume,
        )

    print("\n完了")


if __name__ == "__main__":
    main()
