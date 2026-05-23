#!/usr/bin/env python3
"""
ランク検索結果の統計分析・可視化。

事前に join_judgments.py を実行して rank_judgments/ を生成しておくこと。

出力:
  vector/output/{CLASS}/{sim_func}/
    rank_ccdf_{type}.png     — Figure 1: 順位の CCDF（log-log、Yes/No 別）
    rank_scatter_{type}.png  — Figure 2: 順位 vs 類似度の散布図（全件、Yes/No 別マーカー）

  /mnt/eightthdd/uspto/class/{CLASS}/rank_analysis/{sim_func}/{type}/pair_comparison/
    {src}--{tgt}_rank{r:03d}.png  — Figure 3: Rank ≤ topk の全 Yes ペア（各1枚）

実行:
    python vector/analysis/rank_analysis.py --class D18
    python vector/analysis/rank_analysis.py --class D18 --top-k 10
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as ticker
import numpy as np


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_processor import ImageProcessor

# ---------------------------------------------------------------------------
# パス定数
# ---------------------------------------------------------------------------
CLASS_BASE = Path("/mnt/eightthdd/uspto/class")
OUT_BASE   = Path(__file__).resolve().parents[1] / "output"   # vector/output/
COLUMN_W   = 3.37   # PRL single column [inch]
DESIGN_OFFSET = 10_000_000_000

FALLBACK_EXACT_KEYWORDS = ["identical", "exact", "same"]


def build_exact_pattern(exact_keywords: list[str]) -> re.Pattern:
    terms = "|".join(re.escape(k) for k in exact_keywords)
    return re.compile(rf"\b({terms})\b", re.IGNORECASE)


def classify_records(records: list[dict], exact_pattern: re.Pattern) -> list[dict]:
    """Yes レコードに _label フィールド（Yes_exact / Yes_nonexact）を付与して返す。"""
    for r in records:
        if r["judgment"] == "Yes":
            r["_label"] = (
                "Yes_exact"
                if exact_pattern.search(r.get("reason", ""))
                else "Yes_nonexact"
            )
        else:
            r["_label"] = r["judgment"]
    return records

# ---------------------------------------------------------------------------
# Matplotlib スタイル（統計図用、PRL シングルカラム準拠）
# ---------------------------------------------------------------------------
def _set_style_stats() -> None:
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
# Matplotlib スタイル（画像グリッド図用、大きいフォント）
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def int_to_patent_id(n: int) -> str:
    return f"D{(n - DESIGN_OFFSET):07d}"

def patent_id_to_int(s: str) -> int:
    return DESIGN_OFFSET + int(s.lstrip("D").lstrip("0") or "0")

# ---------------------------------------------------------------------------
# データ読み込み
# ---------------------------------------------------------------------------
def load_joined(target_class: str, sim_func: str, img_type: str) -> list[dict]:
    """rank_judgments/{sim_func}/all.jsonl から指定タイプのレコードを返す。"""
    fp = CLASS_BASE / target_class / "rank_judgments" / sim_func / "all.jsonl"
    if not fp.exists():
        raise FileNotFoundError(
            f"{fp} が見つかりません。先に join_judgments.py を実行してください。"
        )
    return [
        json.loads(line)
        for line in fp.read_text().splitlines()
        if line.strip() and json.loads(line).get("type") == img_type
    ]

# ---------------------------------------------------------------------------
# Figure 1: CCDF of rank（log-log）
# ---------------------------------------------------------------------------
def plot_ccdf(records: list[dict], img_type: str, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(COLUMN_W, 2.8))

    groups = {
        "Yes": [r for r in records if r["judgment"] == "Yes"],
        "No":  [r for r in records if r["judgment"] == "No"],
    }
    styles = {
        "Yes": dict(color="#1f77b4", lw=1.4, ls="-",  zorder=3,
                    label=f"Similar ($n={len(groups['Yes'])}$)"),
        "No":  dict(color="#d62728", lw=1.0, ls="--", zorder=2,
                    label=f"Non-similar ($n={len(groups['No'])}$)"),
    }

    for label, recs in groups.items():
        if not recs:
            continue
        ranks  = np.sort([r["rank"] for r in recs])
        n      = len(ranks)
        ccdf_y = np.arange(n, 0, -1) / n
        ax.plot(ranks, ccdf_y, **styles[label])

    ax.set_xscale("log")
    ax.set_yscale("log")
    n_cand = records[0]["n_candidates"]
    ax.set_xlim(0.8, n_cand * 1.5)
    ax.set_ylim(5e-3, 2.0)

    ax.set_xlabel("Rank")
    ax.set_ylabel(r"$P(\mathrm{rank} \geq r)$")

    ax.xaxis.set_major_formatter(ticker.ScalarFormatter())
    ax.yaxis.set_major_formatter(ticker.ScalarFormatter())
    ax.legend(fontsize=7.5, framealpha=0.85, edgecolor="gray", loc="lower left")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  -> {out_path}")

# ---------------------------------------------------------------------------
# CSV エクスポート: 高類似度レコード
# ---------------------------------------------------------------------------
def export_high_sim_csv(
    records: list[dict],
    out_path: Path,
    sim_threshold: float = 0.950,
    exclude_judgments: list[str] | None = None,
) -> None:
    filtered = [r for r in records if r.get("similarity", 0) >= sim_threshold]
    if exclude_judgments:
        filtered = [r for r in filtered if r.get("judgment") not in exclude_judgments]
    filtered.sort(key=lambda r: r["similarity"], reverse=True)

    fields = [
        "source", "target", "rank", "n_candidates", "similarity",
        "judgment", "confidence", "reason", "source_image", "target_image",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(filtered)
    excl = f", exclude={exclude_judgments}" if exclude_judgments else ""
    print(f"  {len(filtered)} 件 (similarity >= {sim_threshold}{excl}) -> {out_path}")

# ---------------------------------------------------------------------------
# Figure 2-density: 2D density map（物理学論文スタイル）
# ---------------------------------------------------------------------------
def plot_density_map(
    records: list[dict],
    img_type: str,
    out_path: Path,
    n_grid: int = 300,
    xlim: tuple[float, float] | None = None,
    ylim: tuple[float, float] | None = None,
    log_x: bool = False,
    log_color: bool = False,
) -> None:
    """
    Rank vs cosine similarity の2次元PDF（gaussian_kde）。
    contourf + contour lines で表示。PRL シングルカラム準拠。
    xlim/ylim を指定するとその範囲のデータのみで KDE を再推定してズーム表示。
    log_x=True で rank 軸を対数スケール、log_color=True でカラーを対数スケール。
    """
    from scipy.stats import gaussian_kde
    from matplotlib.colors import LogNorm

    fig, ax = plt.subplots(figsize=(COLUMN_W, 2.8))

    n_cand = records[0]["n_candidates"]

    all_ranks = np.array([r["rank"] for r in records], dtype=float)
    all_sims  = np.array([r["similarity"] for r in records], dtype=float)

    # zoom 指定があればその範囲のデータのみ使用
    if xlim is not None or ylim is not None:
        mask = np.ones(len(all_ranks), dtype=bool)
        if xlim is not None:
            mask &= (all_ranks >= xlim[0]) & (all_ranks <= xlim[1])
        if ylim is not None:
            mask &= (all_sims >= ylim[0]) & (all_sims <= ylim[1])
        all_ranks = all_ranks[mask]
        all_sims  = all_sims[mask]

    sim_lo,  sim_hi  = (ylim if ylim is not None else (0.38, 1.01))
    rank_lo, rank_hi = (xlim if xlim is not None else (1.0, float(n_cand) + 0.5))

    # 2次元KDE（スケールを正規化してからKDE計算）
    rx = (all_ranks - rank_lo) / (rank_hi - rank_lo)
    ry = (all_sims  - sim_lo)  / (sim_hi  - sim_lo)
    kde = gaussian_kde(np.vstack([rx, ry]), bw_method="scott")

    # X軸グリッド：log_x なら対数間隔
    if log_x:
        xg = np.logspace(np.log10(max(rank_lo, 1)), np.log10(rank_hi), n_grid)
    else:
        xg = np.linspace(rank_lo, rank_hi, n_grid)
    yg = np.linspace(sim_lo, sim_hi, n_grid)

    XX, YY = np.meshgrid(xg, yg)
    rxg = (XX - rank_lo) / (rank_hi - rank_lo)
    ryg = (YY - sim_lo)  / (sim_hi  - sim_lo)
    ZZ = kde(np.vstack([rxg.ravel(), ryg.ravel()])).reshape(XX.shape)
    ZZ /= ZZ.max()

    # カラースケール設定
    p_min = 0.02
    if log_color:
        norm         = LogNorm(vmin=p_min, vmax=1.0)
        levels_fill  = np.logspace(np.log10(p_min), 0, 25)
        cbar_ticks   = [0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
    else:
        norm         = None
        levels_fill  = np.linspace(p_min, 1.0, 20)
        cbar_ticks   = [0.2, 0.4, 0.6, 0.8, 1.0]

    cf = ax.contourf(XX, YY, ZZ, levels=levels_fill,
                     cmap="Reds", norm=norm, extend="neither", zorder=1)
    ax.contour(
        XX, YY, ZZ,
        levels=[0.05, 0.2, 0.5, 0.8],
        colors="k", linewidths=0.5, alpha=0.55, zorder=2,
    )

    cbar = fig.colorbar(cf, ax=ax, pad=0.02, fraction=0.046, ticks=cbar_ticks)
    cbar.set_label(r"$p\,(\mathrm{Rank,\ Cosine\ Similarity})$", fontsize=8, labelpad=4)
    cbar.ax.tick_params(labelsize=7)
    if log_color:
        cbar.ax.yaxis.set_major_formatter(ticker.LogFormatterSciNotation(base=10))

    # Similar（Yes）点をオーバーレイ
    yes_recs = [r for r in records if r["judgment"] == "Yes"]
    if yes_recs:
        xyes = np.array([r["rank"] for r in yes_recs])
        yyes = np.array([r["similarity"] for r in yes_recs])
        ax.scatter(
            xyes, yyes,
            facecolors="none", edgecolors="#1f77b4",
            marker="D", s=8, linewidths=0.6,
            label=f"Similar ($n={len(yes_recs)}$)",
            zorder=4, alpha=0.85,
        )

    n_all = len(records)
    ax.text(0.97, 0.97, f"$N = {n_all}$",
            transform=ax.transAxes, ha="right", va="top", fontsize=7.5)

    ax.set_xlabel("Rank")
    ax.set_ylabel("Cosine similarity")
    if log_x:
        ax.set_xscale("log")
        ax.set_xlim(rank_lo * 0.85, rank_hi)
        ax.xaxis.set_major_formatter(ticker.ScalarFormatter())
    else:
        ax.set_xlim(rank_lo, rank_hi)
        ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.set_ylim(sim_lo, sim_hi)
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(4))
    ax.legend(fontsize=7, framealpha=0.85, edgecolor="gray",
              loc="lower left", markerscale=1.2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  -> {out_path}")


# ---------------------------------------------------------------------------
# Figure 2: Scatter（全件、中ぬきマーカー）
# ---------------------------------------------------------------------------
def plot_scatter(
    records: list[dict],
    img_type: str,
    out_path: Path,
    xlim: tuple[float, float] | None = None,
    ylim: tuple[float, float] | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(COLUMN_W, 2.8))

    n_cand = records[0]["n_candidates"]

    n_yes     = sum(1 for r in records if r["judgment"] == "Yes")
    n_no      = sum(1 for r in records if r["judgment"] == "No")
    n_unknown = sum(1 for r in records if r["judgment"] == "Unknown")

    layers = [
        ("No",      "#d62728", "x",  18,  0.5, f"Non-similar ($n={n_no}$)"),
        ("Yes",     "#1f77b4", "D",  10,  0.8, f"Similar ($n={n_yes}$)"),
        ("Unknown", "#aaaaaa", "^",   9,  0.4, f"Unknown ($n={n_unknown}$)"),
    ]

    for label, color, marker, size, lw, leg in layers:
        recs = [r for r in records if r["judgment"] == label]
        if not recs:
            continue
        x = np.array([r["rank"] for r in recs])
        y = np.array([r["similarity"] for r in recs])

        zorder = {"No": 2, "Unknown": 1, "Yes": 3}[label]
        if marker == "x":
            ax.scatter(x, y, c=color, marker=marker, s=size,
                       linewidths=lw, label=leg, zorder=zorder, alpha=0.6)
        else:
            ax.scatter(x, y, facecolors="none", edgecolors=color,
                       marker=marker, s=size,
                       linewidths=lw, label=leg, zorder=zorder, alpha=0.85)

    ax.set_xlabel("Rank")
    ax.set_ylabel("Cosine similarity")
    ax.set_xlim(xlim if xlim is not None else (-5, n_cand + 10))
    ax.set_ylim(ylim if ylim is not None else (0.38, 1.02))
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    legend_loc = "lower right" if xlim is not None else "lower left"
    ax.legend(fontsize=7.5, framealpha=0.85, edgecolor="gray", loc=legend_loc)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  -> {out_path}")

# ---------------------------------------------------------------------------
# 画像ロード
# ---------------------------------------------------------------------------
def load_image(path: str | None) -> np.ndarray | None:
    if not path:
        return None
    try:
        img = ImageProcessor.process_file(path).convert("RGB")
        return np.array(img)
    except Exception as e:
        print(f"  [warn] {path}: {e}", file=sys.stderr)
        return None

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
# Figure 3: ペア比較画像グリッド（1 ペアにつき 1 PNG）
# ---------------------------------------------------------------------------
def plot_pair_comparison(
    rec: dict,
    top10: list[dict],
    out_path: Path,
) -> None:
    """
    3行 × 5列レイアウト:
      Row 0: [Query A (2列)] [Cited B (2列)] [情報テキスト (1列)]
      Row 1: Top-1 〜 Top-5
      Row 2: Top-6 〜 Top-10
    """
    N_COLS = 5
    CELL_W = 1.65
    CELL_H = 2.1

    fig = plt.figure(figsize=(CELL_W * N_COLS, CELL_H * 3))
    gs  = gridspec.GridSpec(
        3, N_COLS,
        figure=fig,
        hspace=0.55, wspace=0.10,
        top=0.90, bottom=0.02, left=0.01, right=0.99,
    )

    TITLE_FS   = 11
    CAPTION_FS = 10
    INFO_FS    = 10
    LEGEND_FS  = 12   # 凡例・強調テキスト

    def _panel(ax, img_path, title, caption, border=None, border_lw=3.0):
        arr = load_image(img_path)
        ax.set_xticks([]); ax.set_yticks([])
        if arr is not None:
            ax.imshow(arr, aspect="equal", interpolation="lanczos")
        else:
            ax.set_facecolor("#e8e8e8")
            ax.text(0.5, 0.5, "N/A", ha="center", va="center",
                    transform=ax.transAxes, fontsize=CAPTION_FS)
        ax.set_title(title, fontsize=TITLE_FS, pad=3, fontweight="bold")
        ax.set_xlabel(caption, fontsize=CAPTION_FS, labelpad=4)
        for sp in ax.spines.values():
            if border:
                sp.set_edgecolor(border); sp.set_linewidth(border_lw)
            else:
                sp.set_linewidth(0.6)

    # Row 0: Query A
    ax_a = fig.add_subplot(gs[0, :2])
    _panel(ax_a, rec["source_image"],
           f"Query: {rec['source']}", "")

    # Row 0: Cited target B
    j_color = "#1f77b4" if rec["judgment"] == "Yes" else "#d62728"
    ax_b = fig.add_subplot(gs[0, 2:4])
    _panel(ax_b, rec["target_image"],
           f"Expected (cited): {rec['target']}",
           (f"rank = {rec['rank']} / {rec['n_candidates']}"
            f"   $r_{{\\rm s}}$ = {rec['similarity']:.4f}\n"
            f"LLM: {rec['judgment']}   conf = {rec['confidence']}"),
           border=j_color)

    # Row 0: 情報テキスト
    ax_info = fig.add_subplot(gs[0, 4])
    ax_info.axis("off")
    info = (
        f"Class  : D18\n"
        f"Type   : perspective\n"
        f"N      : {rec['n_candidates'] + 1}\n"
        f"Rank   : {rec['rank']}\n"
        f"Sim    : {rec['similarity']:.4f}\n"
        f"LLM    : {rec['judgment']}\n"
        f"Conf   : {rec['confidence']}"
    )
    ax_info.text(0.06, 0.95, info, va="top", ha="left",
                 transform=ax_info.transAxes,
                 fontsize=INFO_FS, family="monospace",
                 bbox=dict(boxstyle="round,pad=0.4",
                           fc="white", ec="#999", alpha=0.9))

    # Rows 1–2: Top-10 近傍
    for i, nb in enumerate(top10[:10]):
        row = 1 + i // N_COLS
        col = i % N_COLS
        ax_n = fig.add_subplot(gs[row, col])

        pid_str  = int_to_patent_id(nb["patent_id_int"])
        is_cited = (pid_str == rec["target"])
        border   = "#ff7f0e" if is_cited else None
        caption  = f"$r_{{\\rm s}}$ = {nb['similarity']:.4f}"
        if is_cited:
            caption += "\n[cited target]"

        _panel(ax_n,
               nb["file_path"],
               f"#{nb['rank']}  {pid_str}",
               caption,
               border=border)

    # 凡例（境界線の意味）
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="none", edgecolor="#1f77b4", linewidth=3,
              label="Similar (LLM: Yes)"),
        Patch(facecolor="none", edgecolor="#d62728", linewidth=3,
              label="Non-similar (LLM: No)"),
        Patch(facecolor="none", edgecolor="#ff7f0e", linewidth=3,
              label="Cited target in top-10"),
    ]
    fig.legend(handles=legend_elements,
               fontsize=LEGEND_FS,
               loc="lower center",
               ncol=3,
               framealpha=0.9,
               edgecolor="gray",
               bbox_to_anchor=(0.5, -0.01))

    n_cand = rec["n_candidates"]
    fig.suptitle(
        (f"Nearest-neighbor retrieval: query {rec['source']}"
         f"  (D18 / perspective,  $N = {n_cand + 1}$)"),
        fontsize=12, y=0.995,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)

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
    parser.add_argument("--use-llm", action="store_true",
                        help="Qwen LLM でキーワード取得（デフォルト: フォールバックキーワードを使用）")
    args = parser.parse_args()

    # ── データ読み込み ──────────────────────────────────────────
    print("Loading joined rank-judgment records...")
    records = load_joined(args.target_class, args.sim, args.img_type)
    n_cand  = records[0]["n_candidates"]
    from collections import Counter
    cnt = Counter(r["judgment"] for r in records)
    print(f"  {len(records)} records  Yes={cnt['Yes']}  No={cnt['No']}  Unknown={cnt.get('Unknown',0)}")

    # # ── Yes レコードを exact / non-exact に分類 ─────────────────
    # if args.use_llm:
    #     sys.path.insert(0, str(Path(__file__).resolve().parent))
    #     from export_non_exact_pairs import ask_llm_for_keywords
    #     yes_reasons = [r["reason"] for r in records if r["judgment"] == "Yes"]
    #     print("\nQuerying Qwen for exact-match keywords ...")
    #     exact_kws, _ = ask_llm_for_keywords(yes_reasons)
    # else:
    #     exact_kws = FALLBACK_EXACT_KEYWORDS
    #     print(f"\n[LLM スキップ] exact keywords: {exact_kws}  (--use-llm で有効化)")
    # exact_pattern = build_exact_pattern(exact_kws)
    # classify_records(records, exact_pattern)
    # n_exact    = sum(1 for r in records if r.get("_label") == "Yes_exact")
    # n_nonexact = sum(1 for r in records if r.get("_label") == "Yes_nonexact")
    # print(f"  Exact match: {n_exact}  /  Non-exact similar: {n_nonexact}")

    # ── Figure 1: CCDF ──────────────────────────────────────────
    _set_style_stats()
    out_stats = OUT_BASE / args.target_class / args.sim
    out_stats.mkdir(parents=True, exist_ok=True)

    print("\n[1/3] Plotting CCDF...")
    plot_ccdf(records, args.img_type,
              out_stats / f"rank_ccdf_{args.img_type}.png")

    # ── Figure 2: Scatter ───────────────────────────────────────
    print("[2/3] Plotting scatter...")
    plot_scatter(records, args.img_type,
                 out_stats / f"rank_scatter_{args.img_type}.png")

    # ── Figure 2d: 2D density map ───────────────────────────────
    print("[2d] Plotting 2D density map...")
    plot_density_map(records, args.img_type,
                     out_stats / f"rank_density_{args.img_type}.png")

    # ── Figure 2d zoom ──────────────────────────────────────────
    print("[2d-zoom] Plotting 2D density map (zoom)...")
    plot_density_map(records, args.img_type,
                     out_stats / f"rank_density_{args.img_type}_zoom.png",
                     xlim=(0.5, 20.5),
                     ylim=(0.84, 1.01))

    # ── Figure 2d log-log ───────────────────────────────────────
    print("[2d-loglog] Plotting 2D density map (log rank)...")
    plot_density_map(records, args.img_type,
                     out_stats / f"rank_density_{args.img_type}_loglog.png",
                     ylim=(0.60, 1.01),
                     log_x=True, log_color=False)

    # ── Figure 2d log-log zoom ──────────────────────────────────
    print("[2d-loglog-zoom] Plotting 2D density map (log rank + log color, zoom)...")
    plot_density_map(records, args.img_type,
                     out_stats / f"rank_density_{args.img_type}_loglog_zoom.png",
                     xlim=(1.0, 20.5), ylim=(0.84, 1.01),
                     log_x=True, log_color=True)

    # ── Figure 2b: Scatter（拡大: rank ≤ 20, similarity ≥ 0.85） ──
    print("[2b] Plotting scatter (zoom)...")
    plot_scatter(records, args.img_type,
                 out_stats / f"rank_scatter_{args.img_type}_zoom.png",
                 xlim=(-0.5, 21),
                 ylim=(0.84, 1.02))

    # # ── Figure 3: ペア比較画像（Yes & rank <= top_k） ──────────
    # print(f"[3/3] Plotting pair comparison images (Yes, rank <= {args.top_k})...")
    # _set_style_image()

    # yes_topk = [
    #     r for r in records
    #     if r["judgment"] == "Yes" and r["rank"] <= args.top_k
    # ]
    # yes_topk.sort(key=lambda r: r["rank"])
    # print(f"  対象: {len(yes_topk)} 件")

    # out_img = (
    #     CLASS_BASE / args.target_class
    #     / "rank_analysis" / args.sim / args.img_type
    #     / "pair_comparison"
    # )

    # for rec in tqdm(yes_topk, desc="pair images", unit="件"):
    #     top10 = get_topk(rec["source"], args.img_type,
    #                      args.target_class, k=args.top_k)
    #     fname = (
    #         f"{rec['source']}--{rec['target']}"
    #         f"_rank{rec['rank']:03d}.png"
    #     )
    #     plot_pair_comparison(rec, top10, out_img / fname)

    # ── CSV: 高類似度レコード（similarity ≥ 0.950） ─────────────────
    print("[3/3] Exporting high-similarity CSV (>= 0.950)...")
    export_high_sim_csv(
        records,
        out_stats / f"high_sim_{args.img_type}_0950.csv",
        sim_threshold=0.950,
    )
    export_high_sim_csv(
        records,
        out_stats / f"high_sim_{args.img_type}_0950_judged.csv",
        sim_threshold=0.950,
        exclude_judgments=["Unknown"],
    )

    print(f"\n完了")
    print(f"  統計図: {out_stats}")


if __name__ == "__main__":
    main()
