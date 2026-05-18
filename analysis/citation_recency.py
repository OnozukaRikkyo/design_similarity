#!/usr/bin/env python3
"""
analysis/citation_recency.py

USPTO Design Patent Co-citation Network — Recency Effect Analysis
Outputs separate PNG files with explicit titles.

Fig. 1  fig_vintage_effect.png  — Cumulative co-citations by filing year
Fig. 2  fig_recency_rate.png    — Annual co-citation rate by filing year

Usage:
    python analysis/citation_recency.py
    python analysis/citation_recency.py --out-dir analysis/output --min-n 5
"""

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import pandas as pd

# ─────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────
EDGE_DIR = Path("/mnt/eightthdd/uspto/edge_list")
DATA_DIR = Path("/mnt/eightthdd/uspto/data")
OUT_DIR  = Path("analysis/output")

OBS_END_YEAR   = 2022
OBS_START_YEAR = 2007
MIN_N_PER_YEAR = 10

# ─────────────────────────────────────────────────────────────────────
# Physical-science (PRL/PRE) style
# ─────────────────────────────────────────────────────────────────────
PLT_STYLE: dict = {
    "font.family":          "serif",
    "mathtext.fontset":     "stix",
    "font.size":            12,
    "axes.labelsize":       13,
    "axes.titlesize":       14,
    "xtick.labelsize":      11,
    "ytick.labelsize":      11,
    "xtick.direction":      "in",
    "ytick.direction":      "in",
    "xtick.minor.visible":  True,
    "ytick.minor.visible":  True,
    "xtick.top":            True,
    "ytick.right":          True,
    "axes.linewidth":       1.2,
    "figure.facecolor":     "white",
    "axes.facecolor":       "white",
    "lines.linewidth":      1.2,
    "savefig.dpi":          300,
    "savefig.bbox":         "tight",
    "savefig.pad_inches":   0.05,
}

COLOR_CUMUL = "#1f77b4"   # muted blue  (matplotlib C0)
COLOR_RATE  = "#2ca02c"   # cooked asparagus green (matplotlib C2)

BOX_PROPS = dict(
    patch_artist=True,
    widths=0.6,
    showfliers=True,
    flierprops=dict(marker=".", markersize=2.0, alpha=0.4,
                    color="#555555", markeredgecolor="none"),
    medianprops=dict(color="black", linewidth=1.5),
    whiskerprops=dict(linestyle="-", linewidth=1.0, color="black"),
    capprops=dict(linewidth=1.0, color="black"),
)

# ─────────────────────────────────────────────────────────────────────
# Data loading
# ─────────────────────────────────────────────────────────────────────
def load_patent_dates(data_dir: Path) -> dict[str, int]:
    """Returns {patent_id: filing_year} from data/*.csv (date column = YYYYMMDD)."""
    dfs = []
    for p in sorted(data_dir.glob("*.csv")):
        try:
            dfs.append(pd.read_csv(p, usecols=["id", "date"], dtype=str,
                                   on_bad_lines="skip"))
        except Exception as e:
            print(f"  [warn] {p.name}: {e}")
    if not dfs:
        return {}
    combined = pd.concat(dfs, ignore_index=True).dropna(subset=["id", "date"])
    combined["filing_year"] = (
        combined["date"].str.strip().str[:4]
        .where(combined["date"].str.strip().str[:4].str.isdigit())
        .astype("Int64")
    )
    combined = combined.dropna(subset=["filing_year"])
    return dict(zip(combined["id"].str.strip(), combined["filing_year"].astype(int)))


def load_citation_counts(edge_dir: Path) -> dict[str, int]:
    """
    Returns {patent_id: undirected degree} in co-citation network.
    Duplicate OA events for the same pair are collapsed to one edge.
    """
    dfs = []
    for p in sorted(edge_dir.glob("*.csv")):
        try:
            dfs.append(pd.read_csv(p, usecols=["source", "target"], dtype=str,
                                   on_bad_lines="skip"))
        except Exception as e:
            print(f"  [warn] {p.name}: {e}")
    if not dfs:
        return {}

    edges = pd.concat(dfs, ignore_index=True).dropna()
    edges["source"] = edges["source"].str.strip()
    edges["target"] = edges["target"].str.strip()

    # Canonicalise direction so deduplication is order-independent
    swap = edges["source"] > edges["target"]
    orig_src = edges.loc[swap, "source"].values.copy()
    orig_tgt = edges.loc[swap, "target"].values.copy()
    edges.loc[swap, "source"] = orig_tgt
    edges.loc[swap, "target"] = orig_src

    edges = edges.drop_duplicates(subset=["source", "target"])

    src_deg = edges.groupby("source").size()
    tgt_deg = edges.groupby("target").size()
    return src_deg.add(tgt_deg, fill_value=0).astype(int).to_dict()


