#!/usr/bin/env python3
"""
USPTO 意匠特許共引用グラフの EstimNetDirected 用入力ファイルを生成する。

意匠分類（D1–D99）をノード属性として扱い、クラス間の Homophily・
Sender/Receiver 効果を ERGM で推定するための入力ファイル群を出力する。

処理フェーズ:
  Phase 1 — ノード属性抽出（D-class フラグ・多様性スコア・日付）
  Phase 2 — クラス類似度行列の計算（同一クラス / Jaccard 係数）
  Phase 3 — EstimNetDirected 用ファイルエクスポート
  Phase 4 — モデル設定ファイル (.cfg) の生成

入力:
  /mnt/eightthdd/uspto/edge_list/<year>.csv   共引用エッジリスト
  /mnt/eightthdd/uspto/data/<year>.csv        特許属性 CSV (id, class, date)

出力 (--out-dir で指定、デフォルト: ergm_input/):
  arc_list.txt              エッジリスト（無向エッジを双方向アークとして出力）
  attributes.txt            ノード属性（タブ区切り、EstimNetDirected 形式）
  class_sim_binary.npy      クラス一致バイナリ行列（dense bool）
  class_sim_jaccard.npy     全クラス Jaccard 類似度行列（dense float32）
  model.cfg                 EstimNetDirected 設定ファイルのひな型
  _patent_attr_cache.pkl    特許属性キャッシュ
"""

import argparse
import csv
import pickle
import re
import sys
from pathlib import Path

import numpy as np
import numpy.lib.format as _npy_fmt
import psutil
from tqdm import tqdm
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, NullFormatter

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
EDGE_DIR = Path("/mnt/eightthdd/uspto/edge_list")
DATA_DIR = Path("/mnt/eightthdd/uspto/data")
DEFAULT_OUT_DIR = Path("ergm_input")

# D-class 全リスト（D1–D34, D99）
ALL_CLASSES: list[str] = [f"D{i}" for i in range(1, 35)] + ["D99"]

CLASS_NAMES: dict[str, str] = {
    "D1":  "Edible Products",
    "D2":  "Apparel & Haberdashery",
    "D3":  "Travel Goods & Personal Items",
    "D4":  "Brushware",
    "D5":  "Textile/Fabric Articles",
    "D6":  "Furnishings",
    "D7":  "Equipment for Preparing Food",
    "D8":  "Tools & Hardware",
    "D9":  "Tools & Hardware (misc)",
    "D10": "Measuring/Testing Devices",
    "D11": "Jewelry/Symbolic Insignia",
    "D12": "Transportation",
    "D13": "Equipment for Production/Distribution",
    "D14": "Recording/Communication/Info",
    "D15": "Machines",
    "D16": "Photography & Optics",
    "D17": "Musical Instruments",
    "D18": "Printing & Office Machinery",
    "D19": "Office Supplies/Equipment",
    "D20": "Sales/Advertising/Signs",
    "D21": "Amusement Devices",
    "D22": "Arms/Pyrotechnics/etc.",
    "D23": "Environmental Heating/Cooling",
    "D24": "Medical/Lab Equipment",
    "D25": "Building Units & Construction",
    "D26": "Lighting",
    "D27": "Tobacco & Smoking",
    "D28": "Pharmaceuticals & Cosmetics",
    "D29": "Animal Husbandry",
    "D30": "Outdoor/Garden",
    "D31": "Articles of Manufacture",
    "D32": "Washing/Cleaning Equipment",
    "D33": "Food/Beverage Service",
    "D34": "Material/Article Handling",
    "D99": "Miscellaneous",
}


# ---------------------------------------------------------------------------
# メモリ監視
# ---------------------------------------------------------------------------
def _mem_str() -> str:
    m = psutil.virtual_memory()
    return f"{m.percent:.1f}%  ({m.used/1e9:.1f}/{m.total/1e9:.1f} GB)"


def _check_memory(threshold: float, where: str = "") -> None:
    """使用率が threshold を超えていれば MemoryError を送出する。"""
    pct = psutil.virtual_memory().percent / 100
    if pct > threshold:
        loc = f" [{where}]" if where else ""
        raise MemoryError(
            f"メモリ使用率 {pct*100:.1f}% が上限 {threshold*100:.0f}%{loc} を超えました\n"
            f"  現在: {_mem_str()}\n"
            f"  --no-sim で類似度行列をスキップするか --mem-limit を調整してください。"
        )


