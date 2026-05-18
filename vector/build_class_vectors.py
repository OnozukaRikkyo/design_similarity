#!/usr/bin/env python3
"""
指定クラスの引用ペアから画像ベクトルを生成・保存する。

処理の優先順位:
  1. cited_image_vectors/ に既存ベクトルがあれば → そのままコピー（再計算不要）
  2. 見つからなければ → Qwen3-VL-Embedding-2B で生成

入力:
    /mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/{year}.jsonl
    /mnt/eightthdd/uspto/cited_image_vectors/{type}/    ← 既存ベクトルの参照元

出力:
    /mnt/eightthdd/uspto/class/{CLASS}/cited_image_vectors/{type}/
        patent_ids_{year}.npy   (N,) int64
        vectors_{year}.npy      (N, D) float32
        file_paths_{year}.txt   N 行
        _checkpoint_{year}.pkl  (処理中のみ)

実行:
    # D18（デフォルト）GPU 使用
    python build_class_vectors.py

    # 別クラス
    python build_class_vectors.py --class D5

    # GPU なしで動作確認
    python build_class_vectors.py --no-gpu

    # 指定年のみ
    python build_class_vectors.py 2007 2008 --class D18

    # チェックポイントを無視して最初から
    python build_class_vectors.py --no-resume
"""

import argparse
import json
import pickle
import re
import sys
from pathlib import Path

import numpy as np
import torch
from tqdm import tqdm

# ImageProcessor: design_similarity ディレクトリから共有
sys.path.insert(0, str(Path(__file__).parent.parent))
from image_processor import ImageProcessor  # noqa: E402

# ---------------------------------------------------------------------------
# パス定数（クラス非依存部分）
# ---------------------------------------------------------------------------
CLASS_BASE       = Path("/mnt/eightthdd/uspto/class")
EXISTING_VEC_DIR = Path("/mnt/eightthdd/uspto/cited_image_vectors")

MODEL_ID   = "Qwen/Qwen3-VL-Embedding-2B"
BATCH_SIZE = 8
MAX_PIXELS = 768 * 768
FIXED_TEXT = "Design Patent Drawing."

DESIGN_OFFSET = 10_000_000_000
D_PATTERN     = re.compile(r"D0*(\d+)", re.IGNORECASE)
IMAGE_TYPES   = ("perspective", "front", "overview")


def pairs_dir(target_class: str) -> Path:
    return CLASS_BASE / target_class / "cited_image_pairs"


def out_dir(target_class: str) -> Path:
    return CLASS_BASE / target_class / "cited_image_vectors"


# ---------------------------------------------------------------------------
# 既存ベクトルインデックス
# ---------------------------------------------------------------------------
class ExistingVectorIndex:
    """
    cited_image_vectors/ を全走査して
    (image_type, patent_id_int) → (year, row) のインデックスを構築する。
    ベクトルファイルはオンデマンドでロード・キャッシュする。
    """

    def __init__(self, vec_dir: Path):
        self._vec_dir = vec_dir
        self._idx: dict[tuple[str, int], tuple[str, int]] = {}
        self._cache: dict[tuple[str, str], np.ndarray] = {}
        n = self._build()
        print(f"既存ベクトルインデックス: {n:,} エントリ ({vec_dir})")

    def _build(self) -> int:
        count = 0
        for vtype in IMAGE_TYPES:
            type_dir = self._vec_dir / vtype
            if not type_dir.exists():
                continue
            for ids_path in sorted(type_dir.glob("patent_ids_*.npy")):
                year = ids_path.stem.replace("patent_ids_", "")
                vec_path = type_dir / f"vectors_{year}.npy"
                if not vec_path.exists():
                    continue
                ids = np.load(ids_path)
                for row, pid in enumerate(ids):
                    key = (vtype, int(pid))
                    if key not in self._idx:
                        self._idx[key] = (year, row)
                        count += 1
        return count

    def get(self, patent_id_int: int, vtype: str) -> np.ndarray | None:
        key = (vtype, patent_id_int)
        if key not in self._idx:
            return None
        year, row = self._idx[key]
        cache_key = (vtype, year)
        if cache_key not in self._cache:
            self._cache[cache_key] = np.load(
                self._vec_dir / vtype / f"vectors_{year}.npy"
            )
        return self._cache[cache_key][row]


