#!/usr/bin/env python3
"""
画像ペアに対してベクトルランク検索を実行する。

各ペア (source=A, target=B) について、画像タイプごとに:
  1. A のベクトルを rank_index から取得
  2. 全件ベクトルで A との類似度を計算（A 自身は除外）
  3. B の順位を取得（1-indexed、1 が最も類似）

入力:
    class/{CLASS}/cited_image_pairs/{year}.jsonl
    class/{CLASS}/rank_index/{type}/
        patent_ids.npy
        vectors_l2norm.npy

出力:
    class/{CLASS}/rank_results/{sim_func}/{year}.jsonl
    1 行 1 レコード: source, target, type, rank, n_candidates, similarity

sim_func の選択:
    cosine_numpy  — numpy matmul（L2 正規化済み内積、デフォルト）
    cosine_faiss  — FAISS IndexFlatIP（faiss-cpu インストール時のみ）

実行:
    python compute_ranks.py --class D18
    python compute_ranks.py --class D18 --sim cosine_faiss
    python compute_ranks.py 2007 2008 --class D18 --no-resume
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from tqdm import tqdm

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

CLASS_BASE    = Path("/mnt/eightthdd/uspto/class")
IMAGE_TYPES   = ("perspective", "front", "overview")
DESIGN_OFFSET = 10_000_000_000


def patent_id_to_int(s: str) -> int:
    return DESIGN_OFFSET + int(s.lstrip("D").lstrip("0") or "0")


# ---------------------------------------------------------------------------
# 類似度バックエンド
# ---------------------------------------------------------------------------

class NumpyCosineBackend:
    """L2 正規化済みベクトルに対するコサイン類似度（numpy BLAS）。
    全件と一括内積し、自身を除外して B の順位を O(N) でカウント。"""

    name = "cosine_numpy"

    def __init__(self, vectors: np.ndarray) -> None:
        self.vectors = vectors  # (N, D) float32, L2 正規化済み
        self.N = len(vectors)

    def search_rank(self, query_row: int, target_row: int) -> tuple[int, int, float]:
        """
        Returns (rank_1indexed, n_candidates, similarity_to_target).

        rank_1indexed : 1 が最も類似（自身を除く N-1 件の中での順位）
        n_candidates  : N - 1
        """
        sims = self.vectors @ self.vectors[query_row]  # (N,) BLAS dgemv
        sims[query_row] = -2.0   # 自身を除外（コサイン類似度の範囲は [-1, 1]）
        sim_target = float(sims[target_row])
        rank       = int(np.sum(sims > sim_target)) + 1   # ソート不要、O(N)
        n_cand     = self.N - 1
        return rank, n_cand, sim_target


class FaissCosineBackend:
    """L2 正規化済みベクトルに対するコサイン類似度（FAISS IndexFlatIP）。
    インデックスをクラス・タイプ単位で一度だけ構築して使い回す。"""

    name = "cosine_faiss"

    def __init__(self, vectors: np.ndarray) -> None:
        self.vectors = vectors
        self.N       = len(vectors)
        self.index   = faiss.IndexFlatIP(vectors.shape[1])
        self.index.add(vectors)

    def search_rank(self, query_row: int, target_row: int) -> tuple[int, int, float]:
        query               = self.vectors[query_row].reshape(1, -1)
        sims_sorted, idxs_sorted = self.index.search(query, self.N)
        sims_s = sims_sorted[0]  # (N,) 降順
        idxs_s = idxs_sorted[0]  # (N,) 降順

        # 自身を除く
        mask   = idxs_s != query_row
        sims_f = sims_s[mask]
        idxs_f = idxs_s[mask]

        pos = np.where(idxs_f == target_row)[0]
        if len(pos) == 0:
            return -1, len(sims_f), 0.0
        rank = int(pos[0]) + 1
        sim  = float(sims_f[pos[0]])
        return rank, len(sims_f), sim


def make_backend(
    name: str,
    vectors: np.ndarray,
) -> NumpyCosineBackend | FaissCosineBackend:
    if name == "cosine_numpy":
        return NumpyCosineBackend(vectors)
    if name == "cosine_faiss":
        if not HAS_FAISS:
            print(
                "[警告] faiss がインストールされていません。cosine_numpy で代替します。",
                file=sys.stderr,
            )
            return NumpyCosineBackend(vectors)
        return FaissCosineBackend(vectors)
    raise ValueError(f"未知の類似度関数: {name}")


AVAILABLE_SIMS = ["cosine_numpy"] + (["cosine_faiss"] if HAS_FAISS else [])


# ---------------------------------------------------------------------------
# ランクインデックス（タイプ別、遅延ロード）
# ---------------------------------------------------------------------------

class RankIndex:
    def __init__(self, target_class: str, sim_name: str) -> None:
        self.base     = CLASS_BASE / target_class / "rank_index"
        self.sim_name = sim_name
        self._backends: dict[str, NumpyCosineBackend | FaissCosineBackend] = {}
        self._id2row:   dict[str, dict[int, int]] = {}

    def load(self, img_type: str) -> bool:
        """未ロードなら rank_index/{type}/ を読み込む。成功時 True を返す。"""
        if img_type in self._backends:
            return True
        d     = self.base / img_type
        ids_f = d / "patent_ids.npy"
        vec_f = d / "vectors_l2norm.npy"
        if not ids_f.exists() or not vec_f.exists():
            return False
        ids  = np.load(ids_f)
        vecs = np.load(vec_f)
        self._id2row[img_type]   = {int(pid): i for i, pid in enumerate(ids)}
        self._backends[img_type] = make_backend(self.sim_name, vecs)
        tqdm.write(
            f"  [index loaded] {img_type}: {len(ids):,} 件  "
            f"shape={vecs.shape}"
        )
        return True

    def get_row(self, img_type: str, patent_id_int: int) -> int | None:
        return self._id2row.get(img_type, {}).get(patent_id_int)

    def backend(self, img_type: str) -> NumpyCosineBackend | FaissCosineBackend:
        return self._backends[img_type]


# ---------------------------------------------------------------------------
# 年ごとの処理
# ---------------------------------------------------------------------------

def process_year(
    year: str,
    target_class: str,
    rank_index: RankIndex,
    sim_name: str,
    resume: bool,
) -> None:
    in_path  = CLASS_BASE / target_class / "cited_image_pairs" / f"{year}.jsonl"
    out_dir  = CLASS_BASE / target_class / "rank_results" / sim_name
    out_path = out_dir / f"{year}.jsonl"

    if not in_path.exists():
        return
    lines = [l for l in in_path.read_text().splitlines() if l.strip()]
    if not lines:
        return

    if resume and out_path.exists():
        tqdm.write(f"[{year}] 処理済み → スキップ ({out_path})")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    with open(out_path, "w") as fout:
        for line in tqdm(
            lines, desc=year, unit="ペア", leave=False, dynamic_ncols=True
        ):
            rec    = json.loads(line)
            src_id = patent_id_to_int(rec["source"])
            tgt_id = patent_id_to_int(rec["target"])

            for img_type in IMAGE_TYPES:
                if img_type not in rec.get("source_images", {}):
                    continue
                if img_type not in rec.get("target_images", {}):
                    continue
                if not rank_index.load(img_type):
                    continue

                src_row = rank_index.get_row(img_type, src_id)
                tgt_row = rank_index.get_row(img_type, tgt_id)
                if src_row is None or tgt_row is None:
                    continue

                rank, n_cand, sim = rank_index.backend(img_type).search_rank(
                    src_row, tgt_row
                )
                out_rec = {
                    "source":       rec["source"],
                    "target":       rec["target"],
                    "type":         img_type,
                    "rank":         rank,
                    "n_candidates": n_cand,
                    "similarity":   round(sim, 6),
                }
                fout.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
                n_written += 1

    tqdm.write(f"[{year}] {n_written:,} 件 → {out_path}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="画像ペアに対するベクトルランク検索を実行する"
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年（例: 2007 2008）。省略時は全年。",
    )
    parser.add_argument(
        "--class", dest="target_class", default="D18", metavar="CLASS",
        help="対象クラスコード（デフォルト: D18）",
    )
    parser.add_argument(
        "--sim", default="cosine_numpy",
        choices=["cosine_numpy", "cosine_faiss"],
        help="類似度計算バックエンド（デフォルト: cosine_numpy）",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="処理済みファイルを上書きする",
    )
    args = parser.parse_args()

    pairs_dir = CLASS_BASE / args.target_class / "cited_image_pairs"
    years = args.years or [
        p.stem for p in sorted(pairs_dir.glob("[0-9]*.jsonl"))
    ]

    print(f"対象クラス  : {args.target_class}")
    print(f"類似度関数  : {args.sim}")
    print(f"処理対象年  : {years}\n")

    rank_index = RankIndex(args.target_class, args.sim)

    with tqdm(years, desc="全体", unit="年", position=0, leave=True) as pbar:
        for year in pbar:
            pbar.set_description(f"全体 [{year}]")
            process_year(
                year, args.target_class, rank_index, args.sim,
                resume=not args.no_resume,
            )

    print("\n完了")


if __name__ == "__main__":
    main()