def _save_npy_chunked(path: Path, mm: np.memmap, chunk_rows: int,
                      desc: str = ".npy 書き出し") -> None:
    """memmap 配列を chunk_rows 行ずつ .npy 形式でディスクに書き出す。

    np.save(mm) は tobytes() で全体を RAM にコピーするため使わない。
    代わりにヘッダーを先頭に書いてから chunk 単位で raw bytes を追記する。
    chunk あたりの RAM 使用量: chunk_rows × N × itemsize バイト。
    """
    N       = mm.shape[0]
    n_chunks = (N + chunk_rows - 1) // chunk_rows
    with open(path, "wb") as fp:
        _npy_fmt.write_array_header_1_0(fp, {
            "descr":         mm.dtype.str,
            "fortran_order": False,
            "shape":         mm.shape,
        })
        for start in tqdm(range(0, N, chunk_rows), desc=desc,
                          unit="chunk", total=n_chunks):
            fp.write(mm[start : min(start + chunk_rows, N)].tobytes())


# ---------------------------------------------------------------------------
# Matplotlib スタイル（PRL シングルカラム準拠、plot_indegree.py と共通）
# ---------------------------------------------------------------------------
def _set_style(usetex: bool) -> None:
    plt.rcParams.update({
        "text.usetex":         usetex,
        "font.family":         "serif",
        "font.serif":          ["Times New Roman", "DejaVu Serif", "Palatino"],
        "mathtext.fontset":    "stix",
        "font.size":           9,
        "axes.labelsize":      10,
        "axes.titlesize":      9,
        "xtick.labelsize":     8,
        "ytick.labelsize":     8,
        "xtick.direction":     "in",
        "ytick.direction":     "in",
        "xtick.top":           True,
        "ytick.right":         True,
        "xtick.major.size":    4.0,
        "ytick.major.size":    4.0,
        "xtick.minor.size":    2.5,
        "ytick.minor.size":    2.5,
        "xtick.major.width":   0.7,
        "ytick.major.width":   0.7,
        "xtick.minor.visible": True,
        "ytick.minor.visible": True,
        "axes.linewidth":      0.7,
        "lines.linewidth":     1.0,
        "figure.dpi":          300,
        "savefig.dpi":         300,
        "savefig.bbox":        "tight",
        "pdf.fonttype":        42,
        "ps.fonttype":         42,
    })


# ---------------------------------------------------------------------------
# CSV ファイル列挙（plot_indegree.py と共通）
# ---------------------------------------------------------------------------
def _csv_files(edge_dir: Path, years: list[str] | None) -> list[Path]:
    if years:
        return [edge_dir / f"{y}.csv" for y in years]
    return sorted(edge_dir.glob("*.csv"))


# ---------------------------------------------------------------------------
# Phase 1: ノード属性抽出
# ---------------------------------------------------------------------------
def _extract_all_classes(class_str: str) -> set[str]:
    """class フィールドから全 D-class コードを抽出する（複数クラス・カンマ区切り対応）。"""
    if not class_str or class_str.strip() == "":
        return set()
    result: set[str] = set()
    for part in class_str.split(","):
        part = part.strip()
        m = re.match(r"D (\d)", part)
        if m:
            result.add(f"D{m.group(1)}")
            continue
        m = re.match(r"D(\d+)", part)
        if not m:
            continue
        digits = m.group(1)
        if len(digits) >= 2:
            two = int(digits[:2])
            if (10 <= two <= 34) or two == 99:
                result.add(f"D{two}")
                continue
        one = int(digits[:1])
        if 1 <= one <= 9:
            result.add(f"D{one}")
    return result


