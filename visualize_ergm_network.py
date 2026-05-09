#!/usr/bin/env python3
"""
USPTO Design Patent Co-citation Network Visualizer
====================================================
Full implementation of equations from:
  Chakraborty, Byshkin & Crestani (2020)
  "Patent citation network analysis: A perspective from
   descriptive statistics and ERGMs"  PLoS ONE 15(12): e0241797.

Equations implemented
─────────────────────
Eq.(1)  ERGM probability:   pi(x) = exp(sum theta_s g_s(x)) / Z
Eq.(2)  Arc statistic:      g_L(x) = sum x_{i,j}
Eq.(4)  Sender effect:      g_send(x) = sum_{i,j} a_i x_{i,j}
Eq.(5)  Receiver effect:    g_rec(x)  = sum_{i,j} a_j x_{i,j}
Eq.(6)  Homophily:          g_homo(x) = sum_{i,j} delta(a_i,a_j) x_{i,j}
Eq.(7)  Date guard:         g_date(x) = sum_{i,j} H(d_j - d_i) x_{i,j}
Eq.(9)  Transitivity T:     3 x triangles / connected-triples
Eq.(10) Density D:          |E| / (|V|(|V|-1))
Eq.(11) Betweenness g(v):   sum_{s!=v!=t} sigma_st(v) / sigma_st

Network statistics (Snijders et al.)
  GWIDegree  (AltInStar)
  GWODegree  (AltOutStar)
  GWESP      (AltKTriangleT)
  GWDSP      (AltTwoPathsTD)

Outputs
───────
  output/fig1_network_topology.png      Eq.(9)(10) -- structural overview
  output/fig2_ergm_statistics.png       Eq.(1-8)   -- ERGM sufficient statistics
  output/fig3_degree_distribution.png   Eq.(10)(11) -- degree + betweenness
  output/fig4_homophily_heatmap.png     Eq.(6) -- delta(a_i,a_j) matrix (35x35)
  output/fig5_sender_receiver.png       Eq.(4)(5) -- per-class send/recv
  output/fig6_gw_statistics.png         GWIDeg / GWODeg / GWESP / GWDSP
  output/fig7_date_guard.png            Eq.(7)(8) -- temporal citation bias
  output/ergm_statistics.csv           all computed statistics

Usage
─────
  python visualize_ergm_network.py
  python visualize_ergm_network.py --ergm-dir ./ergm_input --out-dir ./output
  python visualize_ergm_network.py --top-n 500 --bc-k 1000
  python visualize_ergm_network.py --no-fig6   # skip slow GW stats
"""

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import networkx as nx
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Publication-quality style
# ---------------------------------------------------------------------------
PLT_STYLE = {
    "figure.facecolor":   "white",
    "axes.facecolor":     "white",
    "axes.edgecolor":     "#222222",
    "axes.linewidth":     0.8,
    "axes.grid":          True,
    "grid.color":         "#DDDDDD",
    "grid.linewidth":     0.5,
    "font.family":        "sans-serif",
    "font.size":          9,
    "axes.labelsize":     9,
    "axes.titlesize":     10,
    "xtick.labelsize":    8,
    "ytick.labelsize":    8,
    "legend.fontsize":    8,
    "legend.framealpha":  0.9,
    "lines.linewidth":    1.2,
    "savefig.dpi":        300,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.05,
}
matplotlib.rcParams.update(PLT_STYLE)

# ---------------------------------------------------------------------------
# D-class constants
# ---------------------------------------------------------------------------
ALL_CLASSES = [f"D{i}" for i in range(1, 35)] + ["D99"]

CLASS_NAMES = {
    "D1":  "Edible Prods.",     "D2":  "Apparel",
    "D3":  "Travel Goods",      "D4":  "Brushware",
    "D5":  "Textile",           "D6":  "Furnishings",
    "D7":  "Food Equip.",       "D8":  "Tools/Hardware",
    "D9":  "Tools (misc)",      "D10": "Measuring Dev.",
    "D11": "Jewelry",           "D12": "Transportation",
    "D13": "Prod. Equip.",      "D14": "Rec./Comm./Info.",
    "D15": "Machines",          "D16": "Photography",
    "D17": "Musical Instr.",    "D18": "Printing/Office",
    "D19": "Office Suppl.",     "D20": "Sales/Advert.",
    "D21": "Amusement Dev.",    "D22": "Arms/Pyro.",
    "D23": "Heating/Cooling",   "D24": "Medical/Lab",
    "D25": "Building/Constr.",  "D26": "Lighting",
    "D27": "Tobacco",           "D28": "Pharma/Cosmet.",
    "D29": "Animal Husb.",      "D30": "Outdoor/Garden",
    "D31": "Articles Mfg.",     "D32": "Washing/Clean.",
    "D33": "Food/Bev Svc.",     "D34": "Material Hdl.",
    "D99": "Misc.",
}

# 35 distinct qualitative colors: tab20 (20) + tab20b[:15]
_c20a = list(plt.cm.tab20.colors)
_c20b = list(plt.cm.tab20b.colors)
_PALETTE = _c20a + _c20b[:15]