# ---------------------------------------------------------------------------
# JSONL からペア情報を収集
# ---------------------------------------------------------------------------
def patent_id_int(did: str) -> int | None:
    m = D_PATTERN.search(did)
    return DESIGN_OFFSET + int(m.group(1)) if m else None


def load_pairs(target_class: str) -> dict[str, dict[str, dict[int, str]]]:
    """
    class/{CLASS}/cited_image_pairs/*.jsonl を走査し、
    year → image_type → {patent_id_int: file_path} を返す。
    """
    p_dir = pairs_dir(target_class)
    result: dict[str, dict[str, dict[int, str]]] = {}

    jsonl_files = [
        p for p in sorted(p_dir.glob("*.jsonl"))
        if not p.name.startswith("_")
    ]
    if not jsonl_files:
        print(f"JSONL ファイルが見つかりません: {p_dir}", file=sys.stderr)
        return result

    print(f"{target_class} JSONL ファイル数: {len(jsonl_files)}")
    for jsonl_path in jsonl_files:
        year = jsonl_path.stem
        type_map: dict[str, dict[int, str]] = {t: {} for t in IMAGE_TYPES}

        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                for role in ("source", "target"):
                    pid = patent_id_int(row[role])
                    if pid is None:
                        continue
                    for img_type, fpath in row.get(f"{role}_images", {}).items():
                        if img_type in type_map and pid not in type_map[img_type]:
                            type_map[img_type][pid] = fpath

        result[year] = type_map
        counts = {t: len(m) for t, m in type_map.items() if m}
        print(f"  {year}: {counts}")

    return result


# ---------------------------------------------------------------------------
# 前処理・埋め込み
# ---------------------------------------------------------------------------
def preprocess(path: str):
    from PIL import Image
    with Image.open(path) as img:
        return ImageProcessor.process(img.copy()).convert("RGB")


def embed_batch(paths: list[str], processor, model, device: str) -> np.ndarray:
    images = [preprocess(p) for p in paths]
    texts = [
        processor.apply_chat_template(
            [{"role": "user", "content": [
                {"type": "image"},
                {"type": "text", "text": FIXED_TEXT},
            ]}],
            tokenize=False,
            add_generation_prompt=False,
        )
        for _ in paths
    ]
    inputs = processor(
        text=texts, images=images,
        return_tensors="pt", padding=True, max_pixels=MAX_PIXELS,
    ).to(device)
    with torch.no_grad():
        outputs = model(**inputs)

    if hasattr(outputs, "image_embeds") and outputs.image_embeds is not None:
        vecs = outputs.image_embeds
    elif hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
        vecs = outputs.pooler_output
    else:
        vecs = outputs.last_hidden_state.mean(dim=1)
    return vecs.cpu().float().numpy()


# ---------------------------------------------------------------------------
# チェックポイント
# ---------------------------------------------------------------------------
def _ckpt_path(o_dir: Path, year: str) -> Path:
    return o_dir / f"_checkpoint_{year}.pkl"