def _extract_main_class(class_str: str) -> str | None:
    """最初のクラスのみを抽出する（add_class_to_edge_list.py と同一ロジック）。"""
    if not class_str or class_str.strip() == "":
        return None
    first = class_str.split(",")[0].strip()
    m = re.match(r"D (\d)", first)
    if m:
        return f"D{m.group(1)}"
    m = re.match(r"D(\d+)", first)
    if not m:
        return None
    digits = m.group(1)
    if len(digits) >= 2:
        two = int(digits[:2])
        if (10 <= two <= 34) or two == 99:
            return f"D{two}"
    one = int(digits[:1])
    if 1 <= one <= 9:
        return f"D{one}"
    return None


def build_patent_index(
    data_dir: Path,
    cache_path: Path,
    rebuild: bool = False,
) -> dict[str, dict]:
    """
    data/ 以下の全 CSV から特許属性インデックスを構築する。
    { patent_id: {"classes": set[str], "primary": str, "date": str} }
    初回構築後は pickle キャッシュを使用する。
    """
    if not rebuild and cache_path.exists():
        print(f"キャッシュからロード: {cache_path}", flush=True)
        with open(cache_path, "rb") as f:
            return pickle.load(f)

    print("特許インデックスを構築中...", flush=True)
    index: dict[str, dict] = {}

    csv_files = sorted(data_dir.glob("*.csv"))
    for csv_path in tqdm(csv_files, desc="特許インデックス構築", unit="file"):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("id", "").strip()
                if not pid:
                    continue
                index[pid] = {
                    "classes": _extract_all_classes(row.get("class", "")),
                    "primary": _extract_main_class(row.get("class", "")) or "Unknown",
                    "date":    row.get("date", "").strip(),
                }

    print(f"  {len(index):,} 件")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"  キャッシュ保存: {cache_path}")
    return index