def cls_color(c: str) -> tuple:
    idx = ALL_CLASSES.index(c) if c in ALL_CLASSES else 34
    return _PALETTE[idx]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_attrs(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", low_memory=False)


def load_arc_list(path: Path) -> list[tuple[int, int]]:
    arcs = []
    with open(path) as f:
        for line in f:
            p = line.strip().split()
            if len(p) == 2:
                arcs.append((int(p[0]), int(p[1])))
    return arcs


def arcs_to_undirected(arcs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    for u, v in arcs:
        if u != v:
            seen.add((min(u, v), max(u, v)))
    return list(seen)


def build_networkx(n_nodes: int, edges: list[tuple[int, int]]) -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(range(n_nodes))
    G.add_edges_from(edges)
    return G


def attach_attrs(G: nx.Graph, attrs: pd.DataFrame) -> None:
    for i in G.nodes():
        if i >= len(attrs):
            G.nodes[i]["primary_class"] = "Unknown"
            G.nodes[i]["n_classes"]     = 0
            G.nodes[i]["date"]          = ""
        else:
            row = attrs.iloc[i]
            G.nodes[i]["primary_class"] = str(row.get("primary_class", "Unknown"))
            nc = row.get("n_classes", 0)
            G.nodes[i]["n_classes"] = int(nc) if pd.notna(nc) else 0
            G.nodes[i]["date"] = str(row.get("date", ""))


# ---------------------------------------------------------------------------
# Eq.(2)  Arc statistic
# ---------------------------------------------------------------------------
def eq2_arc_stat(arcs: list) -> int:
    """g_L(x) = sum x_{i,j}"""
    return len(arcs)


# ---------------------------------------------------------------------------
# Eq.(4)  Sender effect per class
# ---------------------------------------------------------------------------
def eq4_sender_effect(arcs: list, node_class: dict) -> dict:
    """g_send(x; a) = sum_{i,j} a_i x_{i,j}  [directed arcs]"""
    cnt: dict[str, int] = defaultdict(int)
    for i, _j in arcs:
        cnt[node_class.get(i, "Unknown")] += 1
    return dict(cnt)


# ---------------------------------------------------------------------------
# Eq.(5)  Receiver effect per class
# ---------------------------------------------------------------------------
def eq5_receiver_effect(arcs: list, node_class: dict) -> dict:
    """g_rec(x; a) = sum_{i,j} a_j x_{i,j}"""
    cnt: dict[str, int] = defaultdict(int)
    for _i, j in arcs:
        cnt[node_class.get(j, "Unknown")] += 1
    return dict(cnt)


# ---------------------------------------------------------------------------
# Eq.(6)  Homophily matrix
# ---------------------------------------------------------------------------
def eq6_homophily(
    edges: list,
    node_class: dict,
    cls_list: list[str],
) -> np.ndarray:
    """g_homo(x) = sum delta(a_i, a_j) x_{i,j}  ->  35x35 matrix"""
    idx = {c: k for k, c in enumerate(cls_list)}
    mat = np.zeros((len(cls_list), len(cls_list)), dtype=np.int64)
    for u, v in edges:
        cu = node_class.get(u, "Unknown")
        cv = node_class.get(v, "Unknown")
        if cu in idx and cv in idx:
            mat[idx[cu], idx[cv]] += 1
            if cu != cv:
                mat[idx[cv], idx[cu]] += 1
    return mat


# ---------------------------------------------------------------------------
# Eq.(7)/(8)  Date guard
# ---------------------------------------------------------------------------
def eq7_date_guard(arcs: list, node_date: dict) -> int:
    """
    g_date(x) = sum H(d_j - d_i) x_{i,j}
    H(y) = 0 if y <= 0, else 1  (Eq. 8)
    Returns count of "forward arcs" (arc i->j where j is newer than i).
    """
    violations = 0
    for i, j in arcs:
        di = node_date.get(i)
        dj = node_date.get(j)
        if di is not None and dj is not None and (dj - di).days > 0:
            violations += 1
    return violations


# ---------------------------------------------------------------------------
# Eq.(9)  Transitivity
# ---------------------------------------------------------------------------
def eq9_transitivity(G: nx.Graph) -> float:
    """T = 3 x triangles / connected-triples"""
    return nx.transitivity(G)


# ---------------------------------------------------------------------------
# Eq.(10) Density
# ---------------------------------------------------------------------------
def eq10_density(G: nx.Graph) -> float:
    """D = |E| / (|V|(|V|-1))"""
    N = G.number_of_nodes()
    M = G.number_of_edges()
    return M / (N * (N - 1)) if N >= 2 else 0.0


# ---------------------------------------------------------------------------
# Eq.(11) Betweenness centrality
# ---------------------------------------------------------------------------
def eq11_betweenness(G: nx.Graph, k: int = 500) -> dict:
    """g(v) = sum_{s!=v!=t} sigma_st(v) / sigma_st"""
    N = G.number_of_nodes()
    if N <= k:
        return nx.betweenness_centrality(G, normalized=True)
    return nx.betweenness_centrality(G, k=k, normalized=True, seed=42)


# ---------------------------------------------------------------------------
# GW statistics (Snijders et al.)
# ---------------------------------------------------------------------------
def gw_idegree(G: nx.Graph, alpha: float = 1.0) -> float:
    """GWIDegree (AltInStar): geometrically-weighted degree sum."""
    degs = np.array([d for _, d in G.degree()], dtype=float)
    return float(np.sum(np.exp(-alpha * degs)))


def gw_odegree(G: nx.Graph, alpha: float = 1.0) -> float:
    """GWODegree (AltOutStar): same as GWIDegree for undirected graphs."""
    return gw_idegree(G, alpha)


def gw_esp(G: nx.Graph, alpha: float = 2.0) -> float:
    """GWESP (AltKTriangleT): geometrically-weighted edgewise shared partners."""
    esp_counts: dict[int, int] = defaultdict(int)
    for u, v in G.edges():
        shared = len(set(G.neighbors(u)) & set(G.neighbors(v)))
        esp_counts[shared] += 1
    return float(sum(cnt * math.exp(-alpha * k) for k, cnt in esp_counts.items()))


def gw_dsp(G: nx.Graph, alpha: float = 2.0) -> float:
    """GWDSP (AltTwoPathsTD): geometrically-weighted dyadwise shared partners
    (approximation over non-edge pairs sharing at least one common neighbor)."""
    dsp_counts: dict[tuple, int] = defaultdict(int)
    for v in G.nodes():
        nbrs = list(G.neighbors(v))
        for i in range(len(nbrs)):
            for j in range(i + 1, len(nbrs)):
                u, w = nbrs[i], nbrs[j]
                if not G.has_edge(u, w):
                    dsp_counts[(min(u, w), max(u, w))] += 1
    counts: dict[int, int] = defaultdict(int)
    for cnt in dsp_counts.values():
        counts[cnt] += 1
    return float(sum(c * math.exp(-alpha * k) for k, c in counts.items()))


# ---------------------------------------------------------------------------
# Degree distribution helpers
# ---------------------------------------------------------------------------
def degree_arrays(G: nx.Graph) -> np.ndarray:
    return np.array([d for _, d in G.degree()], dtype=float)


def ccdf(degs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    vals = np.sort(np.unique(degs))
    n = len(degs)
    prob = np.array([np.sum(degs >= v) / n for v in vals])
    return vals, prob


# ---------------------------------------------------------------------------
# Subgraph for visualization
# ---------------------------------------------------------------------------
def focus_subgraph(G: nx.Graph, top_n: int = 300) -> nx.Graph:
    deg = dict(G.degree())
    top  = sorted(deg, key=deg.get, reverse=True)[:top_n]
    nbrs: set[int] = set()
    for n in top:
        nbrs.update(G.neighbors(n))
    return G.subgraph(sorted(set(top) | nbrs)).copy()


# ---------------------------------------------------------------------------
# Figure 1 -- Network topology overview  (Eq.9, Eq.10)
# ---------------------------------------------------------------------------
def fig1_network_topology(
    G: nx.Graph,
    out_path: Path,
    top_n: int = 300,
) -> None:
    """
    Network visualization with node color = primary class,
    node size proportional to degree, annotated with Eq.(9) and Eq.(10).
    """
    SG  = focus_subgraph(G, top_n)
    pos = nx.spring_layout(SG, seed=42, weight=None,
                           k=0.35, iterations=max(30, min(80, 8000 // max(SG.number_of_nodes(), 1))))
    T = eq9_transitivity(SG)
    D = eq10_density(SG)
    N = SG.number_of_nodes()
    M = SG.number_of_edges()

    fig, ax = plt.subplots(figsize=(9, 8))
    ax.set_aspect("equal")
    ax.axis("off")

    # Edges
    edge_x, edge_y = [], []
    for u, v in SG.edges():
        x0, y0 = pos[u]; x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]
    ax.plot(edge_x, edge_y, lw=0.25, color="#BBBBBB", zorder=1, solid_capstyle="round")

    # Nodes -- per class for legend
    deg = dict(SG.degree())
    max_d = max(deg.values()) if deg else 1
    patch_handles = []
    present = {SG.nodes[n].get("primary_class", "Unknown") for n in SG.nodes()}
    for cls in ALL_CLASSES:
        if cls not in present:
            continue
        xs, ys, sizes = [], [], []
        for n in SG.nodes():
            if SG.nodes[n].get("primary_class", "Unknown") != cls:
                continue
            x, y = pos[n]
            xs.append(x); ys.append(y)
            sizes.append(20 + 120 * (deg.get(n, 0) / max_d) ** 0.6)
        ax.scatter(xs, ys, s=sizes, color=cls_color(cls),
                   edgecolors="white", linewidths=0.3, zorder=2, alpha=0.88)
        patch_handles.append(
            mpatches.Patch(color=cls_color(cls),
                           label=f"{cls}  {CLASS_NAMES.get(cls, '')}")
        )

    # Node size scale legend
    ref_degs = sorted({1, max(2, max_d // 4), max(4, max_d // 2), max_d})
    size_handles = [
        plt.scatter([], [],
                    s=20 + 120 * (v / max_d) ** 0.6,
                    color="#555555", edgecolors="white", linewidths=0.3,
                    label=f"$k$ = {v:,}")
        for v in ref_degs
    ]

    leg1 = ax.legend(handles=patch_handles, loc="lower left",
                     fontsize=6.5, ncol=3, framealpha=0.88,
                     title="Primary D-class", title_fontsize=7,
                     bbox_to_anchor=(0, 0), borderpad=0.5,
                     markerscale=0.75)
    ax.add_artist(leg1)

    leg2 = ax.legend(handles=size_handles, loc="lower right",
                     fontsize=7, title="Node size (degree)", title_fontsize=7.5,
                     framealpha=0.88, scatterpoints=1, borderpad=0.6)
    ax.add_artist(leg2)

    # Metric annotation box
    eq_text = (
        r"$\mathbf{Network\ Metrics\ (Eqs.\ 9\text{-}10)}$" + "\n"
        r"$T = \frac{3\times\#\mathrm{triangles}}{\#\mathrm{conn.\ triples}}$"
        + f" $= {T:.4f}$\n"
        r"$D = \frac{|E|}{|V|(|V|-1)}$"
        + f" $= {D:.2e}$\n"
        f"$|V|$ = {N:,},  $|E|$ = {M:,}"
    )
    ax.text(0.98, 0.98, eq_text, transform=ax.transAxes,
            va="top", ha="right", fontsize=8.5,
            bbox=dict(boxstyle="round,pad=0.5", fc="white", ec="#AAAAAA", alpha=0.93))

    fig.suptitle(
        "USPTO Design Patent Co-citation Network\n"
        r"Node color: primary D-class  $|$  Node size $\propto$ degree  $|$  "
        f"Focus subgraph: top-{top_n} nodes + 1-hop neighbors",
        fontsize=9, y=1.0)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig1] -> {out_path}")


# ---------------------------------------------------------------------------
# Figure 2 -- ERGM sufficient statistics  (Eq.1-8)
# ---------------------------------------------------------------------------
def fig2_ergm_statistics(
    G: nx.Graph,
    arcs: list,
    edges: list,
    attrs: pd.DataFrame,
    out_path: Path,
) -> None:
    """Six-panel figure showing all ERGM statistics from Chakraborty et al. Eqs. 1-8."""
    node_class = {i: G.nodes[i].get("primary_class", "Unknown") for i in G.nodes()}

    # Parse dates for Eq.(7)
    node_date: dict = {}
    if "date" in attrs.columns:
        for i, row in attrs.iterrows():
            try:
                node_date[i] = pd.to_datetime(row["date"])
            except Exception:
                pass

    g_L   = eq2_arc_stat(arcs)
    g_s   = eq4_sender_effect(arcs, node_class)
    g_r   = eq5_receiver_effect(arcs, node_class)
    T     = eq9_transitivity(G)
    D     = eq10_density(G)
    fw    = eq7_date_guard(arcs, node_date)

    cls_list = [c for c in ALL_CLASSES if c in set(node_class.values())]
    homo_mat = eq6_homophily(edges, node_class, cls_list)
    g_homo   = int(np.trace(homo_mat))

    n_classes_arr = (
        attrs["n_classes"].dropna().astype(int).values
        if "n_classes" in attrs.columns else np.array([])
    )
    pct_multi = float((n_classes_arr > 1).mean() * 100) if len(n_classes_arr) else 0.0

    fig = plt.figure(figsize=(11, 6))
    gs  = gridspec.GridSpec(2, 3, figure=fig, hspace=0.55, wspace=0.38)

    # --- Panel A: ERGM formula (Eq.1) ---
    ax0 = fig.add_subplot(gs[0, 0])
    ax0.axis("off")
    eq1_str = (
        r"$\mathbf{ERGM\ (Eq.\ 1)}$" + "\n\n"
        r"$\pi(x)=\frac{\exp\!\left(\sum_{s}\theta_s g_s(x)\right)}{Z(\theta)}$"
        + "\n\n"
        r"$g_L(x) = \sum_{i,j} x_{ij}$" + f"  $= {g_L:,}$  (Eq. 2)\n"
        r"$g_\mathrm{send}=\sum_{i,j}a_i x_{ij}$" + "  (Eq. 4)\n"
        r"$g_\mathrm{rec} =\sum_{i,j}a_j x_{ij}$" + "  (Eq. 5)\n"
        r"$g_\mathrm{homo}=\sum_{i,j}\delta_{a_i,a_j}x_{ij}$"
        + f"$= {g_homo:,}$  (Eq. 6)\n"
        r"$g_\mathrm{date}=\sum_{i,j}H(d_j\!-\!d_i)x_{ij}$"
        + f"$= {fw:,}$  (Eq. 7)"
    )
    ax0.text(0.05, 0.95, eq1_str, transform=ax0.transAxes,
             va="top", ha="left", fontsize=8.5,
             bbox=dict(boxstyle="round,pad=0.5", fc="#F7F9FF", ec="#AABBD0", alpha=0.97))
    ax0.set_title("(A) ERGM Sufficient Statistics", fontsize=9, pad=4)

    # --- Panel B: Sender effect per class (Eq.4) ---
    ax1 = fig.add_subplot(gs[0, 1])
    vals_s = [g_s.get(c, 0) for c in cls_list]
    ax1.bar(range(len(cls_list)), vals_s,
            color=[cls_color(c) for c in cls_list],
            edgecolor="white", linewidth=0.2)
    ax1.set_xticks(range(len(cls_list)))
    ax1.set_xticklabels(cls_list, rotation=90, fontsize=6.5)
    ax1.set_ylabel(r"$g_\mathrm{send}(x;a)$", fontsize=8)
    ax1.set_title(r"(B) Sender Effect $g_\mathrm{send}$ (Eq. 4)", fontsize=9, pad=4)
    ax1.yaxis.set_major_formatter(
        FuncFormatter(lambda x, _: f"{x/1000:.0f}k" if x >= 1000 else f"{int(x)}"))

    # --- Panel C: Receiver effect per class (Eq.5) ---
    ax2 = fig.add_subplot(gs[0, 2])
    vals_r = [g_r.get(c, 0) for c in cls_list]
    ax2.bar(range(len(cls_list)), vals_r,
            color=[cls_color(c) for c in cls_list],
            edgecolor="white", linewidth=0.2)
    ax2.set_xticks(range(len(cls_list)))
    ax2.set_xticklabels(cls_list, rotation=90, fontsize=6.5)
    ax2.set_ylabel(r"$g_\mathrm{rec}(x;a)$", fontsize=8)
    ax2.set_title(r"(C) Receiver Effect $g_\mathrm{rec}$ (Eq. 5)", fontsize=9, pad=4)
    ax2.yaxis.set_major_formatter(
        FuncFormatter(lambda x, _: f"{x/1000:.0f}k" if x >= 1000 else f"{int(x)}"))

    # --- Panel D: Sender vs. Receiver scatter ---
    ax3 = fig.add_subplot(gs[1, 0])
    p75_s = float(np.percentile(vals_s, 75)) if vals_s else 0
    p75_r = float(np.percentile(vals_r, 75)) if vals_r else 0
    for c in cls_list:
        ax3.scatter(g_s.get(c, 0), g_r.get(c, 0),
                    color=cls_color(c), s=30,
                    edgecolors="white", linewidths=0.3, zorder=3, alpha=0.9)
        if g_s.get(c, 0) > p75_s or g_r.get(c, 0) > p75_r:
            ax3.annotate(c, (g_s.get(c, 0), g_r.get(c, 0)),
                         fontsize=6.5, ha="left", va="bottom", color="#333")
    lim = max(ax3.get_xlim()[1], ax3.get_ylim()[1])
    ax3.plot([0, lim], [0, lim], "k--", lw=0.7, alpha=0.5, label="Send = Receive")
    ax3.set_xlabel(r"$g_\mathrm{send}$ (Eq. 4)", fontsize=8)
    ax3.set_ylabel(r"$g_\mathrm{rec}$ (Eq. 5)", fontsize=8)
    ax3.set_title("(D) Sender vs. Receiver Effect", fontsize=9, pad=4)
    ax3.legend(fontsize=7)

    # --- Panel E: Key parameters summary ---
    ax4 = fig.add_subplot(gs[1, 1])
    metrics = {
        r"$T$ (Eq.9)":        T,
        r"$D$ (Eq.10)":       D,
        r"$D\!\times\!10^6$": D * 1e6,
        r"Multi-class %":     pct_multi / 100,
        r"Homophily ratio":   g_homo / max(g_L, 1),
    }
    colors4 = ["#1f77b4", "#ff7f0e", "#ff7f0e", "#2ca02c", "#9467bd"]
    bars4 = ax4.bar(range(len(metrics)), list(metrics.values()),
                    color=colors4, edgecolor="white")
    ax4.set_xticks(range(len(metrics)))
    ax4.set_xticklabels(list(metrics.keys()), fontsize=7.5)
    for bar, val in zip(bars4, metrics.values()):
        ax4.text(bar.get_x() + bar.get_width() / 2, bar.get_height() * 1.02,
                 f"{val:.3g}", ha="center", va="bottom", fontsize=7)
    ax4.set_title("(E) Key Network Parameters", fontsize=9, pad=4)
    ax4.set_ylabel("Value", fontsize=8)

    # --- Panel F: Date guard distribution (Eq.7-8) ---
    ax5 = fig.add_subplot(gs[1, 2])
    if node_date:
        valid_arcs = [(i, j) for i, j in arcs if i in node_date and j in node_date]
        if valid_arcs:
            diff_days = [(node_date[j] - node_date[i]).days for i, j in valid_arcs]
            diff_arr  = np.array(diff_days, dtype=float)
            bins = np.linspace(diff_arr.min(), diff_arr.max(), 40)
            neg_bins = bins[bins <= 0]
            pos_bins = bins[bins > 0]
            if len(neg_bins) > 1:
                ax5.hist(diff_arr[diff_arr <= 0], bins=neg_bins,
                         color="#2ca02c", alpha=0.8, label=r"$H\!=\!0$: valid ($d_j\!\leq\!d_i$)")
            if len(pos_bins) > 1:
                ax5.hist(diff_arr[diff_arr > 0], bins=pos_bins,
                         color="#d62728", alpha=0.8, label=r"$H\!=\!1$: fwd ($d_j\!>\!d_i$)")
            ax5.axvline(0, color="black", lw=1.0, linestyle="--")
            ax5.set_xlabel(r"$d_j - d_i$ (days)", fontsize=8)
            ax5.set_ylabel("Arc count", fontsize=8)
            ax5.legend(fontsize=7)
        else:
            ax5.text(0.5, 0.5, "No valid\ndate arcs",
                     transform=ax5.transAxes, ha="center", va="center",
                     fontsize=9, color="grey")
    else:
        ax5.text(0.5, 0.5, "Date data\nnot available",
                 transform=ax5.transAxes, ha="center", va="center",
                 fontsize=9, color="grey")
    ax5.set_title(r"(F) Date Guard $H(d_j\!-\!d_i)$ (Eqs. 7-8)", fontsize=9, pad=4)

    fig.suptitle(
        "ERGM Sufficient Statistics -- Chakraborty et al. (2020) Eqs. 1-8",
        fontsize=10, fontweight="bold", y=1.01)
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig2] -> {out_path}")


# ---------------------------------------------------------------------------
# Figure 3 -- Degree & Betweenness distributions  (Eq.10, Eq.11)
# ---------------------------------------------------------------------------
def fig3_degree_distribution(
    G: nx.Graph,
    out_path: Path,
    bc_k: int = 500,
) -> None:
    """Three-panel figure: degree CCDF, betweenness CCDF, degree-betweenness scatter."""
    degs   = degree_arrays(G)
    bc     = eq11_betweenness(G, k=bc_k)
    bc_arr = np.array([bc.get(n, 0.0) for n in range(G.number_of_nodes())])

    deg_pos  = degs[degs > 0]
    vals_d, prob_d = ccdf(deg_pos)
    bc_pos   = bc_arr[bc_arr > 0]
    vals_bc, prob_bc = ccdf(bc_pos) if len(bc_pos) > 0 else (np.array([]), np.array([]))

    def powerlaw_fit(x: np.ndarray, y: np.ndarray):
        mask = y > 0
        if mask.sum() < 3:
            return None, None
        lx = np.log10(x[mask]); ly = np.log10(y[mask])
        m, b = np.polyfit(lx, ly, 1)
        return m, b

    gamma_d,  b_d  = powerlaw_fit(vals_d, prob_d)
    gamma_bc, b_bc = powerlaw_fit(vals_bc, prob_bc) if len(vals_bc) else (None, None)

    fig, axes = plt.subplots(1, 3, figsize=(12, 4.5))
    ax_deg, ax_bc, ax_scat = axes

    # Panel A: Degree CCDF
    ax_deg.loglog(vals_d, prob_d, "o", ms=3.5, color="#1f77b4",
                  alpha=0.75, label="CCDF  $P(K \geq k)$", zorder=3)
    if gamma_d is not None:
        xf = np.logspace(np.log10(vals_d.min()), np.log10(vals_d.max()), 80)
        ax_deg.loglog(xf, 10**b_d * xf**gamma_d, "--", color="#d62728", lw=1.2,
                      label=fr"Power-law  $\gamma = {gamma_d:.2f}$")
    D_val = eq10_density(G)
    ax_deg.set_xlabel(r"Degree $k$", fontsize=9)
    ax_deg.set_ylabel(r"$P(K \geq k)$", fontsize=9)
    ax_deg.set_title(
        r"(A) Degree CCDF  (Eq. 10)" + "\n"
        r"$D = |E|\,/\,(|V|(|V|-1))$", fontsize=9)
    ax_deg.legend(fontsize=8)
    ax_deg.text(0.97, 0.97, f"$D = {D_val:.2e}$",
                transform=ax_deg.transAxes, ha="right", va="top", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#AAA"))

    # Panel B: Betweenness CCDF
    if len(vals_bc) > 1:
        ax_bc.loglog(vals_bc, prob_bc, "s", ms=3.5, color="#ff7f0e",
                     alpha=0.75, label="CCDF  $P(G \geq g)$", zorder=3)
        if gamma_bc is not None:
            xf = np.logspace(np.log10(vals_bc.min()), np.log10(vals_bc.max()), 80)
            ax_bc.loglog(xf, 10**b_bc * xf**gamma_bc, "--", color="#9467bd", lw=1.2,
                         label=fr"Power-law  $\gamma = {gamma_bc:.2f}$")
    else:
        ax_bc.text(0.5, 0.5, "Insufficient data",
                   transform=ax_bc.transAxes, ha="center", va="center", color="grey")
    ax_bc.set_xlabel(r"Betweenness $g(v)$  (Eq. 11)", fontsize=9)
    ax_bc.set_ylabel(r"$P(G \geq g)$", fontsize=9)
    ax_bc.set_title(r"(B) Betweenness Centrality CCDF  (Eq. 11)", fontsize=9)
    ax_bc.legend(fontsize=8)

    # Panel C: Degree vs. Betweenness
    deg_arr  = np.array([degs[n] for n in G.nodes()])
    bc_all   = np.array([bc.get(n, 0.0) for n in G.nodes()])
    valid    = (deg_arr > 0) & (bc_all > 0)
    ax_scat.loglog(deg_arr[valid], bc_all[valid], ".", ms=2.5,
                   alpha=0.35, color="#2ca02c")
    ax_scat.set_xlabel(r"Degree $k$", fontsize=9)
    ax_scat.set_ylabel(r"Betweenness $g(v)$  (Eq. 11)", fontsize=9)
    ax_scat.set_title("(C) Degree vs. Betweenness", fontsize=9)
    if valid.sum() > 10:
        r_log = np.corrcoef(np.log10(deg_arr[valid]), np.log10(bc_all[valid]))[0, 1]
        ax_scat.text(0.05, 0.97, fr"$r_{{\log}} = {r_log:.3f}$",
                     transform=ax_scat.transAxes, va="top", fontsize=8,
                     bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#AAA"))

    fig.suptitle(
        r"Degree Distribution & Betweenness Centrality -- Eqs. 10-11",
        fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig3] -> {out_path}")


# ---------------------------------------------------------------------------
# Figure 4 -- Homophily heatmap  (Eq.6)
# ---------------------------------------------------------------------------
def fig4_homophily_heatmap(
    G: nx.Graph,
    edges: list,
    out_path: Path,
) -> None:
    """Two-panel heatmap: raw co-citation count and row-normalized fraction."""
    node_class  = {i: G.nodes[i].get("primary_class", "Unknown") for i in G.nodes()}
    cls_present = [c for c in ALL_CLASSES if c in set(node_class.values())]
    mat = eq6_homophily(edges, node_class, cls_present)

    row_sum = mat.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        mat_norm = np.where(row_sum > 0, mat / row_sum, 0.0)

    fig, (ax_raw, ax_norm) = plt.subplots(1, 2, figsize=(13, 6.5))

    # Panel A: raw count (log scale)
    im0 = ax_raw.imshow(np.log1p(mat), cmap="Blues", aspect="auto")
    ax_raw.set_xticks(range(len(cls_present)))
    ax_raw.set_xticklabels(cls_present, rotation=90, fontsize=7)
    ax_raw.set_yticks(range(len(cls_present)))
    ax_raw.set_yticklabels(cls_present, fontsize=7)
    plt.colorbar(im0, ax=ax_raw, shrink=0.75, label=r"$\log(1 + \mathrm{count})$")
    ax_raw.set_title(
        r"(A) $g_\mathrm{homo}(x)=\sum_{i,j}\delta(a_i,a_j)x_{ij}$  (Eq. 6)"
        "\nRaw co-citation count  [log scale]", fontsize=9)
    ax_raw.set_xlabel(r"D-class (target node $j$)", fontsize=8)
    ax_raw.set_ylabel(r"D-class (source node $i$)", fontsize=8)
    for k in range(len(cls_present)):
        ax_raw.add_patch(plt.Rectangle((k - 0.5, k - 0.5), 1, 1,
                                       fill=False, edgecolor="red", lw=1.2, zorder=3))

    # Panel B: row-normalized
    im1 = ax_norm.imshow(mat_norm, cmap="Oranges", aspect="auto", vmin=0, vmax=1)
    ax_norm.set_xticks(range(len(cls_present)))
    ax_norm.set_xticklabels(cls_present, rotation=90, fontsize=7)
    ax_norm.set_yticks(range(len(cls_present)))
    ax_norm.set_yticklabels(cls_present, fontsize=7)
    plt.colorbar(im1, ax=ax_norm, shrink=0.75, label="Row-normalized fraction")
    ax_norm.set_title(
        r"(B) Normalized homophily matrix" + "\n"
        r"$\hat{H}_{ij} = g_\mathrm{homo}\,/\,\mathrm{row\ sum}$  "
        "(diagonal = within-class rate)", fontsize=9)
    ax_norm.set_xlabel(r"D-class (target node $j$)", fontsize=8)
    ax_norm.set_ylabel(r"D-class (source node $i$)", fontsize=8)
    for k in range(len(cls_present)):
        ax_norm.add_patch(plt.Rectangle((k - 0.5, k - 0.5), 1, 1,
                                        fill=False, edgecolor="navy", lw=1.2, zorder=3))

    fig.suptitle(
        r"Homophily Matrix -- $g_\mathrm{homo}(x)=\sum_{i,j}\delta(a_i,a_j)x_{ij}$  (Eq. 6)"
        "\nDiagonal = same-class co-citations (within-class homophily)",
        fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig4] -> {out_path}")


# ---------------------------------------------------------------------------
# Figure 5 -- Sender / Receiver per class  (Eq.4, Eq.5)
# ---------------------------------------------------------------------------
def fig5_sender_receiver(
    G: nx.Graph,
    arcs: list,
    out_path: Path,
) -> None:
    """Two-panel bar chart: absolute and per-node-normalized send/receive effects."""
    node_class  = {i: G.nodes[i].get("primary_class", "Unknown") for i in G.nodes()}
    cls_present = [c for c in ALL_CLASSES if c in set(node_class.values())]
    g_s = eq4_sender_effect(arcs, node_class)
    g_r = eq5_receiver_effect(arcs, node_class)

    node_count: dict[str, int] = defaultdict(int)
    for c in node_class.values():
        node_count[c] += 1
    gs_norm = {c: g_s.get(c, 0) / max(node_count[c], 1) for c in cls_present}
    gr_norm = {c: g_r.get(c, 0) / max(node_count[c], 1) for c in cls_present}

    x = np.arange(len(cls_present))
    w = 0.38

    fig, (ax_abs, ax_norm) = plt.subplots(2, 1, figsize=(12, 8))

    # Panel A: absolute counts
    ax_abs.bar(x - w / 2, [g_s.get(c, 0) for c in cls_present], width=w,
               color=[cls_color(c) for c in cls_present],
               label=r"Sender $g_\mathrm{send}$ (Eq. 4)", edgecolor="white", alpha=0.9)
    ax_abs.bar(x + w / 2, [g_r.get(c, 0) for c in cls_present], width=w,
               color=[cls_color(c) for c in cls_present], hatch="//",
               label=r"Receiver $g_\mathrm{rec}$ (Eq. 5)", edgecolor="white", alpha=0.7)
    ax_abs.set_xticks(x)
    ax_abs.set_xticklabels(cls_present, rotation=90, fontsize=7)
    ax_abs.set_ylabel("Arc count", fontsize=8)
    ax_abs.set_title(
        r"(A) Absolute Sender $g_\mathrm{send}$ and Receiver $g_\mathrm{rec}$ Effects",
        fontsize=9)
    ax_abs.legend(fontsize=8)
    ax_abs.yaxis.set_major_formatter(
        FuncFormatter(lambda v, _: f"{v/1000:.0f}k" if v >= 1000 else str(int(v))))

    # Panel B: per-node normalized
    ax_norm.bar(x - w / 2, [gs_norm[c] for c in cls_present], width=w,
                color=[cls_color(c) for c in cls_present],
                label="Sender / node count", edgecolor="white", alpha=0.9)
    ax_norm.bar(x + w / 2, [gr_norm[c] for c in cls_present], width=w,
                color=[cls_color(c) for c in cls_present], hatch="//",
                label="Receiver / node count", edgecolor="white", alpha=0.7)
    ax_norm.set_xticks(x)
    ax_norm.set_xticklabels(
        [f"{c}\n{CLASS_NAMES.get(c,'')[:12]}" for c in cls_present],
        rotation=90, fontsize=6.5)
    ax_norm.set_ylabel("Arcs per node", fontsize=8)
    ax_norm.set_title(
        r"(B) Normalized Effects -- arcs per node  "
        "(higher = stronger sender/receiver tendency)", fontsize=9)
    ax_norm.legend(fontsize=8)

    fig.suptitle(
        r"Sender $g_\mathrm{send}=\sum_{i,j}a_i x_{ij}$ (Eq. 4)  and  "
        r"Receiver $g_\mathrm{rec}=\sum_{i,j}a_j x_{ij}$ (Eq. 5)  by D-class",
        fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig5] -> {out_path}")


# ---------------------------------------------------------------------------
# Figure 6 -- GW network statistics
# ---------------------------------------------------------------------------
def fig6_gw_statistics(G: nx.Graph, out_path: Path) -> None:
    """Four-panel figure showing GWIDegree, GWODegree, GWESP, GWDSP."""
    alphas = np.linspace(0.5, 4.0, 15)
    gw_id_v  = [gw_idegree(G, a) for a in alphas]
    gw_od_v  = [gw_odegree(G, a) for a in alphas]
    gw_esp_v = [gw_esp(G, a)     for a in alphas]

    print("    computing GWDSP (slow for large graphs)...")
    gw_dsp_val = gw_dsp(G, alpha=2.0)

    # ESP distribution at alpha=2
    esp_counts: dict[int, int] = defaultdict(int)
    for u, v in G.edges():
        shared = len(set(G.neighbors(u)) & set(G.neighbors(v)))
        esp_counts[shared] += 1
    esp_k   = sorted(esp_counts.keys())
    esp_freq = [esp_counts[k] for k in esp_k]

    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    (ax_gw, ax_esp_curve), (ax_esp_dist, ax_summary) = axes

    # Panel A: GWIDeg / GWODeg vs alpha
    ax_gw.plot(alphas, gw_id_v, "o-", color="#1f77b4", label="GWIDegree (AltInStar)",  ms=4)
    ax_gw.plot(alphas, gw_od_v, "s--", color="#ff7f0e", label="GWODegree (AltOutStar)", ms=4)
    ax_gw.set_xlabel(r"Decay parameter $\alpha$", fontsize=8)
    ax_gw.set_ylabel(r"$\sum_k e^{-\alpha k}$ count", fontsize=8)
    ax_gw.set_title(r"(A) GWIDegree & GWODegree vs. $\alpha$", fontsize=9)
    ax_gw.legend(fontsize=8)

    # Panel B: GWESP vs alpha
    ax_esp_curve.plot(alphas, gw_esp_v, "^-", color="#2ca02c",
                      label="GWESP (AltKTriangleT)", ms=4)
    ax_esp_curve.set_xlabel(r"Decay parameter $\alpha$", fontsize=8)
    ax_esp_curve.set_ylabel("GWESP value", fontsize=8)
    ax_esp_curve.set_title(r"(B) GWESP (AltKTriangleT) vs. $\alpha$", fontsize=9)
    ax_esp_curve.legend(fontsize=8)

    # Panel C: ESP distribution
    ax_esp_dist.bar(esp_k[:20], esp_freq[:20], color="#9467bd",
                    edgecolor="white", width=0.7)
    ax_esp_dist.set_xlabel("# shared partners (ESP)", fontsize=8)
    ax_esp_dist.set_ylabel("Edge count", fontsize=8)
    ax_esp_dist.set_title(
        "(C) Edgewise Shared Partner Distribution\n"
        r"AltKTriangleT: $\theta>0$ $\Rightarrow$ transitivity", fontsize=9)
    ax_esp_dist.set_yscale("log")
    T_val = eq9_transitivity(G)
    ax_esp_dist.text(0.97, 0.97, f"$T$ (Eq.9) $= {T_val:.4f}$",
                     transform=ax_esp_dist.transAxes, ha="right", va="top", fontsize=8,
                     bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#AAA"))

    # Panel D: Summary & interpretation
    ax_summary.axis("off")
    summary_text = (
        r"$\mathbf{GW\ Network\ Statistics\ Summary}$" + "\n\n"
        r"GWIDegree $(\alpha=2)$ $= $" + f"{gw_idegree(G, 2.0):.3e}\n"
        r"GWODegree $(\alpha=2)$ $= $" + f"{gw_odegree(G, 2.0):.3e}\n"
        r"GWESP $(\alpha=2)$ $= $"      + f"{gw_esp(G, 2.0):.3e}\n"
        r"GWDSP $(\alpha=2)$ $= $"      + f"{gw_dsp_val:.3e}\n\n"
        "Interpretation (Chakraborty et al. 2020, Table 7):\n"
        r"  $\theta_\mathrm{AltKTriT}>0$: transitivity (citation snowball)" + "\n"
        r"  $\theta_\mathrm{AltTwoPaths}<0$: triangles dominate open paths" + "\n"
        r"  $\theta_\mathrm{AltInStar}<0$: no strong preferential attachment"
    )
    ax_summary.text(0.05, 0.95, summary_text, transform=ax_summary.transAxes,
                    va="top", fontsize=8.5,
                    bbox=dict(boxstyle="round,pad=0.6", fc="#F7FFF7",
                              ec="#88BB88", alpha=0.95))
    ax_summary.set_title("(D) Summary & Interpretation", fontsize=9)

    fig.suptitle(
        "Geometrically-Weighted Network Statistics\n"
        "GWIDegree · GWODegree · GWESP (AltKTriangleT) · GWDSP (AltTwoPathsTD)",
        fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig6] -> {out_path}")


# ---------------------------------------------------------------------------
# Figure 7 -- Temporal citation bias  (Eq.7, Eq.8)
# ---------------------------------------------------------------------------
def fig7_date_guard(
    G: nx.Graph,
    arcs: list,
    attrs: pd.DataFrame,
    out_path: Path,
) -> None:
    """Three-panel figure on date guard statistics."""
    if "date" not in attrs.columns:
        print("  [Fig7] 'date' column missing -- skipping")
        return

    node_date: dict = {}
    for i, row in attrs.iterrows():
        try:
            node_date[i] = pd.to_datetime(row["date"])
        except Exception:
            pass

    valid = [(i, j) for i, j in arcs if i in node_date and j in node_date]
    if not valid:
        print("  [Fig7] no valid date arcs -- skipping")
        return

    diff_years = np.array([(node_date[j] - node_date[i]).days / 365.25
                           for i, j in valid], dtype=float)
    n_fwd   = int((diff_years > 0).sum())
    pct_fwd = 100 * n_fwd / max(len(diff_years), 1)

    fig, (ax_hist, ax_hfunc, ax_cumul) = plt.subplots(1, 3, figsize=(13, 4.5))

    # Panel A: histogram
    lo = max(float(diff_years.min()), -30)
    hi = min(float(diff_years.max()), 30)
    bins = np.linspace(lo, hi, 60)
    neg = bins[bins <= 0]; pos = bins[bins > 0]
    if len(neg) > 1:
        ax_hist.hist(diff_years[diff_years <= 0], bins=neg,
                     color="#1f77b4", alpha=0.85,
                     label=r"$H\!=\!0$: valid ($d_j\!\leq\!d_i$)")
    if len(pos) > 1:
        ax_hist.hist(diff_years[diff_years > 0], bins=pos,
                     color="#d62728", alpha=0.85,
                     label=r"$H\!=\!1$: forward ($d_j\!>\!d_i$)")
    ax_hist.axvline(0, color="black", lw=1.2, linestyle="--", label="$t=0$")
    ax_hist.set_xlabel(r"$(d_j - d_i)$ in years", fontsize=8)
    ax_hist.set_ylabel("Arc count", fontsize=8)
    ax_hist.set_title(
        "(A) Date Difference Distribution\n"
        r"$g_\mathrm{date}(x)=\sum_{i,j}H(d_j\!-\!d_i)x_{ij}$  (Eq. 7)", fontsize=9)
    ax_hist.legend(fontsize=7)
    ax_hist.text(0.97, 0.97,
                 f"Forward arcs: {pct_fwd:.1f}%\n($n={n_fwd:,}$ / {len(diff_years):,})",
                 transform=ax_hist.transAxes, ha="right", va="top", fontsize=8,
                 bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="#AAA"))

    # Panel B: step function H(y)
    y    = np.linspace(-3, 3, 300)
    H_y  = np.where(y > 0, 1, 0)
    ax_hfunc.step(y, H_y, color="#333333", lw=1.5, where="post")
    ax_hfunc.fill_between(y, 0, H_y, step="post", alpha=0.15, color="#d62728",
                           label=r"$H\!=\!1$ (forward, penalized)")
    ax_hfunc.fill_between(y, 0, 1 - H_y, step="post", alpha=0.15, color="#1f77b4",
                           label=r"$H\!=\!0$ (valid arc)")
    ax_hfunc.axvline(0, color="black", lw=1.0, linestyle="--")
    ax_hfunc.set_xlabel(r"$y = d_j - d_i$", fontsize=9)
    ax_hfunc.set_ylabel(r"$H(y)$", fontsize=9)
    ax_hfunc.set_ylim(-0.1, 1.25); ax_hfunc.set_yticks([0, 1])
    ax_hfunc.set_title(
        r"(B) Unit Step Function $H(y)$  (Eq. 8)" + "\n"
        r"$H(y)=0\ \mathrm{if}\ y\leq0$,  $\theta_\mathrm{date}=-10^{10}$", fontsize=9)
    ax_hfunc.legend(fontsize=7)

    # Panel C: cumulative citation age gap
    yr_fwd = np.sort(diff_years[diff_years > 0])
    yr_bkw = np.sort(-diff_years[diff_years <= 0])
    if len(yr_fwd) > 1:
        ax_cumul.plot(yr_fwd, np.arange(1, len(yr_fwd) + 1) / len(yr_fwd),
                      color="#d62728", lw=1.3, label="Forward arcs CDF")
    if len(yr_bkw) > 1:
        ax_cumul.plot(yr_bkw, np.arange(1, len(yr_bkw) + 1) / len(yr_bkw),
                      color="#1f77b4", lw=1.3, label=r"$|$backward$|$ arcs CDF")
    ax_cumul.set_xlabel("Citation age gap |years|", fontsize=8)
    ax_cumul.set_ylabel("Cumulative fraction", fontsize=8)
    ax_cumul.set_title(
        "(C) Citation Age Gap CDF\n(backward = expected; forward = anomaly)", fontsize=9)
    ax_cumul.legend(fontsize=7)

    fig.suptitle(
        r"Date Guard Statistic -- $g_\mathrm{date}(x)=\sum_{i,j}H(d_j\!-\!d_i)x_{ij}$"
        r"  with $\theta_\mathrm{date}=-10^{10}$  (Eqs. 7-8)",
        fontsize=10, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig7] -> {out_path}")


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
def export_csv(
    G: nx.Graph,
    arcs: list,
    edges: list,
    attrs: pd.DataFrame,
    out_path: Path,
) -> None:
    node_class  = {i: G.nodes[i].get("primary_class", "Unknown") for i in G.nodes()}
    cls_present = [c for c in ALL_CLASSES if c in set(node_class.values())]
    g_s      = eq4_sender_effect(arcs, node_class)
    g_r      = eq5_receiver_effect(arcs, node_class)
    homo_mat = eq6_homophily(edges, node_class, cls_present)
    degs     = degree_arrays(G)
    bc       = eq11_betweenness(G, k=300)
    bc_arr   = np.array([bc.get(i, 0.0) for i in range(len(degs))])

    rows = [
        {"statistic": "g_L (Eq.2)",             "value": eq2_arc_stat(arcs),          "equation": "2"},
        {"statistic": "g_homo sum (Eq.6)",       "value": int(np.trace(homo_mat)),     "equation": "6"},
        {"statistic": "Transitivity T (Eq.9)",   "value": eq9_transitivity(G),         "equation": "9"},
        {"statistic": "Density D (Eq.10)",       "value": eq10_density(G),             "equation": "10"},
        {"statistic": "N nodes",                 "value": G.number_of_nodes(),         "equation": "-"},
        {"statistic": "M edges (undirected)",    "value": G.number_of_edges(),         "equation": "-"},
        {"statistic": "mean degree",             "value": float(degs.mean()),          "equation": "-"},
        {"statistic": "max degree",              "value": int(degs.max()),             "equation": "-"},
        {"statistic": "mean betweenness (Eq.11)","value": float(bc_arr.mean()),        "equation": "11"},
        {"statistic": "GWIDegree (alpha=2)",     "value": gw_idegree(G, 2.0),         "equation": "Snijders"},
        {"statistic": "GWESP (alpha=2)",         "value": gw_esp(G, 2.0),             "equation": "Snijders"},
    ]
    for c in cls_present:
        rows.append({"statistic": f"g_send[{c}] (Eq.4)", "value": g_s.get(c, 0), "equation": "4"})
        rows.append({"statistic": f"g_rec[{c}] (Eq.5)",  "value": g_r.get(c, 0), "equation": "5"})

    pd.DataFrame(rows).to_csv(out_path, index=False)
    print(f"  [CSV]  -> {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Visualize USPTO design patent co-citation network\n"
            "implementing all equations from Chakraborty et al. (2020)"
        )
    )
    parser.add_argument("--ergm-dir", default="ergm_input",
                        help="build_ergm_input.py output directory (default: ergm_input)")
    parser.add_argument("--out-dir",  default="output",
                        help="Output directory (default: output)")
    parser.add_argument("--top-n",   type=int, default=300,
                        help="Top-N nodes by degree for topology figure (default: 300)")
    parser.add_argument("--bc-k",    type=int, default=500,
                        help="Betweenness approximation sample size -- Eq.(11) (default: 500)")
    parser.add_argument("--no-fig1", action="store_true",
                        help="Skip fig1 (network topology)")
    parser.add_argument("--no-fig6", action="store_true",
                        help="Skip fig6 (GW statistics -- slow for large graphs)")
    args = parser.parse_args()

    ergm_dir = Path(args.ergm_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    attr_path = ergm_dir / "attributes.txt"
    arc_path  = ergm_dir / "arc_list.txt"
    if not attr_path.exists() or not arc_path.exists():
        print(f"ERROR: {attr_path} or {arc_path} not found.", file=sys.stderr)
        sys.exit(1)

    print("Loading attributes...")
    attrs = load_attrs(attr_path)
    print(f"  {len(attrs):,} nodes")

    print("Loading arc list...")
    arcs  = load_arc_list(arc_path)
    edges = arcs_to_undirected(arcs)
    print(f"  {len(arcs):,} arcs -> {len(edges):,} undirected edges")

    G = build_networkx(len(attrs), edges)
    attach_attrs(G, attrs)

    print("\nGenerating figures...")

    if not args.no_fig1:
        fig1_network_topology(G, out_dir / "fig1_network_topology.png", args.top_n)

    fig2_ergm_statistics(G, arcs, edges, attrs, out_dir / "fig2_ergm_statistics.png")
    fig3_degree_distribution(G, out_dir / "fig3_degree_distribution.png", args.bc_k)
    fig4_homophily_heatmap(G, edges, out_dir / "fig4_homophily_heatmap.png")
    fig5_sender_receiver(G, arcs, out_dir / "fig5_sender_receiver.png")

    if not args.no_fig6:
        fig6_gw_statistics(G, out_dir / "fig6_gw_statistics.png")

    fig7_date_guard(G, arcs, attrs, out_dir / "fig7_date_guard.png")
    export_csv(G, arcs, edges, attrs, out_dir / "ergm_statistics.csv")

    print(f"\nDone. Output -> {out_dir}/")
    print("  fig1_network_topology.png   Eq.(9)(10)  network layout + metrics")
    print("  fig2_ergm_statistics.png    Eq.(1-8)    all ERGM statistics")
    print("  fig3_degree_distribution.png Eq.(10)(11) degree + betweenness CCDF")
    print("  fig4_homophily_heatmap.png  Eq.(6)      delta(a_i,a_j) 35x35 matrix")
    print("  fig5_sender_receiver.png    Eq.(4)(5)   per-class sender/receiver")
    print("  fig6_gw_statistics.png      GWIDeg / GWODeg / GWESP / GWDSP")
    print("  fig7_date_guard.png         Eq.(7)(8)   temporal citation bias")
    print("  ergm_statistics.csv         all computed statistics")


if __name__ == "__main__":
    main()