#!/usr/bin/env python3
"""
Two-heatmap generator for USPTO design patent similarity data.
Publication-quality figures conforming to APS Physical Review style.

Heatmap 1 — Reference (all pairs):
    /mnt/eightthdd/uspto/all_pair/qwen_all_pairs/**/*.jsonl

Heatmap 2 — LLM-similar pairs:
    /mnt/eightthdd/uspto/yes_pair/qwen/exact_match/**/*.jsonl
    /mnt/eightthdd/uspto/yes_pair/qwen/high_similar/**/*.jsonl
    /mnt/eightthdd/uspto/yes_pair/qwen/similar/**/*.jsonl
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ── Inline paths ──────────────────────────────────────────────────────
REFERENCE_DIR = Path("/mnt/eightthdd/uspto/all_pair/qwen_all_pairs")

SIMILAR_DIRS = [
    Path("/mnt/eightthdd/uspto/yes_pair/qwen/exact_match"),
    Path("/mnt/eightthdd/uspto/yes_pair/qwen/high_similar"),
    Path("/mnt/eightthdd/uspto/yes_pair/qwen/similar"),
]

OUT_DIR  = Path("output")
OUT_REF  = OUT_DIR / "heatmap_reference.png"
OUT_SIM  = OUT_DIR / "heatmap_similar.png"
TOP_N    = 14
FIG_DPI  = 600   # 600 dpi for print submission

# US design patent class names — authoritative source:
#   /home/sonozuka/multimodal/plot_class_histogram.py
# Keys zero-padded to match parse_class() output (D01–D34, D99).
CLASS_NAMES = {
    "D01": "Edible Products",
    "D02": "Apparel & Haberdashery",
    "D03": "Travel Goods & Personal Items",
    "D04": "Brushware",
    "D05": "Textile/Fabric Articles",
    "D06": "Furnishings",
    "D07": "Equipment for Preparing Food",
    "D08": "Tools & Hardware",
    "D09": "Tools & Hardware (misc)",
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

# ── APS Physical Review RC params ─────────────────────────────────────
matplotlib.rcParams.update({
    # Font — Computer Modern (LaTeX) via mathtext; fallback DejaVu Serif
    "font.family":        "serif",
    "font.serif":         ["Times New Roman", "DejaVu Serif", "Palatino"],
    "mathtext.fontset":   "stix",
    "font.size":          13,
    "axes.titlesize":     14,
    "axes.labelsize":     13,
    "xtick.labelsize":    12,
    "ytick.labelsize":    12,
    "legend.fontsize":    11,
    # Tick marks — inward, major on all four sides
    "xtick.direction":    "in",
    "ytick.direction":    "in",
    "xtick.top":          True,
    "ytick.right":        True,
    "xtick.major.size":   4.5,
    "ytick.major.size":   4.5,
    "xtick.minor.size":   2.5,
    "ytick.minor.size":   2.5,
    "xtick.major.width":  0.8,
    "ytick.major.width":  0.8,
    # Axes
    "axes.linewidth":     0.8,
    "axes.grid":          False,
    # Figure
    "figure.dpi":         FIG_DPI,
    "savefig.dpi":        FIG_DPI,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.05,
    # Fonts embedded in PDF
    "pdf.fonttype":       42,
    "ps.fonttype":        42,
})


def parse_class(raw: str) -> str:
    """'D 6480' → 'D06',  'D34 38' → 'D34'"""
    m = re.match(r"D\s*0*(\d+)", str(raw).strip(), re.I)
    if not m:
        return "D??"
    n = int(m.group(1))
    if (1 <= n <= 34) or n == 99:
        return f"D{n:02d}"
    return "D??"


def load_class_pairs(roots: list[Path]) -> tuple[defaultdict, defaultdict]:
    pair_cnt = defaultdict(int)
    cls_cnt  = defaultdict(int)
    total_files = 0

    for root in roots:
        for jpath in sorted(root.rglob("*.jsonl")):
            total_files += 1
            print(f"  {jpath.relative_to(root.parent)} ...")
            with open(jpath, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rec = json.loads(line)
                    sc = parse_class(rec.get("source_class", ""))
                    tc = parse_class(rec.get("target_class", ""))
                    if sc == "D??" or tc == "D??":
                        continue
                    pair_cnt[(sc, tc)] += 1
                    cls_cnt[sc] += 1
                    cls_cnt[tc] += 1

    total = sum(pair_cnt.values())
    print(f"  → {total_files} files, {total:,} pairs")
    return pair_cnt, cls_cnt


def make_heatmap(
    pair_cnt: defaultdict,
    cls_cnt:  defaultdict,
    out_path: Path,
    title: str,
    subtitle: str = "",
    top_n: int = TOP_N,
) -> None:
    top_cls = [c for c, _ in sorted(cls_cnt.items(), key=lambda x: -x[1])][:top_n]

    mat     = np.array([[pair_cnt[(r, c)] for c in top_cls]
                        for r in top_cls], dtype=float)
    log_mat = np.log1p(mat)          # natural log (ln)

    diag_sum     = sum(pair_cnt[(c, c)] for c in top_cls)
    total_in_mat = mat.sum()
    within_pct   = diag_sum / total_in_mat * 100 if total_in_mat > 0 else 0
    print(f"  Within-class: {diag_sum:,}  ({within_pct:.1f}%)")
    print(f"  Cross-class : {int(total_in_mat - diag_sum):,}  ({100 - within_pct:.1f}%)")

    # Double-column APS width: 17.2 cm ≈ 6.77 in; use slightly wider for 14×14
    fig, ax = plt.subplots(figsize=(9.5, 8.5))

    im = ax.imshow(
        log_mat, cmap="YlOrRd", aspect="equal", origin="upper",
        vmin=0, vmax=log_mat.max(),
    )

    # Teal border on each diagonal cell (within-class)
    for i in range(len(top_cls)):
        ax.add_patch(plt.Rectangle(
            (i - 0.5, i - 0.5), 1, 1,
            fill=False, edgecolor="#1a5e63", linewidth=2.0, zorder=4,
        ))

    # Annotate cells above 4% of max
    threshold = mat.max() * 0.04
    for i, r in enumerate(top_cls):
        for j, c in enumerate(top_cls):
            v = int(mat[i, j])
            if v >= threshold:
                txt_col = "white" if log_mat[i, j] > log_mat.max() * 0.60 else "#111111"
                ax.text(j, i, f"{v:,}",
                        ha="center", va="center",
                        fontsize=8.5, color=txt_col, fontweight="bold", zorder=5)

    # X/Y axis labels — class code only (names kept in CLASS_NAMES for CSV export)
    ax.set_xticks(range(len(top_cls)))
    ax.set_xticklabels(top_cls, rotation=45, ha="right", rotation_mode="anchor",
                       fontsize=12)
    ax.set_yticks(range(len(top_cls)))
    ax.set_yticklabels(top_cls, fontsize=12)

    ax.set_xlabel("Target class (cited patent)", fontsize=13, labelpad=10)
    ax.set_ylabel("Source class (citing patent)", fontsize=13, labelpad=10)

    # Suppress matplotlib's own tick marks on image axes (pixels are discrete)
    ax.tick_params(which="both", length=0)
    for sp in ax.spines.values():
        sp.set_linewidth(0.8)

    # Colorbar
    cbar = plt.colorbar(im, ax=ax, pad=0.015, shrink=0.80, aspect=24)
    cbar.set_label(r"$\ln(\mathrm{count} + 1)$", fontsize=13)
    cbar.ax.tick_params(labelsize=11)
    max_count = int(mat.max())
    n_pairs   = int(total_in_mat)
    cbar.ax.text(
        3.0, log_mat.max(),
        f"max = {max_count:,}",
        ha="left", va="top", fontsize=10, color="#444444",
        transform=cbar.ax.transData,
    )
    cbar.outline.set_linewidth(0.8)

    # Title (no "Figure" prefix per user instruction)
    full_title = title
    if subtitle:
        full_title += f"\n{subtitle}"
    ax.set_title(full_title, fontsize=14, pad=12, color="#111111")

    # Stats annotation — upper right, prominent
    stats_txt = (
        f"$N = {n_pairs:,}$\n"
        f"Within-class: {within_pct:.1f}%\n"
        f"Cross-class: {100 - within_pct:.1f}%"
    )
    ax.text(
        0.985, 0.985, stats_txt,
        transform=ax.transAxes, ha="right", va="top",
        fontsize=15, color="#111111", linespacing=1.5,
        bbox=dict(boxstyle="round,pad=0.45", fc="white", ec="#888888",
                  alpha=0.55, linewidth=0.9),
    )

    fig.tight_layout()
    fig.savefig(out_path, dpi=FIG_DPI, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  → {out_path}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Heatmap 1: Reference (all pairs)")
    print("=" * 60)
    pair_cnt_ref, cls_cnt_ref = load_class_pairs([REFERENCE_DIR])
    make_heatmap(
        pair_cnt_ref, cls_cnt_ref, OUT_REF,
        title="Cross-class design patent pair frequency (log scale)",
        subtitle="Reference dataset — all examiner-cited pairs",
    )

    print()
    print("=" * 60)
    print("Heatmap 2: LLM-similar pairs")
    print("=" * 60)
    pair_cnt_sim, cls_cnt_sim = load_class_pairs(SIMILAR_DIRS)
    make_heatmap(
        pair_cnt_sim, cls_cnt_sim, OUT_SIM,
        title="Cross-class design patent pair frequency (log scale)",
        subtitle="LLM-judged similar pairs ",
    )

    print()
    print("Done.")
    print(f"  {OUT_REF}")
    print(f"  {OUT_SIM}")


if __name__ == "__main__":
    main()