def build_graph(
    edge_dir: Path,
    years: list[str] | None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """エッジ CSV を読み込み、ソート済みノードリストとエッジリストを返す。"""
    nodes: set[str] = set()
    edges: list[tuple[str, str]] = []

    for path in tqdm(_csv_files(edge_dir, years), desc="エッジCSV読み込み", unit="file"):
        if not path.exists():
            print(f"警告: {path} が見つかりません", file=sys.stderr)
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                src = row.get("source", "").strip()
                tgt = row.get("target", "").strip()
                if src and tgt:
                    nodes.add(src)
                    nodes.add(tgt)
                    edges.append((src, tgt))

    return sorted(nodes), edges


def build_node_attributes(
    node_list: list[str],
    patent_index: dict[str, dict],
) -> list[dict]:
    """各ノードの属性辞書を構築する（Phase 1）。"""
    records = []
    for node in tqdm(node_list, desc="ノード属性構築", unit="node"):
        info    = patent_index.get(node, {})
        classes = info.get("classes", set())
        record: dict = {
            "primary_class": info.get("primary", "Unknown"),
            "n_classes":     len(classes),
            "date":          info.get("date", ""),
        }
        for cls in ALL_CLASSES:
            record[f"IsClass_{cls}"] = 1 if cls in classes else 0
        records.append(record)
    return records


# ---------------------------------------------------------------------------
# Phase 2: クラス類似度行列（chunk × memmap 方式）
# ---------------------------------------------------------------------------
def compute_class_similarities(
    node_list: list[str],
    patent_index: dict[str, dict],
    out_dir: Path,
    binary_name: str,
    jaccard_name: str,
    chunk_rows: int = 500,
    mem_limit: float = 0.80,
) -> None:
    """
    D-class ビットベクトルの行列積でチャンクごとに Jaccard を計算し、
    np.memmap でディスクに書き出す（Phase 2）。

    RAM を N×N 行列に使わない設計:
      cls_vec  : (N, 35) uint8  ≈ 0.6 MB  ← 全体を RAM に保持
      chunk    : (chunk_rows, N) int16  ≈ chunk_rows×N×2 B  ← 1チャンク分のみ
      memmap   : N×N float32 / bool をディスク上に確保
    ピークメモリ: cls_vec + chunk × 3 ≈ chunk_rows × N × 6 B
                  chunk_rows=500, N=18900 → ~54 MB
    """
    N   = len(node_list)
    K   = len(ALL_CLASSES)
    cls_idx = {c: i for i, c in enumerate(ALL_CLASSES)}

    _check_memory(mem_limit, "Phase 2 開始前")

    # --- (N, K) uint8 クラスビットベクトルを構築 ---
    cls_vec = np.zeros((N, K), dtype=np.uint8)
    for i, node in enumerate(tqdm(node_list, desc="クラスベクトル構築", unit="node")):
        for cls in patent_index.get(node, {}).get("classes", set()):
            if cls in cls_idx:
                cls_vec[i, cls_idx[cls]] = 1

    cls_vec_i16 = cls_vec.astype(np.int16)          # 行列積用（overflow 防止）
    n_cls       = cls_vec.sum(axis=1).astype(np.int16)  # (N,) 各ノードのクラス数
    del cls_vec

    chunk_mb = chunk_rows * N * 6 / 1e6  # inter(int16) + union(int16) + jac(float32)
    print(
        f"  N={N:,}  K={K}  chunk_rows={chunk_rows}\n"
        f"  チャンクRAM ≈ {chunk_mb:.1f} MB  現在: {_mem_str()}",
        flush=True,
    )

    # --- memmap をディスク上に確保 ---
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_jac = out_dir / "_tmp_jaccard.mmap"
    tmp_bin = out_dir / "_tmp_binary.mmap"
    jac_mm  = np.memmap(tmp_jac, dtype=np.float32, mode="w+", shape=(N, N))
    bin_mm  = np.memmap(tmp_bin, dtype=np.bool_,   mode="w+", shape=(N, N))

    # --- チャンクごとに計算して memmap へ書き込む ---
    n_chunks = (N + chunk_rows - 1) // chunk_rows
    pbar = tqdm(range(0, N, chunk_rows), desc="類似度行列計算",
                unit="chunk", total=n_chunks)
    for start in pbar:
        end  = min(start + chunk_rows, N)
        rows = end - start

        _check_memory(mem_limit, f"chunk {start}-{end}")

        # inter[r, c] = クラス共有数: (rows, K) × (K, N) → (rows, N) int16
        inter = cls_vec_i16[start:end] @ cls_vec_i16.T

        # union = n_cls[i] + n_cls[j] - inter
        union = n_cls[start:end, np.newaxis] + n_cls[np.newaxis, :] - inter

        # Jaccard（0除算を無音で処理）
        with np.errstate(invalid="ignore", divide="ignore"):
            jac_chunk = np.where(
                union > 0,
                inter.astype(np.float32) / union.astype(np.float32),
                0.0,
            )

        bin_chunk = (inter > 0)

        # 対角を 0 にする（i==j は自己ペア）
        diag_col = np.arange(rows) + start          # 実際の列インデックス
        in_range = diag_col < N
        jac_chunk[np.arange(rows)[in_range], diag_col[in_range]] = 0.0
        bin_chunk[np.arange(rows)[in_range], diag_col[in_range]] = False

        jac_mm[start:end, :] = jac_chunk
        bin_mm[start:end, :] = bin_chunk

        pbar.set_postfix({"RAM": _mem_str()})

    # --- flush して memmap を閉じる ---
    jac_mm.flush(); bin_mm.flush()
    del jac_mm, bin_mm, jac_chunk, bin_chunk, inter, union

    # --- .npy へチャンク書き出し（np.save は tobytes で全体コピーするため不可）---
    print(f"  .npy 変換中... メモリ: {_mem_str()}", flush=True)
    jac_r = np.memmap(tmp_jac, dtype=np.float32, mode="r", shape=(N, N))
    bin_r = np.memmap(tmp_bin, dtype=np.bool_,   mode="r", shape=(N, N))
    _save_npy_chunked(out_dir / jaccard_name, jac_r, chunk_rows, desc="jaccard .npy 書き出し")
    _save_npy_chunked(out_dir / binary_name,  bin_r, chunk_rows, desc="binary  .npy 書き出し")
    del jac_r, bin_r

    tmp_jac.unlink()
    tmp_bin.unlink()

    print(
        f"  binary  → {out_dir / binary_name}\n"
        f"  jaccard → {out_dir / jaccard_name}\n"
        f"  完了  メモリ: {_mem_str()}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Phase 3: EstimNetDirected 用ファイルエクスポート
# ---------------------------------------------------------------------------
def export_arc_list(
    edges: list[tuple[str, str]],
    node_to_id: dict[str, int],
    out_path: Path,
) -> None:
    """無向エッジを双方向アークとして出力する（Phase 3）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n_arcs = 0
    with open(out_path, "w") as f:
        for src, tgt in tqdm(edges, desc="アークリスト出力", unit="edge"):
            si = node_to_id.get(src)
            ti = node_to_id.get(tgt)
            if si is not None and ti is not None:
                f.write(f"{si} {ti}\n")
                f.write(f"{ti} {si}\n")
                n_arcs += 2
    print(f"  エッジリスト: {out_path}  ({n_arcs:,} アーク)", flush=True)


def export_attributes(attrs: list[dict], out_path: Path) -> None:
    """ノード属性をタブ区切りで出力する（Phase 3）。"""
    if not attrs:
        return
    fieldnames = list(attrs[0].keys())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        for attr in tqdm(attrs, desc="属性ファイル出力", unit="node"):
            writer.writerow(attr)
    print(f"  ノード属性: {out_path}  ({len(attrs):,} ノード, {len(fieldnames)} 列)", flush=True)


# ---------------------------------------------------------------------------
# Phase 4: 設定ファイル生成
# ---------------------------------------------------------------------------
def export_cfg(
    out_path: Path,
    arc_file: str,
    attr_file: str,
    sim_jaccard_file: str,
    sim_binary_file: str,
) -> None:
    """EstimNetDirected 設定ファイルのひな型を生成する（Phase 4）。"""
    half    = len(ALL_CLASSES) // 2
    cls_lo  = " ".join(f"IsClass_{c}" for c in ALL_CLASSES[:half])
    cls_hi  = " ".join(f"IsClass_{c}" for c in ALL_CLASSES[half:])

    cfg = f"""; EstimNetDirected 設定ファイル（意匠分類ノード属性版）
; 生成元: build_ergm_input.py
;
; 意匠分類 D1–D99 をノード属性として扱い、
; クラス間 Homophily・Sender/Receiver 効果を推定する。
; 論文の IPC Subclass 相当 = 意匠分類 D-class (D1–D99)

ArcListFile       = {arc_file}
AttributesFile    = {attr_file}
PairAttributeFile = {sim_jaccard_file}

; === 構造統計量 ===
Param_AltInStar     = 1    ; GWIDegree（被共引用多様性）
Param_AltOutStar    = 1    ; GWODegree（共引用先多様性）
Param_AltKTriangleT = 2    ; GWESP 推移性
Param_AltTwoPathsTD = 1    ; GWDSP

; === D-class Sender/Receiver 効果（2 行に分割）===
; 「クラス X の特許は共引用されやすいか / 多く共引用するか」
ReceiverEffect = {cls_lo}
ReceiverEffect = {cls_hi}
SenderEffect   = {cls_lo}
SenderEffect   = {cls_hi}

; === D-class 多様性スコア（連続変量）===
ReceiverEffect = n_classes
SenderEffect   = n_classes

; === D-class Homophily ===
; バイナリ: 同一メインクラス間（論文の OverlappingCategorization 相当）
Homophily      = primary_class
; 連続値: 全クラス Jaccard 類似度（拡張版）
PairAttribute  = {sim_jaccard_file}
; または バイナリ行列を使う場合:
; PairAttribute  = {sim_binary_file}
"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(cfg)
    print(f"  設定ファイル: {out_path}", flush=True)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="USPTO意匠特許共引用グラフの EstimNetDirected 用入力ファイルを生成"
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年 (例: 2007 2008)。省略時は全 CSV"
    )
    parser.add_argument(
        "--edge-dir", default=str(EDGE_DIR),
        help=f"エッジリスト CSV のディレクトリ (default: %(default)s)"
    )
    parser.add_argument(
        "--data-dir", default=str(DATA_DIR),
        help=f"特許属性 CSV のディレクトリ (default: %(default)s)"
    )
    parser.add_argument(
        "--out-dir", default=str(DEFAULT_OUT_DIR),
        help=f"出力ディレクトリ (default: %(default)s)"
    )
    parser.add_argument(
        "--no-sim", action="store_true",
        help="類似度行列の計算をスキップ（ノード数が多い場合）"
    )
    parser.add_argument(
        "--rebuild", action="store_true",
        help="特許インデックスのキャッシュを再構築"
    )
    parser.add_argument(
        "--mem-limit", type=float, default=0.80,
        help="メモリ使用率の上限（0〜1、default: 0.80）。超えた場合は処理を停止する"
    )
    parser.add_argument(
        "--chunk-rows", type=int, default=500,
        help="Phase 2 の行列計算チャンクサイズ（default: 500）。"
             "小さいほど RAM 節約、大きいほど高速"
    )
    parser.add_argument(
        "--usetex", action="store_true",
        help="LaTeX でテキストレンダリング（要 texlive）"
    )
    args = parser.parse_args()

    years    = args.years or None
    edge_dir = Path(args.edge_dir)
    data_dir = Path(args.data_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / "_patent_attr_cache.pkl"

    _set_style(args.usetex)
    print(f"メモリ上限: {args.mem_limit*100:.0f}%  現在: {_mem_str()}", flush=True)

    # グラフ構築
    print("グラフを構築中...")
    node_list, edges = build_graph(edge_dir, years)
    node_to_id = {n: i for i, n in enumerate(node_list)}
    print(f"  ノード数: {len(node_list):,}  エッジ数: {len(edges):,}")

    # Phase 1: ノード属性抽出
    print("\nPhase 1: ノード属性を抽出中...")
    patent_index = build_patent_index(data_dir, cache_path, rebuild=args.rebuild)
    attrs   = build_node_attributes(node_list, patent_index)
    unknown = sum(1 for a in attrs if a["primary_class"] == "Unknown")
    print(f"  属性付与: {len(attrs):,} ノード  クラス不明: {unknown:,}")

    # Phase 2: 類似度行列（dense .npy で保存。ほぼ全ペアが非ゼロのため sparse より効率的）
    sim_jaccard_name = "class_sim_jaccard.npy"
    sim_binary_name  = "class_sim_binary.npy"
    if not args.no_sim:
        print("\nPhase 2: クラス類似度行列を計算中...")
        try:
            compute_class_similarities(
                node_list, patent_index,
                out_dir, sim_binary_name, sim_jaccard_name,
                chunk_rows=args.chunk_rows,
                mem_limit=args.mem_limit,
            )
        except MemoryError as e:
            print(f"\n[メモリ不足] {e}", file=sys.stderr)
            print("Phase 2 をスキップして続行します。", file=sys.stderr)
    else:
        print("\nPhase 2: スキップ (--no-sim)")

    # Phase 3: ファイルエクスポート
    print("\nPhase 3: EstimNetDirected 用ファイルをエクスポート中...")
    arc_path  = out_dir / "arc_list.txt"
    attr_path = out_dir / "attributes.txt"
    export_arc_list(edges, node_to_id, arc_path)
    export_attributes(attrs, attr_path)

    # Phase 4: 設定ファイル
    print("\nPhase 4: 設定ファイルを生成中...")
    cfg_path = out_dir / "model.cfg"
    export_cfg(cfg_path, arc_path.name, attr_path.name, sim_jaccard_name, sim_binary_name)

    print(f"\n完了  →  {out_dir}/")
    print(f"  ノード数: {len(node_list):,}")
    print(f"  エッジ数: {len(edges):,}  双方向アーク: {len(edges) * 2:,}")
    print(f"  メモリ: {_mem_str()}")


if __name__ == "__main__":
    # 使い方:
    #   python build_ergm_input.py                      # 全年処理
    #   python build_ergm_input.py 2007 2008             # 指定年のみ
    #   python build_ergm_input.py --no-sim              # 類似度行列をスキップ
    #   python build_ergm_input.py --rebuild             # キャッシュ再構築
    #   python build_ergm_input.py --mem-limit 0.70      # メモリ上限を 70% に設定
    #   python build_ergm_input.py --chunk-rows 200      # チャンクを小さく（RAM 節約）
    #   python build_ergm_input.py --chunk-rows 2000     # チャンクを大きく（高速化）
    #   python build_ergm_input.py --out-dir ./out       # 出力先指定
    main()
