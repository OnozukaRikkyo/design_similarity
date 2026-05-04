#!/usr/bin/env python3
"""
USPTO 意匠特許引用グラフの入次数分布を log-log プロットする。

2 パネル構成:
  (a) PDF  P(k)        — 全ノードを log-space ジッターで 1 点ずつ表示
  (b) CCDF P(K >= k)   — ランクを y 軸に割り当て、全ノードを 1 点ずつ表示

読み込み元: /mnt/eightthdd/uspto/edge_list/<year>.csv
出力:       indegree_distribution.png (または --output で指定)
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import LogLocator, NullFormatter

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
EDGE_DIR    = Path("/mnt/eightthdd/uspto/edge_list")
DEFAULT_OUT_PDF  = Path("indegree_pdf.png")
DEFAULT_OUT_CCDF = Path("indegree_ccdf.png")


# ---------------------------------------------------------------------------
# Matplotlib スタイル（PRL シングルカラム準拠）
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
# 入次数・出次数集計
# ---------------------------------------------------------------------------
def _csv_files(edge_dir: Path, years: list[str] | None) -> list[Path]:
    if years:
        return [edge_dir / f"{y}.csv" for y in years]
    return sorted(edge_dir.glob("*.csv"))


def compute_indegrees(edge_dir: Path, years: list[str] | None) -> Counter:
    counter: Counter = Counter()
    for path in _csv_files(edge_dir, years):
        if not path.exists():
            print(f"警告: {path} が見つかりません")
            continue
        print(f"  読み込み中 (in):  {path}")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                t = row.get("target", "").strip()
                if t:
                    counter[t] += 1
    return counter


def compute_outdegrees(edge_dir: Path, years: list[str] | None) -> Counter:
    counter: Counter = Counter()
    for path in _csv_files(edge_dir, years):
        if not path.exists():
            continue
        print(f"  読み込み中 (out): {path}")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                s = row.get("source", "").strip()
                if s:
                    counter[s] += 1
    return counter


def compute_degrees_undirected(edge_dir: Path, years: list[str] | None) -> Counter:
    """無向グラフの次数集計。各エッジが source・target 両端点に +1（自己ループは +2）。"""
    counter: Counter = Counter()
    for path in _csv_files(edge_dir, years):
        if not path.exists():
            print(f"警告: {path} が見つかりません")
            continue
        print(f"  読み込み中: {path}")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                s = row.get("source", "").strip()
                t = row.get("target", "").strip()
                if s:
                    counter[s] += 1
                if t:
                    counter[t] += 1
    return counter


# ---------------------------------------------------------------------------
# べき乗則フィット（log-log 空間での OLS）
# ---------------------------------------------------------------------------
def fit_powerlaw(k: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """
    y ∝ k^{-alpha} を OLS でフィット。

    Returns:
        alpha  : 指数（正値）
        log10c : 切片
        r2     : 決定係数
    """
    log_k = np.log10(k)
    log_y = np.log10(y)
    coeffs = np.polyfit(log_k, log_y, 1)
    alpha  = -coeffs[0]
    log10c = coeffs[1]
    residuals = log_y - np.polyval(coeffs, log_k)
    ss_tot = np.sum((log_y - log_y.mean()) ** 2)
    r2 = 1.0 - np.sum(residuals**2) / ss_tot if ss_tot > 0 else float("nan")
    return alpha, log10c, r2


# ---------------------------------------------------------------------------
# 共通ヘルパー
# ---------------------------------------------------------------------------
def _apply_log_axis_style(ax: plt.Axes) -> None:
    for axis in (ax.xaxis, ax.yaxis):
        axis.set_minor_locator(LogLocator(subs=np.arange(2, 10) * 0.1))
        axis.set_minor_formatter(NullFormatter())


def _set_equal_log_limits(
    ax: plt.Axes,
    x_arrays: list[np.ndarray],
    y_arrays: list[np.ndarray],
    pad: float = 0.15,
    x_gap: float = 0.08,
) -> None:
    """
    縦軸・横軸を同じデケード幅に揃え、y データを全件表示する。

    手順:
      1. y は全データ範囲 + pad でレンジを決定
      2. x は 10^(-x_gap) スタートで全データ + pad のレンジを決定
      3. 大きい方のデケード数を共通幅とする
      4. x は左端固定で右へ拡張、y はデータ中心を保ちつつ拡張

    pad   : 各軸の端余白（デケード単位）
    x_gap : y 軸スパインと 10^0 の間の余白（デケード単位）
    """
    x_all = np.concatenate([a[a > 0] for a in x_arrays])
    y_all = np.concatenate([a[a > 0] for a in y_arrays])

    # y: 全データが収まるレンジ
    y_log_lo = np.log10(y_all.min()) - pad
    y_log_hi = np.log10(y_all.max()) + pad
    y_decades = y_log_hi - y_log_lo

    # x: 10^0 より gap 分だけ左からスタート
    x_log_lo = -x_gap
    x_log_hi = np.log10(x_all.max()) + pad
    x_decades = x_log_hi - x_log_lo

    # 共通デケード幅 = 大きい方
    decades = max(x_decades, y_decades)

    # x: 左端固定、右へ伸ばす
    x_log_hi = x_log_lo + decades

    # y: データ中心を保ちつつ同じデケード幅に拡張
    y_center = (y_log_lo + y_log_hi) / 2
    y_log_lo = y_center - decades / 2
    y_log_hi = y_center + decades / 2

    ax.set_xlim(10 ** x_log_lo, 10 ** x_log_hi)
    ax.set_ylim(10 ** y_log_lo, 10 ** y_log_hi)
    ax.set_aspect("equal", adjustable="box")


def _save(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout(pad=0.5)
    fig.savefig(path)
    print(f"保存: {path}")
    plt.close(fig)


# ---------------------------------------------------------------------------
# (a) PDF プロット — 全ノードを log-space ジッターで 1 点ずつ表示
# ---------------------------------------------------------------------------
def _jitter_pdf(degrees: np.ndarray, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    """degrees 配列から (plot_k, plot_y) を生成。同一 k のノードに log-space ジッターを付与。"""
    N = len(degrees)
    unique_k, counts = np.unique(degrees, return_counts=True)
    pk = counts / N
    rng = np.random.default_rng(seed)
    plot_k = np.empty(N, dtype=float)
    plot_y = np.empty(N, dtype=float)
    idx = 0
    for k, p, c in zip(unique_k, pk, counts):
        plot_k[idx:idx + c] = k
        if c == 1:
            plot_y[idx] = p
        else:
            plot_y[idx:idx + c] = p * 10 ** rng.normal(0.0, 0.07, c)
        idx += c
    return plot_k, plot_y


def plot_pdf(
    degrees: np.ndarray,
    out_path: Path,
    fit: bool = True,
    years_label: str = "",
    degrees_out: np.ndarray | None = None,
) -> None:
    N = len(degrees)
    unique_k, counts = np.unique(degrees, return_counts=True)
    pk = counts / N
    plot_k, plot_y = _jitter_pdf(degrees, seed=42)

    fig, ax = plt.subplots(figsize=(3.6, 3.6))

    deg_label = "In-degree" if degrees_out is not None else "Degree"
    ax.scatter(
        plot_k, plot_y,
        s=3, facecolors="none", edgecolors="black", linewidths=0.4,
        zorder=3, rasterized=True, label=f"{deg_label}  ($N={N:,}$)",
    )

    if fit:
        alpha, log10c, r2 = fit_powerlaw(unique_k.astype(float), pk)
        k_fit = np.logspace(np.log10(unique_k.min()), np.log10(unique_k.max()), 300)
        fit_label = r"$\gamma_{{in}} = {:.2f}$".format(alpha) if degrees_out is not None else r"$\gamma = {:.2f}$".format(alpha)
        ax.plot(
            k_fit, 10**log10c * k_fit**(-alpha),
            color="black", lw=1.0, ls="--", zorder=4,
            label=fit_label,
        )
        print(f"PDF in  べき乗則: γ = {alpha:.3f},  R² = {r2:.3f}")

    all_k, all_y = [plot_k], [plot_y]

    if degrees_out is not None:
        No = len(degrees_out)
        unique_ko, counts_o = np.unique(degrees_out, return_counts=True)
        pko = counts_o / No
        plot_ko, plot_yo = _jitter_pdf(degrees_out, seed=7)
        ax.scatter(
            plot_ko, plot_yo,
            s=8, c="#d62728", linewidths=0.5,
            marker="x", zorder=3, rasterized=True,
            label=f"Out-degree ($N={No:,}$)",
        )
        if fit:
            alpha_o, log10c_o, r2_o = fit_powerlaw(unique_ko.astype(float), pko)
            k_fit_o = np.logspace(np.log10(unique_ko.min()), np.log10(unique_ko.max()), 300)
            ax.plot(
                k_fit_o, 10**log10c_o * k_fit_o**(-alpha_o),
                color="#d62728", lw=1.0, ls="--", zorder=4,
                label=r"$\gamma_{{out}} = {:.2f}$".format(alpha_o),
            )
            print(f"PDF out べき乗則: γ = {alpha_o:.3f},  R² = {r2_o:.3f}")
        all_k.append(plot_ko)
        all_y.append(plot_yo)

    title = "Degree distribution $P(k)$  [undirected]"
    if years_label:
        title += f"\nUSPTO design-patent citation graph  ({years_label})"
    ax.set_title(title, fontsize=8, pad=4)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(r"Degree $k$")
    ax.set_ylabel(r"$P(k)$")
    ax.legend(fontsize=7, frameon=False, handlelength=1.5)
    _set_equal_log_limits(ax, all_k, all_y)
    _apply_log_axis_style(ax)
    _save(fig, out_path)


# ---------------------------------------------------------------------------
# (b) CCDF プロット — 全ノードを昇順ランクで 1 点ずつ表示
# ---------------------------------------------------------------------------
def _ccdf_xy(degrees: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """昇順ソートして各ノードに CCDF 値を割り当てる。"""
    k_asc = np.sort(degrees)
    N = len(k_asc)
    return k_asc.astype(float), (N - np.arange(N)) / N


def plot_ccdf(
    degrees: np.ndarray,
    out_path: Path,
    fit: bool = True,
    years_label: str = "",
    degrees_out: np.ndarray | None = None,
) -> None:
    k_in, ccdf_in = _ccdf_xy(degrees)

    fig, ax = plt.subplots(figsize=(3.6, 3.6))

    deg_label = "In-degree" if degrees_out is not None else "Degree"
    ax.scatter(
        k_in, ccdf_in,
        s=3, facecolors="none", edgecolors="black", linewidths=0.4,
        zorder=3, rasterized=True, label=f"{deg_label}  ($N={len(degrees):,}$)",
    )

    if fit:
        unique_k, counts = np.unique(k_in, return_counts=True)
        cumcounts = np.cumsum(counts)
        ccdf_unique = (len(degrees) - (cumcounts - counts)) / len(degrees)
        alpha_c, log10c2, r2_c = fit_powerlaw(unique_k, ccdf_unique)
        k_fit = np.logspace(np.log10(k_in.min()), np.log10(k_in.max()), 300)
        fit_label = r"$\gamma_{{in}}-1 = {:.2f}$".format(alpha_c) if degrees_out is not None else r"$\gamma-1 = {:.2f}$".format(alpha_c)
        ax.plot(
            k_fit, 10**log10c2 * k_fit**(-alpha_c),
            color="black", lw=1.0, ls="--", zorder=4,
            label=fit_label,
        )
        print(f"CCDF in  べき乗則: γ-1 = {alpha_c:.3f},  R² = {r2_c:.3f}")

    all_k, all_y = [k_in], [ccdf_in]

    if degrees_out is not None:
        k_out, ccdf_out = _ccdf_xy(degrees_out)
        ax.scatter(
            k_out, ccdf_out,
            s=8, c="#d62728", linewidths=0.5,
            marker="x", zorder=3, rasterized=True,
            label=f"Out-degree ($N={len(degrees_out):,}$)",
        )
        if fit:
            unique_ko, counts_o = np.unique(k_out, return_counts=True)
            cumcounts_o = np.cumsum(counts_o)
            No = len(degrees_out)
            ccdf_unique_o = (No - (cumcounts_o - counts_o)) / No
            alpha_o, log10c_o, r2_o = fit_powerlaw(unique_ko, ccdf_unique_o)
            k_fit_o = np.logspace(np.log10(k_out.min()), np.log10(k_out.max()), 300)
            ax.plot(
                k_fit_o, 10**log10c_o * k_fit_o**(-alpha_o),
                color="#d62728", lw=1.0, ls="--", zorder=4,
                label=r"$\gamma_{{out}}-1 = {:.2f}$".format(alpha_o),
            )
            print(f"CCDF out べき乗則: γ-1 = {alpha_o:.3f},  R² = {r2_o:.3f}")
        all_k.append(k_out)
        all_y.append(ccdf_out)

    title = r"Complementary CDF $P(K \geq k)$  [undirected]"
    if years_label:
        title += f"\nUSPTO design-patent citation graph  ({years_label})"
    ax.set_title(title, fontsize=8, pad=4)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel(r"Degree $k$")
    ax.set_ylabel(r"$P(K \geq k)$")
    ax.legend(fontsize=7, frameon=False, handlelength=1.5)
    _set_equal_log_limits(ax, all_k, all_y)
    _apply_log_axis_style(ax)
    _save(fig, out_path)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="USPTO意匠特許引用グラフの入次数分布をlog-logで描画（2ファイル出力）"
    )
    parser.add_argument(
        "years", nargs="*",
        help="処理する年 (例: 2007 2008)。省略時は全CSV"
    )
    parser.add_argument(
        "--out-pdf", default=str(DEFAULT_OUT_PDF),
        help=f"PDF図の出力パス (default: %(default)s)"
    )
    parser.add_argument(
        "--out-ccdf", default=str(DEFAULT_OUT_CCDF),
        help=f"CCDF図の出力パス (default: %(default)s)"
    )
    parser.add_argument(
        "--edge-dir", default=str(EDGE_DIR),
        help="エッジリストCSVのディレクトリ (default: %(default)s)"
    )
    parser.add_argument(
        "--no-fit", action="store_true",
        help="べき乗則フィットを省略"
    )
    parser.add_argument(
        "--usetex", action="store_true",
        help="LaTeX でテキストレンダリング（要 texlive）"
    )
    args = parser.parse_args()

    years = args.years or None
    years_label = ", ".join(years) if years else "2007–2010"

    print("次数を集計中（無向グラフ）...")
    counter = compute_degrees_undirected(Path(args.edge_dir), years)
    if not counter:
        print("エラー: エッジが見つかりませんでした。--edge-dir を確認してください。")
        return

    degrees = np.array(list(counter.values()), dtype=np.int64)
    print(f"\nノード数={len(degrees):,}  "
          f"min={degrees.min()}, max={degrees.max()}, mean={degrees.mean():.2f}")

    _set_style(args.usetex)

    plot_pdf(degrees,  Path(args.out_pdf),  fit=not args.no_fit, years_label=years_label)
    plot_ccdf(degrees, Path(args.out_ccdf), fit=not args.no_fit, years_label=years_label)


if __name__ == "__main__":
    main()
