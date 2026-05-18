#!/usr/bin/env python3
"""
ランク検索結果の統計分析・可視化。

出力:
  vector/output/{CLASS}/{sim_func}/
    rank_ccdf_{type}.png     — 順位の CCDF（Yes/No 別）
    rank_scatter_{type}.png  — 順位 vs 類似度の散布図（Yes/No 別マーカー）
    pair_comparison/
      {src}--{tgt}_{type}_top10.png  — ベースペア + Top-10 近傍の画像グリッド

実行:
    python vector/analysis/rank_analysis.py --class D18
    python vector/analysis/rank_analysis.py --class D18 --sim cosine_numpy --type perspective
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as ticker
import numpy as np
from PIL import Image

# ImageProcessor は project root に存在
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_processor import ImageProcessor

# ---------------------------------------------------------------------------
# パス定数
# ---------------------------------------------------------------------------
CLASS_BASE    = Path("/mnt/eightthdd/uspto/class")
QWEN_DIR      = Path("/mnt/eightthdd/uspto/qwen_similarity_results")
OUT_BASE      = Path(__file__).resolve().parents[1] / "output"
DESIGN_OFFSET = 10_000_000_000

# ---------------------------------------------------------------------------
# Matplotlib スタイル（PRL シングルカラム準拠）
# ---------------------------------------------------------------------------
COLUMN_W = 3.37   # PRL single column width [inch]

def _set_style() -> None:
    plt.rcParams.update({
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
# ユーティリティ
# ---------------------------------------------------------------------------
def patent_id_to_int(s: str) -> int:
    return DESIGN_OFFSET + int(s.lstrip("D").lstrip("0") or "0")

def int_to_patent_id(n: int) -> str:
    return f"D{(n - DESIGN_OFFSET):07d}"

# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------
def load_rank_records(target_class: str, sim_func: str, img_type: str) -> list[dict]:
    base = CLASS_BASE / target_class / "rank_results" / sim_func
    records = []
    for f in sorted(base.glob("[0-9]*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r["type"] == img_type:
                    records.append(r)
    return records


def load_qwen_lookup() -> dict[tuple[str, str], dict]:
    """全年の qwen 判定結果を (source, target) → dict で返す。"""
    lookup: dict[tuple[str, str], dict] = {}
    for f in sorted(QWEN_DIR.glob("[0-9]*.jsonl")):
        for line in f.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                lookup[(r["source"], r["target"])] = r
    return lookup


def join_judgment(records: list[dict], qwen: dict[tuple[str, str], dict]) -> list[dict]:
    """rank records に LLM 判定・画像パスを追加する。"""
    for r in records:
        q = qwen.get((r["source"], r["target"]))
        r["judgment"]   = q["similarity"] if q else "Unknown"
        r["confidence"] = q.get("confidence", 0) if q else 0
        if q:
            si = q.get("source_images", {})
            ti = q.get("target_images", {})
            r["source_image"] = list(si.values())[0] if si else None
            r["target_image"] = list(ti.values())[0] if ti else None
        else:
            r["source_image"] = None
            r["target_image"] = None
    return records

# ---------------------------------------------------------------------------
# Figure 1: CCDF of rank
# ---------------------------------------------------------------------------
def plot_ccdf(records: list[dict], out_path: Path) -> None:
    """
    x 軸: 順位 r、y 軸: P(rank >= r)。
    Yes / No グループ別および全体のランダム期待値を重ねて描画する。
    """
    fig, ax = plt.subplots(figsize=(COLUMN_W, 2.8))

    n_cand = records[0]["n_candidates"]

    groups = {
        "Yes": [r for r in records if r["judgment"] == "Yes"],
        "No":  [r for r in records if r["judgment"] == "No"],
    }
    style = {
        "Yes": dict(color="#1f77b4", lw=1.4, zorder=3,
                    label=f"Similar (Yes, $n={len(groups['Yes'])}$)"),
        "No":  dict(color="#d62728", lw=1.0, ls="--", zorder=2,
                    label=f"Non-similar (No, $n={len(groups['No'])}$)"),
    }

    for label, recs in groups.items():
        if not recs:
            continue
        ranks  = np.sort([r["rank"] for r in recs])
        n      = len(ranks)
        ccdf_y = np.arange(n, 0, -1) / n
        kw = style[label]
        ax.plot(ranks, ccdf_y, **kw)

    # ランダム期待値（一様分布）
    r_rand = np.array([1, n_cand])
    ax.plot(r_rand, 1 - (r_rand - 1) / n_cand,
            color="gray", lw=0.8, ls=":", zorder=1, label="Random baseline")

    ax.set_xlabel("Rank $r$")
    ax.set_ylabel(r"$P(\mathrm{rank} \geq r)$")
    ax.set_xlim(0, n_cand + 5)
    ax.set_ylim(0, 1.05)
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.legend(fontsize=7.5, framealpha=0.85, edgecolor="gray", loc="upper right")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  → {out_path}")

# ---------------------------------------------------------------------------
# Figure 2: Scatter (rank vs cosine similarity)
# ---------------------------------------------------------------------------
def plot_scatter(records: list[dict], selected: dict, out_path: Path) -> None:
    """
    x 軸: 順位、y 軸: コサイン類似度。
    Yes / No / Unknown を異なるマーカーで描画し、
    選択代表ペアを強調表示する。
    """
    fig, ax = plt.subplots(figsize=(COLUMN_W, 2.8))

    n_cand = records[0]["n_candidates"]

    # プロット順：No を下に、Yes を上に重ねる
    layers = [
        ("Unknown", "#aaaaaa", "^",  8, 0.4),
        ("No",      "#d62728", "x", 18, 0.5),
        ("Yes",     "#1f77b4", "o", 12, 0.7),
    ]
    for label, color, marker, size, alpha in layers:
        recs = [r for r in records if r["judgment"] == label]
        if not recs:
            continue
        x = [r["rank"] for r in recs]
        y = [r["similarity"] for r in recs]
        kw = dict(marker=marker, s=size, alpha=alpha, linewidths=0.8,
                  label=f"{label} ($n={len(recs)}$)",
                  zorder={"Unknown": 1, "No": 2, "Yes": 3}[label])
        if marker == "x":
            ax.scatter(x, y, c=color, **kw)
        elif marker == "o":
            ax.scatter(x, y, facecolors=color, edgecolors=color, **kw)
        else:
            ax.scatter(x, y, facecolors="none", edgecolors=color, **kw)

    # 代表ペアを強調
    ax.scatter([selected["rank"]], [selected["similarity"]],
               marker="*", s=120, facecolors="none",
               edgecolors="#2ca02c", linewidths=1.5, zorder=5,
               label=(f"Selected pair "
                      f"($r={selected['rank']}$, "
                      f"$r_{{\\rm s}}={selected['similarity']:.3f}$)"))

    ax.set_xlabel("Rank $r$")
    ax.set_ylabel("Cosine similarity")
    ax.set_xlim(-5, n_cand + 10)
    ax.set_ylim(0.38, 1.02)
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.legend(fontsize=6.5, framealpha=0.85, edgecolor="gray", loc="lower left")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  → {out_path}")

# ---------------------------------------------------------------------------
# 画像ロード
# ---------------------------------------------------------------------------
def load_image(path: str | None) -> np.ndarray | None:
    """ImageProcessor で前処理した特許図面を RGB numpy array で返す。"""
    if path is None:
        return None
    try:
        img = ImageProcessor.process_file(path).convert("RGB")
        return np.array(img)
    except Exception as e:
        print(f"  [warn] 画像ロード失敗: {path}: {e}", file=sys.stderr)
        return None

# ---------------------------------------------------------------------------
# Figure 3: ペア比較画像グリッド
# ---------------------------------------------------------------------------
def plot_pair_comparison(
    rec: dict,
    top10: list[dict],
    out_path: Path,
) -> None:
    """
    レイアウト（3行 × 5列）:
      Row 0 : [Query A (2列)] [Cited B (2列)] [情報テキスト (1列)]
      Row 1 : Top-1 〜 Top-5 近傍（各1列）
      Row 2 : Top-6 〜 Top-10 近傍（各1列）
    """
    N_COLS  = 5
    CELL_W  = 1.55   # [inch]
    CELL_H  = 2.00   # [inch]
    fig_w   = CELL_W * N_COLS
    fig_h   = CELL_H * 3

    fig = plt.figure(figsize=(fig_w, fig_h))
    gs  = gridspec.GridSpec(
        3, N_COLS,
        figure=fig,
        hspace=0.45, wspace=0.08,
        top=0.91, bottom=0.02, left=0.01, right=0.99,
    )

    def _panel(ax, img_path, title, caption, border=None):
        arr = load_image(img_path)
        ax.set_xticks([]); ax.set_yticks([])
        if arr is not None:
            ax.imshow(arr, aspect="equal", interpolation="lanczos")
        else:
            ax.set_facecolor("#e8e8e8")
            ax.text(0.5, 0.5, "N/A", ha="center", va="center",
                    transform=ax.transAxes, fontsize=8)
        ax.set_title(title, fontsize=7.0, pad=2, fontweight="bold",
                     wrap=True)
        ax.set_xlabel(caption, fontsize=6.0, labelpad=3)
        if border:
            for sp in ax.spines.values():
                sp.set_edgecolor(border); sp.set_linewidth(2.5)
        else:
            for sp in ax.spines.values():
                sp.set_linewidth(0.5)

    # ── Row 0: Query A ───────────────────────────────────────────
    ax_a = fig.add_subplot(gs[0, :2])
    _panel(ax_a,
           rec["source_image"],
           f"Query: {rec['source']}",
           "")

    # ── Row 0: Cited target B (baseline / expected) ──────────────
    j_color = "#1f77b4" if rec["judgment"] == "Yes" else "#d62728"
    ax_b = fig.add_subplot(gs[0, 2:4])
    _panel(ax_b,
           rec["target_image"],
           f"Expected (cited): {rec['target']}",
           (f"rank={rec['rank']}/{rec['n_candidates']}"
            f"   $r_{{\\rm s}}$={rec['similarity']:.4f}\n"
            f"LLM: {rec['judgment']} (conf={rec['confidence']})"),
           border=j_color)

    # ── Row 0: 情報テキスト ──────────────────────────────────────
    ax_info = fig.add_subplot(gs[0, 4])
    ax_info.axis("off")
    info = (
        f"Class : D18\n"
        f"Type  : perspective\n"
        f"N     : {rec['n_candidates'] + 1}\n"
        f"Cited rank : {rec['rank']}\n"
        f"Similarity : {rec['similarity']:.4f}\n"
        f"LLM   : {rec['judgment']}\n"
        f"Conf  : {rec['confidence']}"
    )
    ax_info.text(0.08, 0.95, info, va="top", ha="left",
                 transform=ax_info.transAxes,
                 fontsize=6.5, family="monospace",
                 bbox=dict(boxstyle="round,pad=0.4",
                           fc="white", ec="#aaa", alpha=0.9))

    # ── Rows 1–2: Top-10 近傍 ───────────────────────────────────
    for i, nb in enumerate(top10[:10]):
        row = 1 + i // N_COLS
        col = i % N_COLS
        ax_n = fig.add_subplot(gs[row, col])

        pid_str  = int_to_patent_id(nb["patent_id_int"])
        is_cited = (pid_str == rec["target"])
        border   = "#ff7f0e" if is_cited else None
        caption  = f"$r_{{\\rm s}}$={nb['similarity']:.4f}"
        if is_cited:
            caption += "\n[cited target]"

        _panel(ax_n,
               nb["file_path"],
               f"#{nb['rank']}  {pid_str}",
               caption,
               border=border)

    n_cand = rec["n_candidates"]
    fig.suptitle(
        (f"Nearest-neighbor retrieval: query {rec['source']}"
         f"  (D18 / perspective, $N={n_cand + 1}$)"),
        fontsize=8.5, y=0.995,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200)
    plt.close(fig)
    print(f"  → {out_path}")

# ---------------------------------------------------------------------------
# Top-k 近傍検索
# ---------------------------------------------------------------------------
def get_topk(
    patent_id_str: str,
    img_type: str,
    target_class: str,
    k: int = 10,
) -> list[dict]:
    idx_dir = CLASS_BASE / target_class / "rank_index" / img_type
    ids     = np.load(idx_dir / "patent_ids.npy")
    vecs    = np.load(idx_dir / "vectors_l2norm.npy")
    fps     = (idx_dir / "file_paths.txt").read_text().splitlines()
    id2row  = {int(pid): i for i, pid in enumerate(ids)}

    src_int = patent_id_to_int(patent_id_str)
    src_row = id2row.get(src_int)
    if src_row is None:
        return []

    sims = vecs @ vecs[src_row]
    sims[src_row] = -2.0
    top_idx = np.argsort(sims)[::-1][:k]

    return [
        {
            "patent_id_int": int(ids[i]),
            "file_path":     fps[i],
            "rank":          rank + 1,
            "similarity":    float(sims[i]),
        }
        for rank, i in enumerate(top_idx)
    ]

# ---------------------------------------------------------------------------
# 代表ペアの選択
# ---------------------------------------------------------------------------
def select_representative(records: list[dict]) -> dict:
    """Yes 判定かつ信頼度 5 のペアの中からランク中央値に最も近いものを選ぶ。"""
    yes5 = [r for r in records if r["judgment"] == "Yes" and r["confidence"] == 5]
    pool = yes5 if yes5 else [r for r in records if r["judgment"] == "Yes"]
    if not pool:
        pool = records
    med = np.median([r["rank"] for r in pool])
    return min(pool, key=lambda r: abs(r["rank"] - med))

# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="ランク検索結果の統計分析・可視化"
    )
    parser.add_argument("--class", dest="target_class", default="D18", metavar="CLASS")
    parser.add_argument("--sim",   default="cosine_numpy",
                        choices=["cosine_numpy", "cosine_faiss"])
    parser.add_argument("--type",  dest="img_type", default="perspective",
                        choices=["perspective", "front", "overview"])
    parser.add_argument("--top-k", type=int, default=10,
                        help="ペア比較図の近傍数（デフォルト: 10）")
    args = parser.parse_args()

    _set_style()

    out_dir = OUT_BASE / args.target_class / args.sim
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── データ読み込み ──────────────────────────────────────────
    print("Loading rank records...")
    records = load_rank_records(args.target_class, args.sim, args.img_type)
    print(f"  {len(records)} records ({args.img_type})")

    print("Loading LLM judgments...")
    qwen    = load_qwen_lookup()
    records = join_judgment(records, qwen)

    from collections import Counter
    cnt = Counter(r["judgment"] for r in records)
    print(f"  Yes={cnt['Yes']}  No={cnt['No']}  Unknown={cnt.get('Unknown',0)}")

    rep = select_representative(records)
    print(f"  Representative: {rep['source']} → {rep['target']}"
          f"  rank={rep['rank']}  sim={rep['similarity']:.4f}"
          f"  {rep['judgment']} (conf={rep['confidence']})")

    # ── Figure 1: CCDF ──────────────────────────────────────────
    print("\n[1/3] Plotting CCDF...")
    plot_ccdf(records, out_dir / f"rank_ccdf_{args.img_type}.png")

    # ── Figure 2: Scatter ───────────────────────────────────────
    print("[2/3] Plotting scatter...")
    plot_scatter(records, rep, out_dir / f"rank_scatter_{args.img_type}.png")

    # ── Figure 3: ペア比較画像 ──────────────────────────────────
    print("[3/3] Plotting pair comparison images...")
    top10 = get_topk(rep["source"], args.img_type, args.target_class, k=args.top_k)
    fname = f"{rep['source']}--{rep['target']}_{args.img_type}_top{args.top_k}.png"
    plot_pair_comparison(rep, top10,
                         out_dir / "pair_comparison" / fname)

    print(f"\n完了  出力先: {out_dir}")


if __name__ == "__main__":
    main()