def build_df(patent_year: dict, citation_count: dict) -> pd.DataFrame:
    """Join year and count; annual_rate = count / effective_age (always > 0)."""
    rows = []
    for pid, cnt in citation_count.items():
        year = patent_year.get(pid)
        if year is None:
            continue
        obs_start = max(year, OBS_START_YEAR)
        age = max(1, OBS_END_YEAR - obs_start + 1)
        rows.append({
            "filing_year":  year,
            "count":        cnt,
            "annual_rate":  cnt / age,
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────
# Plotting helpers
# ─────────────────────────────────────────────────────────────────────
def _valid_years(df: pd.DataFrame, min_n: int = MIN_N_PER_YEAR) -> list[int]:
    counts = df.groupby("filing_year").size()
    return sorted(counts[counts >= min_n].index.tolist())


def _style_ax_log(ax: plt.Axes, years: list[int], ylabel: str,
                  title: str) -> None:
    """Apply log Y-scale, 10^x tick labels, and axis labels with title."""
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(ticker.LogFormatterMathtext())

    xs = list(range(len(years)))
    ax.set_xticks(xs)
    ax.set_xticklabels([str(y) for y in years], rotation=45, ha="right")

    ax.set_xlabel("Filing Year", labelpad=8)
    ax.set_ylabel(ylabel, labelpad=8)
    ax.set_title(title, pad=12, fontweight="bold")
    ax.set_xlim(-0.7, len(years) - 0.3)


def _draw_boxplot(ax: plt.Axes, data: list, color: str) -> dict:
    bp = ax.boxplot(data, positions=range(len(data)), **BOX_PROPS)
    for patch in bp["boxes"]:
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    return bp


# ─────────────────────────────────────────────────────────────────────
# Figures
# ─────────────────────────────────────────────────────────────────────
def make_individual_figs(df: pd.DataFrame, out_dir: Path, min_n: int) -> None:
    """Generate two standalone PNG files, one per metric."""
    out_dir.mkdir(parents=True, exist_ok=True)

    years     = _valid_years(df, min_n)
    cnt_data  = [df.loc[df["filing_year"] == y, "count"].values for y in years]
    rate_data = [df.loc[df["filing_year"] == y, "annual_rate"].values for y in years]
    n_total   = df.loc[df["filing_year"].isin(years)].shape[0]

    # ── Fig. 1: Vintage Effect ──────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=(8, 6))
    bp1 = _draw_boxplot(ax1, cnt_data, COLOR_CUMUL)
    _style_ax_log(ax1, years,
                  ylabel="Citation Count",
                  title="Vintage Effect: Citation Count by Filing Year")
    ax1.set_yscale("linear")
    ax1.yaxis.set_major_formatter(ticker.ScalarFormatter())
    ax1.set_ylim(0, 25)

    for i, vals in enumerate(cnt_data):
        whisker_top = bp1["whiskers"][2 * i + 1].get_ydata()[1]
        text_y = min(whisker_top, 25) + 0.3
        ax1.text(i, text_y, str(len(vals)), ha="center", va="bottom", fontsize=10)

    path1 = out_dir / "fig_vintage_effect.png"
    fig1.tight_layout()
    fig1.savefig(path1)
    plt.close(fig1)
    print(f"  Saved → {path1}")

    # ── Fig. 2: Receiver Recency Effect ────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(8, 6))
    _draw_boxplot(ax2, rate_data, COLOR_RATE)
    _style_ax_log(ax2, years,
                  ylabel=r"Annual Co-citation Rate, $R\ [\mathrm{yr}^{-1}]$",
                  title="Receiver Recency Effect: Annual Co-citation Rate by Filing Year")
    y_lo, y_hi = ax2.get_ylim()
    ax2.set_ylim(y_lo, y_hi * 2.5)
    ax2.text(0.96, 0.96,
             f"Obs: {OBS_START_YEAR}–{OBS_END_YEAR}\n$N = {n_total:,}$",
             transform=ax2.transAxes, ha="right", va="top", fontsize=11)

    path2 = out_dir / "fig_recency_rate.png"
    fig2.tight_layout()
    fig2.savefig(path2)
    plt.close(fig2)
    print(f"  Saved → {path2}")


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Generate recency-effect boxplot figures for USPTO design patents."
    )
    ap.add_argument("--edge-dir", default=str(EDGE_DIR))
    ap.add_argument("--data-dir", default=str(DATA_DIR))
    ap.add_argument("--out-dir",  default=str(OUT_DIR))
    ap.add_argument("--min-n",    type=int, default=MIN_N_PER_YEAR,
                    help="Minimum patents per filing-year bin to include")
    ap.add_argument("--obs-end",  type=int, default=OBS_END_YEAR,
                    help="Observation window end year (default: 2022)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    global OBS_END_YEAR
    OBS_END_YEAR = args.obs_end

    edge_dir = Path(args.edge_dir)
    data_dir = Path(args.data_dir)
    out_dir  = Path(args.out_dir)

    matplotlib.rcParams.update(PLT_STYLE)

    print("Loading patent dates …")
    patent_year = load_patent_dates(data_dir)
    print(f"  {len(patent_year):,} patents with dates")

    print("Loading citation counts …")
    citation_count = load_citation_counts(edge_dir)
    print(f"  {len(citation_count):,} patents in co-citation network")

    print("Building analysis dataframe …")
    df = build_df(patent_year, citation_count)
    year_min, year_max = df["filing_year"].min(), df["filing_year"].max()
    print(f"  {len(df):,} matched patents  |  year range {year_min}–{year_max}")

    valid = _valid_years(df, args.min_n)
    print(f"  {len(valid)} filing-year bins with ≥ {args.min_n} patents "
          f"({valid[0]}–{valid[-1]})")

    print("\nGenerating figures …")
    make_individual_figs(df, out_dir, args.min_n)

    print("\nDone.")


if __name__ == "__main__":
    main()