def _save_checkpoint(path: Path, ids: list[int], vecs: list[np.ndarray], fpaths: list[str]) -> None:
    vecs_arr = np.concatenate(vecs, axis=0) if vecs else np.empty((0, 0), dtype=np.float32)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({"ids": ids, "vecs": vecs_arr, "paths": fpaths}, f,
                    protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def _load_checkpoint(path: Path) -> tuple[list[int], list[np.ndarray], list[str]]:
    with open(path, "rb") as f:
        data = pickle.load(f)
    ids   = list(data["ids"])
    vecs  = [data["vecs"]] if len(data["ids"]) > 0 else []
    fpaths = list(data["paths"])
    return ids, vecs, fpaths


# ---------------------------------------------------------------------------
# 年×タイプ単位の処理
# ---------------------------------------------------------------------------
def process_year_type(
    year: str, img_type: str,
    id_to_path: dict[int, str],
    target_class: str,
    existing_idx: ExistingVectorIndex,
    processor, model, device: str, resume: bool,
) -> None:
    o_dir   = out_dir(target_class) / img_type
    out_ids = o_dir / f"patent_ids_{year}.npy"
    out_vec = o_dir / f"vectors_{year}.npy"
    out_txt = o_dir / f"file_paths_{year}.txt"
    ckpt    = _ckpt_path(o_dir, year)

    if out_ids.exists() and out_vec.exists():
        existing = np.load(out_ids)
        tqdm.write(f"[{year}/{img_type}] スキップ（処理済み {len(existing):,} 件）")
        return

    result_ids:   list[int]        = []
    result_vecs:  list[np.ndarray] = []
    result_paths: list[str]        = []
    done_ids:     set[int]         = set()

    if resume and ckpt.exists():
        result_ids, result_vecs, result_paths = _load_checkpoint(ckpt)
        done_ids = set(result_ids)
        tqdm.write(f"[{year}/{img_type}] チェックポイントから再開: {len(done_ids):,} 件処理済み")

    items   = sorted(id_to_path.items())
    pending = [(pid, fp) for pid, fp in items if pid not in done_ids]
    n_total = len(items)
    n_done  = len(done_ids)

    n_cached  = sum(1 for pid, _ in pending if existing_idx.get(pid, img_type) is not None)
    n_new_gen = len(pending) - n_cached
    tqdm.write(
        f"[{year}/{img_type}] 合計: {n_total}  "
        f"既存コピー: {n_cached}  新規生成: {n_new_gen}"
    )

    batch_pids:  list[int] = []
    batch_paths: list[str] = []

    o_dir.mkdir(parents=True, exist_ok=True)

    def flush_batch(pbar: tqdm) -> None:
        if not batch_paths:
            return
        n = len(batch_paths)
        try:
            vecs = embed_batch(batch_paths, processor, model, device)
            result_ids.extend(batch_pids)
            result_vecs.append(vecs)
            result_paths.extend(batch_paths)
        except Exception as e:
            import traceback
            tqdm.write(f"  [BATCH ERROR] 1枚ずつ再試行: {e}")
            tqdm.write(traceback.format_exc())
            for pid, path in zip(batch_pids, batch_paths):
                try:
                    vec = embed_batch([path], processor, model, device)
                    result_ids.append(pid)
                    result_vecs.append(vec)
                    result_paths.append(path)
                except Exception as e2:
                    tqdm.write(f"  [SKIP] {Path(path).name}: {e2}")
        batch_pids.clear()
        batch_paths.clear()
        pbar.update(n)
        if resume:
            _save_checkpoint(ckpt, result_ids, result_vecs, result_paths)

    with tqdm(
        total=n_total, initial=n_done,
        desc=f"{year}/{img_type}", unit="件",
        leave=True, dynamic_ncols=True,
    ) as pbar:
        for pid, fpath in pending:
            existing_vec = existing_idx.get(pid, img_type)
            if existing_vec is not None:
                flush_batch(pbar)
                result_ids.append(pid)
                result_vecs.append(existing_vec[np.newaxis])
                result_paths.append(fpath)
                pbar.update(1)
                if resume:
                    _save_checkpoint(ckpt, result_ids, result_vecs, result_paths)
                continue

            if not Path(fpath).exists():
                tqdm.write(f"  [NOT FOUND] {fpath}")
                pbar.update(1)
                continue

            if model is None:
                tqdm.write(f"  [SKIP] 既存ベクトルなし・モデル未ロード: {Path(fpath).name}")
                pbar.update(1)
                continue

            batch_pids.append(pid)
            batch_paths.append(fpath)
            if len(batch_paths) >= BATCH_SIZE:
                flush_batch(pbar)

        flush_batch(pbar)

    if not result_ids:
        tqdm.write(f"[{year}/{img_type}] ベクトルなし")
        return

    pat_ids = np.array(result_ids, dtype=np.int64)
    vecs    = np.concatenate(result_vecs, axis=0).astype(np.float32)
    np.save(out_ids, pat_ids)
    np.save(out_vec, vecs)
    out_txt.write_text("\n".join(result_paths), encoding="utf-8")

    if ckpt.exists():
        ckpt.unlink()

    tqdm.write(
        f"[{year}/{img_type}] 完了: {len(pat_ids):,}/{n_total:,} 件"
        f" → {out_vec.name} shape={vecs.shape}"
    )


# ---------------------------------------------------------------------------
# モデルロード要否の判定
# ---------------------------------------------------------------------------
def _count_new_gen_needed(
    all_tasks: list[tuple[str, str, dict[int, str]]],
    target_class: str,
    existing_idx: ExistingVectorIndex,
) -> int:
    count = 0
    for year, img_type, id_to_path in all_tasks:
        if (out_dir(target_class) / img_type / f"vectors_{year}.npy").exists():
            continue
        for pid in id_to_path:
            if existing_idx.get(pid, img_type) is None:
                count += 1
    return count


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main(
    target_class: str = "D18",
    years: list[str] | None = None,
    resume: bool = True,
    no_gpu: bool = False,
) -> None:
    print(f"対象クラス: {target_class}")
    print("ペア情報を収集中...")
    year_data = load_pairs(target_class)

    if years:
        missing = set(years) - set(year_data)
        if missing:
            print(f"JSONL が見つからない年: {sorted(missing)}", file=sys.stderr)
        year_data = {y: year_data[y] for y in years if y in year_data}

    if not year_data:
        print("処理対象なし。終了します。")
        return

    all_tasks = [
        (y, t, td[t])
        for y, td in year_data.items()
        for t in IMAGE_TYPES
        if td.get(t)
    ]
    if not all_tasks:
        print("処理対象なし。終了します。")
        return

    n_done_already = sum(
        1 for y, t, _ in all_tasks
        if (out_dir(target_class) / t / f"vectors_{y}.npy").exists()
    )
    print(
        f"\nタスク合計: {len(all_tasks)} 件（年×タイプ）  "
        f"完了済み: {n_done_already}  未処理: {len(all_tasks) - n_done_already}"
    )
    print(f"再開モード: {'有効' if resume else '無効（--no-resume）'}")

    if n_done_already == len(all_tasks):
        print("全て処理済み。終了します。")
        return

    print()
    existing_idx = ExistingVectorIndex(EXISTING_VEC_DIR)

    n_new_gen = _count_new_gen_needed(all_tasks, target_class, existing_idx)
    print(f"\n新規生成が必要な特許数: {n_new_gen:,}")

    if no_gpu:
        device = "cpu"
        print("CPU モードで動作（--no-gpu）")
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"デバイス: {device}")
        if device == "cuda":
            print(f"GPU: {torch.cuda.get_device_name(0)}")

    processor = model = None
    if n_new_gen > 0 and not no_gpu:
        print(f"モデルをロード中: {MODEL_ID}")
        from transformers import AutoProcessor, AutoModel
        processor = AutoProcessor.from_pretrained(MODEL_ID, trust_remote_code=True)
        model = AutoModel.from_pretrained(
            MODEL_ID,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
            trust_remote_code=True,
        ).to(device).eval()
    elif n_new_gen > 0 and no_gpu:
        print(f"  警告: --no-gpu モードでは {n_new_gen:,} 件の新規生成をスキップします。")
    else:
        print("全ての対象ベクトルが既存データから取得可能。モデルロードをスキップ。")

    with tqdm(
        total=len(all_tasks), initial=n_done_already,
        desc="全体進捗", unit="タスク",
        position=0, leave=True, dynamic_ncols=True,
    ) as pbar_outer:
        for year, img_type, id_to_path in all_tasks:
            if (out_dir(target_class) / img_type / f"vectors_{year}.npy").exists():
                continue
            process_year_type(
                year, img_type, id_to_path,
                target_class, existing_idx,
                processor, model, device, resume=resume,
            )
            pbar_outer.update(1)

    print("\n完了")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="指定クラスの引用ペア画像ベクトルを生成・保存する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使い方:
  python build_class_vectors.py                        # D18、全年（再開モード有効）
  python build_class_vectors.py --class D5             # D5 クラス
  python build_class_vectors.py 2007 2008 --class D18  # D18 の指定年のみ
  python build_class_vectors.py --no-gpu               # GPU なしで動作確認
  python build_class_vectors.py --no-resume            # 最初から処理し直す
        """,
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年（省略時は全年）",
    )
    parser.add_argument(
        "--class", dest="target_class", default="D18",
        metavar="CLASS",
        help="対象クラスコード（デフォルト: D18）",
    )
    parser.add_argument(
        "--no-resume", action="store_true",
        help="チェックポイントを無視して最初から処理し直す",
    )
    parser.add_argument(
        "--no-gpu", action="store_true",
        help="GPU を使わない（既存ベクトルのコピーのみ実行）",
    )
    args = parser.parse_args()
    main(
        target_class=args.target_class,
        years=args.years or None,
        resume=not args.no_resume,
        no_gpu=args.no_gpu,
    )
