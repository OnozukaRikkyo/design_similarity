#!/usr/bin/env python3
"""
USPTO Design Patent Co-citation Network Visualizer  v4
=======================================================
* All figures are exported as single panels (1 plot per file).
* Tables are exported as LaTeX (.tex) files.
* Figure 1 uses Kamada-Kawai layout and hollow nodes.
* Figure 8 shows ERGM coefficients read from a CSV (or watermarked dummy).
* --estimate-ergm runs Robbins-Monro MCMLE and writes ergm_results.csv.
"""

import argparse
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
import networkx as nx

# ─────────────────────────────────────────────────────────────────────
# Global constants
# ─────────────────────────────────────────────────────────────────────
FIG_SIZE = (7, 6)
FIG_DPI  = 300

ALL_CLASSES = [f"D{i}" for i in range(1, 35)] + ["D99"]
CLASS_NAMES = {
    "D1":  "Edible Prods.",    "D2":  "Apparel",         "D3":  "Travel Goods",
    "D4":  "Brushware",        "D5":  "Textile",          "D6":  "Furnishings",
    "D7":  "Food Equip.",      "D8":  "Tools/Hardware",   "D9":  "Tools (misc)",
    "D10": "Measuring Dev.",   "D11": "Jewelry",          "D12": "Transportation",
    "D13": "Prod. Equip.",     "D14": "Rec./Comm./Info.", "D15": "Machines",
    "D16": "Photography",      "D17": "Musical Instr.",   "D18": "Printing/Office",
    "D19": "Office Suppl.",    "D20": "Sales/Advert.",    "D21": "Amusement Dev.",
    "D22": "Arms/Pyro.",       "D23": "Heating/Cooling",  "D24": "Medical/Lab",
    "D25": "Building/Constr.", "D26": "Lighting",         "D27": "Tobacco",
    "D28": "Pharma/Cosmet.",   "D29": "Animal Husb.",     "D30": "Outdoor/Garden",
    "D31": "Articles Mfg.",    "D32": "Washing/Clean.",   "D33": "Food/Bev Svc.",
    "D34": "Material Hdl.",    "D99": "Misc.",
}

PLT_STYLE = {
    "figure.facecolor":   "white",
    "axes.facecolor":     "white",
    "axes.edgecolor":     "#222222",
    "axes.linewidth":     0.9,
    "axes.grid":          True,
    "grid.color":         "#DDDDDD",
    "grid.linewidth":     0.5,
    "grid.alpha":         0.7,
    "font.family":        "DejaVu Sans",
    "font.size":          10,
    "axes.labelsize":     10,
    "axes.titlesize":     11,
    "xtick.labelsize":    9,
    "ytick.labelsize":    9,
    "legend.fontsize":    9,
    "legend.framealpha":  0.88,
    "lines.linewidth":    1.4,
    "savefig.dpi":        FIG_DPI,
    "savefig.bbox":       "tight",
    "savefig.pad_inches": 0.08,
}
matplotlib.rcParams.update(PLT_STYLE)

CMAP_CLASS = matplotlib.colormaps.get_cmap("tab20").resampled(35)


def cls_color(c: str):
    idx = ALL_CLASSES.index(c) if c in ALL_CLASSES else 34
    return CMAP_CLASS(idx / 34)


def infobox(ax, lines: list, loc: str = "upper right",
            fc: str = "#F7F9FF", ec: str = "#AABBD0"):
    text = "\n".join(lines)
    locs = {
        "upper right": (0.97, 0.97, "right",  "top"),
        "upper left":  (0.03, 0.97, "left",   "top"),
        "lower right": (0.97, 0.03, "right",  "bottom"),
        "lower left":  (0.03, 0.03, "left",   "bottom"),
    }
    x, y, ha, va = locs.get(loc, locs["upper right"])
    ax.text(x, y, text, transform=ax.transAxes,
            ha=ha, va=va, fontsize=9,
            bbox=dict(boxstyle="round,pad=0.45", fc=fc, ec=ec, alpha=0.93))

# ─────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────
def load_attrs(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep="\t", low_memory=False)

def load_arc_list(path: Path) -> list:
    arcs = []
    with open(path) as f:
        for line in f:
            p = line.strip().split()
            if len(p) == 2:
                arcs.append((int(p[0]), int(p[1])))
    return arcs

def arcs_to_undirected(arcs: list) -> list:
    s = set()
    for u, v in arcs:
        if u != v:
            s.add((min(u, v), max(u, v)))
    return list(s)

def build_graph(n_nodes: int, edges: list) -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(range(n_nodes))
    G.add_edges_from(edges)
    return G

def attach_attrs(G: nx.Graph, attrs: pd.DataFrame) -> None:
    for i in G.nodes():
        if i >= len(attrs):
            G.nodes[i]["primary_class"] = "Unknown"
            G.nodes[i]["n_classes"] = 0
            G.nodes[i]["date"] = ""
        else:
            row = attrs.iloc[i]
            G.nodes[i]["primary_class"] = str(row.get("primary_class", "Unknown"))
            nc = row.get("n_classes", 0)
            G.nodes[i]["n_classes"] = int(nc) if pd.notna(nc) else 0
            G.nodes[i]["date"] = str(row.get("date", ""))

# ─────────────────────────────────────────────────────────────────────
# Network statistics
# ─────────────────────────────────────────────────────────────────────
def eq2_arc_stat(arcs): return len(arcs)

def eq4_sender_effect(arcs, node_class):
    cnt = defaultdict(int)
    for i, j in arcs:
        cnt[node_class.get(i, "Unknown")] += 1
    return cnt

def eq5_receiver_effect(arcs, node_class):
    cnt = defaultdict(int)
    for i, j in arcs:
        cnt[node_class.get(j, "Unknown")] += 1
    return cnt

def eq6_homophily(edges, node_class, cls_list):
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

def eq7_date_guard(arcs, node_date):
    violations = 0
    for i, j in arcs:
        di = node_date.get(i)
        dj = node_date.get(j)
        if di is not None and dj is not None:
            if (dj - di).days > 0:
                violations += 1
    return violations

def eq9_transitivity(G): return nx.transitivity(G)

def eq10_density(G):
    N, M = G.number_of_nodes(), G.number_of_edges()
    return M / (N * (N - 1)) if N >= 2 else 0.0

def eq11_betweenness(G, k=500):
    N = G.number_of_nodes()
    if N <= k:
        return nx.betweenness_centrality(G, normalized=True)
    return nx.betweenness_centrality(G, k=k, normalized=True, seed=42)

def gw_idegree(G, alpha=1.0):
    return float(np.sum(np.exp(-alpha * np.array([d for _, d in G.degree()]))))

def gw_odegree(G, alpha=1.0): return gw_idegree(G, alpha)

def gw_esp(G, alpha=2.0):
    esp_counts = defaultdict(int)
    for u, v in G.edges():
        shared = len(set(G.neighbors(u)) & set(G.neighbors(v)))
        esp_counts[shared] += 1
    return sum(cnt * math.exp(-alpha * k) for k, cnt in esp_counts.items())

def gw_dsp(G, alpha=2.0):
    dsp_raw = defaultdict(int)
    for v in G.nodes():
        nbrs = list(G.neighbors(v))
        for i in range(len(nbrs)):
            for j in range(i + 1, len(nbrs)):
                u, w = nbrs[i], nbrs[j]
                if not G.has_edge(u, w):
                    dsp_raw[(min(u, w), max(u, w))] += 1
    counts = defaultdict(int)
    for cnt in dsp_raw.values():
        counts[cnt] += 1
    return sum(c * math.exp(-alpha * k) for k, c in counts.items())

def degree_arrays(G):
    return np.array([d for _, d in G.degree()])

def ccdf(degs):
    vals = np.sort(np.unique(degs))
    n = len(degs)
    prob = np.array([np.sum(degs >= v) / n for v in vals])
    return vals, prob

def powerlaw_fit(x, y):
    mask = y > 0
    lx, ly = np.log10(x[mask]), np.log10(y[mask])
    if len(lx) < 5:
        return None, None
    m, b = np.polyfit(lx, ly, 1)
    return m, b

def focus_subgraph(G, top_n=300):
    deg = dict(G.degree())
    top = set(sorted(deg, key=deg.get, reverse=True)[:top_n])
    nbrs = set()
    for n in top:
        nbrs.update(G.neighbors(n))
    return G.subgraph(sorted(top | nbrs)).copy()

# ─────────────────────────────────────────────────────────────────────
# MCMC ERGM estimation (Robbins-Monro MCMLE)
# ─────────────────────────────────────────────────────────────────────

def _rand_pair(rng: np.random.Generator, n: int):
    """Sample a uniformly random unordered pair (i, j) with i != j."""
    i = int(rng.integers(n))
    j = int(rng.integers(n - 1))
    if j >= i:
        j += 1
    return i, j


class _ERGMState:
    """
    Tracks sufficient statistics incrementally during Metropolis-Hastings
    so each step costs O(degree) instead of O(N^2).

    Statistics tracked (matching Chakraborty et al. 2020):
      [0] Arc count              (Eq.2)
      [1] Triangle count         (Eq.9 proxy / AltKTriT)
      [2] GWIDegree  alpha=log2  (AltInStars)
      [3] Same-class homophily   (Eq.6)
    """
    __slots__ = ("G", "nc", "alpha", "edges", "triangles", "gwideg", "homo")

    def __init__(self, G: nx.Graph, nc: dict, alpha: float):
        self.G         = G.copy()
        self.nc        = nc
        self.alpha     = alpha
        self.edges     = float(G.number_of_edges())
        self.triangles = float(sum(nx.triangles(G).values())) / 3.0
        degs           = np.fromiter((d for _, d in G.degree()), dtype=float,
                                     count=G.number_of_nodes())
        self.gwideg    = float(np.sum(np.exp(-alpha * degs)))
        self.homo      = float(sum(1 for u, v in G.edges()
                                   if nc.get(u, "") and nc.get(u, "") == nc.get(v, "")))

    @property
    def stats(self) -> np.ndarray:
        return np.array([self.edges, self.triangles, self.gwideg, self.homo])

    def try_toggle(self, u, v, theta: np.ndarray, rng: np.random.Generator) -> bool:
        """Propose toggling edge (u,v); accept with Metropolis probability."""
        adding = not self.G.has_edge(u, v)
        sign   = 1.0 if adding else -1.0
        nu, nv = set(self.G.neighbors(u)), set(self.G.neighbors(v))
        shared = float(len(nu & nv))
        du, dv = self.G.degree(u), self.G.degree(v)
        dg     = 1 if adding else -1
        d_gwideg = (math.exp(-self.alpha * (du + dg)) - math.exp(-self.alpha * du) +
                    math.exp(-self.alpha * (dv + dg)) - math.exp(-self.alpha * dv))
        cu, cv   = self.nc.get(u, ""), self.nc.get(v, "")
        d_homo   = sign * float(bool(cu) and cu == cv)
        delta    = np.array([sign, sign * shared, d_gwideg, d_homo])
        log_acc  = float(theta @ delta)
        if log_acc >= 0.0 or rng.random() < math.exp(log_acc):
            self.edges     += sign
            self.triangles += sign * shared
            self.gwideg    += d_gwideg
            self.homo      += d_homo
            if adding:
                self.G.add_edge(u, v)
            else:
                self.G.remove_edge(u, v)
            return True
        return False


def estimate_ergm_mcmc(
    G: nx.Graph,
    node_class_dict: dict,
    subgraph_size: int = 500,
    n_outer: int = 40,
    n_mcmc: int = 300,
    burnin: int = 150,
    alpha: float = math.log(2),
    seed: int = 42,
) -> pd.DataFrame:
    """
    Robbins-Monro MCMLE for a four-statistic ERGM on the largest-component
    induced subgraph of the top-degree nodes.

    Returns a DataFrame with columns:
        group, label, estimate, std_error
    suitable for feeding directly to fig8_ergm_coefficients().
    """
    rng = np.random.default_rng(seed)
    t0  = time.time()

    # Build tractable subgraph: top-degree nodes, largest component
    top_nodes = [n for n, _ in sorted(G.degree(), key=lambda x: x[1], reverse=True)
                 ][:subgraph_size]
    SG = G.subgraph(top_nodes).copy()
    SG.remove_nodes_from(list(nx.isolates(SG)))
    cc = max(nx.connected_components(SG), key=len)
    SG = SG.subgraph(cc).copy()
    nodes = list(SG.nodes())
    N     = len(nodes)
    nc    = {n: node_class_dict.get(n, "") for n in nodes}

    print(f"  ERGM subgraph: |V|={N}, |E|={SG.number_of_edges()}")

    g_obs   = _ERGMState(SG, nc, alpha).stats
    density = SG.number_of_edges() / max(N * (N - 1) / 2, 1)
    # Initialise theta from observed density (logit for arc term, 0 elsewhere)
    theta   = np.array([math.log(max(density, 1e-9) / max(1.0 - density, 1e-9)),
                        0.0, 0.0, 0.0])

    print(f"  Starting Robbins-Monro ({n_outer} outer iterations)...")
    for outer in range(n_outer):
        step  = 0.18 / (outer + 1) ** 0.6
        state = _ERGMState(SG, nc, alpha)
        # Burn-in
        for _ in range(burnin):
            i, j = _rand_pair(rng, N)
            state.try_toggle(nodes[i], nodes[j], theta, rng)
        # Collect samples to estimate E_theta[g]
        samples = np.empty((n_mcmc, 4))
        for k in range(n_mcmc):
            i, j = _rand_pair(rng, N)
            state.try_toggle(nodes[i], nodes[j], theta, rng)
            samples[k] = state.stats
        g_mean = samples.mean(axis=0)
        theta  = theta + step * (g_obs - g_mean)
        elapsed = time.time() - t0
        print(f"    iter {outer+1:2d}/{n_outer}  theta={np.round(theta,3)}  "
              f"g_mean~g_obs diff={np.round(g_obs-g_mean,1)}  t={elapsed:.1f}s")

    # Estimate standard errors via Fisher information = Cov_theta[g(X)]
    print("  Estimating standard errors via Fisher information...")
    state_f = _ERGMState(SG, nc, alpha)
    n_se    = n_mcmc * 6
    for _ in range(burnin * 3):
        i, j = _rand_pair(rng, N)
        state_f.try_toggle(nodes[i], nodes[j], theta, rng)
    fin = np.empty((n_se, 4))
    for k in range(n_se):
        i, j = _rand_pair(rng, N)
        state_f.try_toggle(nodes[i], nodes[j], theta, rng)
        fin[k] = state_f.stats
    cov_g = np.cov(fin.T) + 1e-6 * np.eye(4)
    try:
        se = np.sqrt(np.abs(np.diag(np.linalg.inv(cov_g))))
    except np.linalg.LinAlgError:
        se = np.full(4, float("nan"))

    total = time.time() - t0
    print(f"  ERGM estimation done in {total:.1f}s")
    print(f"  theta = {np.round(theta, 4)}")
    print(f"  se    = {np.round(se, 4)}")

    return pd.DataFrame([
        {"group": "Network Structures",
         "label": "Arc Count (Eq.2 analog)",
         "estimate": float(theta[0]), "std_error": float(se[0])},
        {"group": "Network Structures",
         "label": "Triangles / Transitivity (AltKTriT proxy)",
         "estimate": float(theta[1]), "std_error": float(se[1])},
        {"group": "Network Structures",
         "label": "GWIDegree alpha=log(2) (AltInStars)",
         "estimate": float(theta[2]), "std_error": float(se[2])},
        {"group": "Homophily (D-Class)",
         "label": "Same Primary D-Class (Eq.6)",
         "estimate": float(theta[3]), "std_error": float(se[3])},
    ])

# ─────────────────────────────────────────────────────────────────────
# Fig 1 — Network topology (Physics Insight, Kamada-Kawai)
# ─────────────────────────────────────────────────────────────────────
def fig1_network_topology(G: nx.Graph, out_path: Path, top_n: int = 300) -> None:
    deg_dict   = dict(G.degree())
    core_nodes = sorted(deg_dict, key=deg_dict.get, reverse=True)[:top_n]
    SG = G.subgraph(core_nodes).copy()

    SG.remove_nodes_from(list(nx.isolates(SG)))

    if len(SG) > 0:
        largest_cc = max(nx.connected_components(SG), key=len)
        SG = SG.subgraph(largest_cc).copy()

    print("    Calculating Kamada-Kawai layout...")
    pos = nx.kamada_kawai_layout(SG)

    T = eq9_transitivity(SG)
    D = eq10_density(SG)
    N = SG.number_of_nodes()
    M = SG.number_of_edges()

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.set_aspect("equal")
    ax.axis("off")

    edge_x, edge_y = [], []
    for u, v in SG.edges():
        x0, y0 = pos[u]; x1, y1 = pos[v]
        edge_x += [x0, x1, None]; edge_y += [y0, y1, None]
    ax.plot(edge_x, edge_y, lw=0.8, color="black", alpha=0.5, zorder=1)

    deg    = dict(SG.degree())
    max_d  = max(deg.values()) if deg else 1

    xs_all, ys_all, sizes_all = [], [], []
    for n in SG.nodes():
        xs_all.append(pos[n][0])
        ys_all.append(pos[n][1])
        sizes_all.append(30 + 300 * (deg[n] / max_d))
    ax.scatter(xs_all, ys_all, s=sizes_all, facecolors="none", edgecolors="black",
               linewidths=1.5, zorder=2, alpha=0.85)

    ref_degs = sorted({1, max(2, max_d // 4), max(4, max_d // 2), max_d})
    size_handles = [plt.scatter([], [], s=30 + 300*(v/max_d),
                                facecolors="none", edgecolors="black", linewidths=1.5,
                                label=f"k = {v}") for v in ref_degs]
    ax.legend(handles=size_handles, loc="lower right",
              fontsize=9, title="Degree (node size)", frameon=False, scatterpoints=1)

    infobox(ax, [
        "Giant Component Topology",
        f"  Transitivity (Eq.9) T = {T:.4f}",
        f"  Density      (Eq.10) D = {D:.3e}",
        f"  |V| = {N:,}   |E| = {M:,}",
        f"  Max degree  = {max_d:,}",
    ], loc="upper left")

    ax.set_title("USPTO Design Patent Co-citation Core Topology\n"
                 "(Kamada-Kawai layout, hollow nodes scaled by degree)",
                 fontsize=12, fontweight="bold")
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    print(f"  [Fig1] -> {out_path}")

# ─────────────────────────────────────────────────────────────────────
# Fig 2 — ERGM sufficient statistics (Split & LaTeX)
# ─────────────────────────────────────────────────────────────────────
def fig2_ergm_statistics(G: nx.Graph, arcs, edges, attrs: pd.DataFrame, out_dir: Path) -> None:
    node_class  = {i: G.nodes[i].get("primary_class", "Unknown") for i in G.nodes()}
    cls_present = [c for c in ALL_CLASSES if c in set(node_class.values())]

    node_date = {}
    if "date" in attrs.columns:
        for i, row in attrs.iterrows():
            try:
                node_date[i] = pd.to_datetime(row["date"])
            except Exception:
                pass

    g_L      = eq2_arc_stat(arcs)
    g_s      = eq4_sender_effect(arcs, node_class)
    g_r      = eq5_receiver_effect(arcs, node_class)
    T        = eq9_transitivity(G)
    D        = eq10_density(G)
    fw       = eq7_date_guard(arcs, node_date)
    homo_mat = eq6_homophily(edges, node_class, cls_present)
    g_homo   = int(np.trace(homo_mat))

    n_cls_arr = attrs["n_classes"].dropna().astype(int).values if "n_classes" in attrs.columns else np.array([])
    pct_multi = float((n_cls_arr > 1).mean() * 100) if len(n_cls_arr) > 0 else 0.0

    vals_s = [g_s.get(c, 0) for c in cls_present]
    vals_r = [g_r.get(c, 0) for c in cls_present]
    x = np.arange(len(cls_present))

    # LaTeX Table
    tex_path = out_dir / "table_ergm_stats.tex"
    with open(tex_path, "w") as f:
        f.write("\\begin{table}[htbp]\n\\centering\n")
        f.write("\\caption{ERGM Sufficient Statistics Summary}\n")
        f.write("\\begin{tabular}{ll}\n\\hline\n")
        f.write("Statistic (Eq.) & Value \\\\\n\\hline\n")
        f.write(f"Arc count $g_L$ (Eq.2) & {g_L:,} \\\\\n")
        f.write(f"Transitivity $T$ (Eq.9) & {T:.5f} \\\\\n")
        f.write(f"Density $D$ (Eq.10) & {D:.3e} \\\\\n")
        f.write(f"Homophily sum (Eq.6) & {g_homo:,} \\\\\n")
        f.write(f"Forward arcs $H=1$ (Eq.7) & {fw:,} ({100*fw/max(g_L,1):.1f}\\%) \\\\\n")
        f.write(f"Multi-class patents & {pct_multi:.1f}\\% \\\\\n")
        f.write(f"$|V|$ nodes & {G.number_of_nodes():,} \\\\\n")
        f.write(f"|E| undirected edges & {G.number_of_edges():,} \\\\\n")
        f.write("\\hline\n\\end{tabular}\n\\end{table}\n")
    print(f"  [LaTeX] -> {tex_path}")

    # Sender Effect
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.bar(x, vals_s, color=[cls_color(c) for c in cls_present], edgecolor="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(cls_present, rotation=90, fontsize=8)
    ax.set_ylabel("Arc count  g_send  (Eq.4)")
    ax.set_title("Sender Effect per D-class [Eq.4]", fontsize=11, fontweight="bold")
    fig.tight_layout()
    p = out_dir / "fig2a_sender_effect.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig2a] -> {p}")

    # Receiver Effect
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.bar(x, vals_r, color=[cls_color(c) for c in cls_present], edgecolor="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(cls_present, rotation=90, fontsize=8)
    ax.set_ylabel("Arc count  g_rec  (Eq.5)")
    ax.set_title("Receiver Effect per D-class [Eq.5]", fontsize=11, fontweight="bold")
    fig.tight_layout()
    p = out_dir / "fig2b_receiver_effect.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig2b] -> {p}")

    # Scatter
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    for c in cls_present:
        ax.scatter(g_s.get(c, 0), g_r.get(c, 0),
                   color=cls_color(c), s=50, edgecolors="black", alpha=0.9)
    lim = max(max(vals_s, default=1), max(vals_r, default=1)) * 1.05
    ax.plot([0, lim], [0, lim], "k--", lw=1.0, alpha=0.6, label="g_send = g_rec")
    ax.set_xlabel("g_send (Eq.4)")
    ax.set_ylabel("g_rec (Eq.5)")
    ax.set_title("Sender vs. Receiver Effect by Class", fontsize=11, fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig2c_sender_vs_receiver.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig2c] -> {p}")

# ─────────────────────────────────────────────────────────────────────
# Fig 3 — Degree distribution + Betweenness (Split)
# ─────────────────────────────────────────────────────────────────────
def fig3_degree_distribution(G: nx.Graph, out_dir: Path, bc_k: int = 500) -> None:
    degs   = degree_arrays(G)
    bc     = eq11_betweenness(G, k=bc_k)
    bc_arr = np.array([bc.get(n, 0) for n in G.nodes()])

    deg_pos = degs[degs > 0]
    bc_pos  = bc_arr[bc_arr > 0]
    vals_d,  prob_d  = ccdf(deg_pos)
    vals_bc, prob_bc = ccdf(bc_pos)
    gamma_d,  b_d  = powerlaw_fit(vals_d,  prob_d)
    gamma_bc, b_bc = powerlaw_fit(vals_bc, prob_bc)

    # A: Degree CCDF
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.loglog(vals_d, prob_d, "o", mfc="none", mec="#1f77b4", ms=5,
              label="Empirical CCDF")
    if gamma_d is not None:
        xfit = np.logspace(np.log10(vals_d.min()), np.log10(vals_d.max()), 80)
        ax.loglog(xfit, 10**b_d * xfit**gamma_d, "--", color="#d62728", lw=1.5,
                  label=f"Power-law fit (gamma = {gamma_d:.2f})")
    ax.set_xlabel("Degree k")
    ax.set_ylabel("P(K >= k) [CCDF]")
    ax.set_title("Degree CCDF [Eq.10]", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig3a_degree_ccdf.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig3a] -> {p}")

    # B: Betweenness CCDF
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    if len(vals_bc) > 1:
        ax.loglog(vals_bc, prob_bc, "s", mfc="none", mec="#ff7f0e", ms=5,
                  label="Empirical CCDF")
        if gamma_bc is not None:
            xfit = np.logspace(np.log10(vals_bc.min()), np.log10(vals_bc.max()), 80)
            ax.loglog(xfit, 10**b_bc * xfit**gamma_bc, "--", color="#9467bd", lw=1.5,
                      label=f"Power-law fit (gamma = {gamma_bc:.2f})")
    ax.set_xlabel("Betweenness centrality g(v) [Eq.11]")
    ax.set_ylabel("P(G >= g) [CCDF]")
    ax.set_title("Betweenness Centrality CCDF", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig3b_betweenness_ccdf.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig3b] -> {p}")

    # C: Degree vs Betweenness
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    valid = (degs > 0) & (bc_arr > 0)
    ax.loglog(degs[valid], bc_arr[valid], ".", ms=4, alpha=0.4, color="#2ca02c")
    ax.set_xlabel("Degree k")
    ax.set_ylabel("Betweenness g(v) [Eq.11]")
    ax.set_title("Degree vs. Betweenness (log-log)", fontweight="bold")
    fig.tight_layout()
    p = out_dir / "fig3c_degree_vs_betweenness.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig3c] -> {p}")

# ─────────────────────────────────────────────────────────────────────
# Fig 4 — Homophily matrix (Split)
# ─────────────────────────────────────────────────────────────────────
def fig4_homophily_heatmap(G: nx.Graph, edges, out_dir: Path) -> None:
    node_class  = {i: G.nodes[i].get("primary_class", "Unknown") for i in G.nodes()}
    cls_present = [c for c in ALL_CLASSES if c in set(node_class.values())]
    mat = eq6_homophily(edges, node_class, cls_present)

    row_sum = mat.sum(axis=1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        mat_norm = np.where(row_sum > 0, mat / row_sum, 0.0)

    # Raw Heatmap
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    im0 = ax.imshow(np.log1p(mat), cmap="Blues", aspect="auto")
    ax.set_xticks(range(len(cls_present)))
    ax.set_xticklabels(cls_present, rotation=90, fontsize=7)
    ax.set_yticks(range(len(cls_present)))
    ax.set_yticklabels(cls_present, fontsize=7)
    plt.colorbar(im0, ax=ax, label="log(1 + count)")
    ax.set_title("Co-citation Count Matrix log(1+count) [Eq.6]", fontweight="bold")
    ax.set_xlabel("D-class (target j)")
    ax.set_ylabel("D-class (source i)")
    fig.tight_layout()
    p = out_dir / "fig4a_homophily_raw.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig4a] -> {p}")

    # Norm Heatmap
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    im1 = ax.imshow(mat_norm, cmap="Oranges", aspect="auto", vmin=0, vmax=1)
    ax.set_xticks(range(len(cls_present)))
    ax.set_xticklabels(cls_present, rotation=90, fontsize=7)
    ax.set_yticks(range(len(cls_present)))
    ax.set_yticklabels(cls_present, fontsize=7)
    plt.colorbar(im1, ax=ax, label="Row-normalised fraction")
    ax.set_title("Row-Normalised Homophily H_ij / row_sum", fontweight="bold")
    ax.set_xlabel("D-class (target j)")
    ax.set_ylabel("D-class (source i)")
    fig.tight_layout()
    p = out_dir / "fig4b_homophily_norm.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig4b] -> {p}")

# ─────────────────────────────────────────────────────────────────────
# Fig 5 — Sender / Receiver per class (Split)
# ─────────────────────────────────────────────────────────────────────
def fig5_sender_receiver(G: nx.Graph, arcs, out_dir: Path) -> None:
    node_class  = {i: G.nodes[i].get("primary_class", "Unknown") for i in G.nodes()}
    cls_present = [c for c in ALL_CLASSES if c in set(node_class.values())]
    g_s = eq4_sender_effect(arcs, node_class)
    g_r = eq5_receiver_effect(arcs, node_class)

    node_count = defaultdict(int)
    for c in node_class.values():
        node_count[c] += 1

    gs_norm = {c: g_s.get(c, 0) / max(node_count[c], 1) for c in cls_present}
    gr_norm = {c: g_r.get(c, 0) / max(node_count[c], 1) for c in cls_present}

    order = sorted(cls_present, key=lambda c: g_s.get(c, 0) + g_r.get(c, 0), reverse=True)
    x = np.arange(len(order))
    w = 0.38

    # Absolute
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - w/2, [g_s.get(c, 0) for c in order], width=w,
           color=[cls_color(c) for c in order], edgecolor="black", label="Sender")
    ax.bar(x + w/2, [g_r.get(c, 0) for c in order], width=w,
           color=[cls_color(c) for c in order], edgecolor="black", hatch="//",
           alpha=0.7, label="Receiver")
    ax.set_xticks(x)
    ax.set_xticklabels(order, rotation=90, fontsize=8)
    ax.set_ylabel("Arc count")
    ax.set_title("Absolute Sender/Receiver Effects [Eqs. 4-5]", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig5a_effects_absolute.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig5a] -> {p}")

    # Normalised
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - w/2, [gs_norm[c] for c in order], width=w,
           color=[cls_color(c) for c in order], edgecolor="black", label="Sender rate")
    ax.bar(x + w/2, [gr_norm[c] for c in order], width=w,
           color=[cls_color(c) for c in order], edgecolor="black", hatch="//",
           alpha=0.7, label="Receiver rate")
    ax.set_xticks(x)
    ax.set_xticklabels(order, rotation=90, fontsize=8)
    ax.set_ylabel("Arcs per node")
    ax.set_title("Normalised Effects (arcs per node)", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig5b_effects_normalised.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig5b] -> {p}")

# ─────────────────────────────────────────────────────────────────────
# Fig 6 — GW network statistics (Split & LaTeX)
# ─────────────────────────────────────────────────────────────────────
def fig6_gw_statistics(G: nx.Graph, out_dir: Path) -> None:
    alphas      = np.linspace(0.5, 4.0, 14)
    gw_id_vals  = [gw_idegree(G, a) for a in alphas]
    gw_od_vals  = [gw_odegree(G, a) for a in alphas]
    gw_esp_vals = [gw_esp(G, a) for a in alphas]
    gw_dsp_val  = gw_dsp(G, alpha=2.0)
    T_val       = eq9_transitivity(G)

    # GW Degree
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.plot(alphas, gw_id_vals, "o-", color="#1f77b4", label="GWIDegree")
    ax.plot(alphas, gw_od_vals, "s--", color="#ff7f0e", label="GWODegree")
    ax.set_xlabel("Decay parameter alpha")
    ax.set_ylabel("GWDegree value")
    ax.set_title("GWIDegree & GWODegree vs. alpha", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig6a_gw_degree.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig6a] -> {p}")

    # GWESP
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.plot(alphas, gw_esp_vals, "^-", color="#2ca02c", label="GWESP")
    ax.set_xlabel("Decay parameter alpha")
    ax.set_ylabel("GWESP value")
    ax.set_title("GWESP vs. alpha", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig6b_gwesp.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig6b] -> {p}")

    # ESP Count
    esp_counts = defaultdict(int)
    for u, v in G.edges():
        shared = len(set(G.neighbors(u)) & set(G.neighbors(v)))
        esp_counts[shared] += 1
    esp_k    = sorted(esp_counts)
    esp_freq = [esp_counts[k] for k in esp_k]

    fig, ax = plt.subplots(figsize=FIG_SIZE)
    ax.bar(esp_k[:25], esp_freq[:25], color="#9467bd", edgecolor="black")
    ax.set_xlabel("Shared partners k (ESP)")
    ax.set_ylabel("Edge count")
    ax.set_yscale("log")
    ax.set_title("Edgewise Shared Partner Distribution", fontweight="bold")
    fig.tight_layout()
    p = out_dir / "fig6c_esp_dist.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig6c] -> {p}")

    # LaTeX Table
    tex_path = out_dir / "table_gw_stats.tex"
    with open(tex_path, "w") as f:
        f.write("\\begin{table}[htbp]\n\\centering\n")
        f.write("\\caption{GW Statistics Summary ($\\alpha=2$)}\n")
        f.write("\\begin{tabular}{lc}\n\\hline\n")
        f.write("Statistic & Value \\\\\n\\hline\n")
        f.write(f"GWIDegree & {gw_idegree(G, 2.0):.4e} \\\\\n")
        f.write(f"GWODegree & {gw_odegree(G, 2.0):.4e} \\\\\n")
        f.write(f"GWESP & {gw_esp(G, 2.0):.4e} \\\\\n")
        f.write(f"GWDSP & {gw_dsp_val:.4e} \\\\\n")
        f.write(f"Transitivity $T$ & {T_val:.5f} \\\\\n")
        f.write("\\hline\n\\end{tabular}\n\\end{table}\n")
    print(f"  [LaTeX] -> {tex_path}")

# ─────────────────────────────────────────────────────────────────────
# Fig 7 — Date guard (Split)
# ─────────────────────────────────────────────────────────────────────
def fig7_date_guard(G: nx.Graph, arcs, attrs: pd.DataFrame, out_dir: Path) -> None:
    if "date" not in attrs.columns:
        return

    node_date = {}
    for i, row in attrs.iterrows():
        try:
            node_date[i] = pd.to_datetime(row["date"])
        except Exception:
            pass

    valid = [(i, j) for i, j in arcs if i in node_date and j in node_date]
    if not valid:
        return

    diff_years = np.array([(node_date[j] - node_date[i]).days / 365.25 for i, j in valid])

    # Hist
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    lo   = max(diff_years.min(), -30)
    hi   = min(diff_years.max(),  30)
    bins = np.linspace(lo, hi, 55)
    neg_bins = bins[bins <= 0]
    pos_bins = bins[bins > 0]
    if len(neg_bins) >= 2:
        ax.hist(diff_years[diff_years <= 0], bins=neg_bins,
                color="#1f77b4", alpha=0.85, label="H=0 (valid)")
    if len(pos_bins) >= 2:
        ax.hist(diff_years[diff_years > 0], bins=pos_bins,
                color="#d62728", alpha=0.85, label="H=1 (forward)")
    ax.axvline(0, color="black", linestyle="--")
    ax.set_xlabel("(d_j - d_i) in years")
    ax.set_ylabel("Arc count")
    ax.set_title("Date Difference Distribution [Eq.7]", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig7a_date_diff_hist.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig7a] -> {p}")

    # Step function
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    y  = np.linspace(-3, 3, 300)
    Hy = np.where(y > 0, 1, 0).astype(float)
    ax.step(y, Hy, color="black", lw=1.8, where="post")
    ax.fill_between(y, 0, Hy,    step="post", alpha=0.2, color="#d62728",
                    label="H=1 (forward, penalised)")
    ax.fill_between(y, 0, 1-Hy, step="post", alpha=0.2, color="#1f77b4",
                    label="H=0 (valid arc)")
    ax.set_xlabel("y = d_j - d_i")
    ax.set_ylabel("H(y)")
    ax.set_ylim(-0.1, 1.35)
    ax.set_yticks([0, 1])
    ax.set_title("Unit-Step Gate Function H(y) [Eq.8]", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig7b_date_step_func.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig7b] -> {p}")

    # CDF
    fig, ax = plt.subplots(figsize=FIG_SIZE)
    yr_fwd  = np.sort(diff_years[diff_years > 0])
    yr_bkwd = np.sort(-diff_years[diff_years <= 0])
    if len(yr_fwd) > 1:
        ax.plot(yr_fwd,  np.arange(1, len(yr_fwd)+1)  / len(yr_fwd),
                color="#d62728", lw=1.5, label="Forward arcs")
    if len(yr_bkwd) > 1:
        ax.plot(yr_bkwd, np.arange(1, len(yr_bkwd)+1) / len(yr_bkwd),
                color="#1f77b4", lw=1.5, label="|Backward| arcs")
    ax.set_xlabel("Citation age gap |years|")
    ax.set_ylabel("Cumulative fraction")
    ax.set_title("Citation Age Gap CDF", fontweight="bold")
    ax.legend()
    fig.tight_layout()
    p = out_dir / "fig7c_date_diff_cdf.png"
    fig.savefig(p)
    plt.close(fig)
    print(f"  [Fig7c] -> {p}")

# ─────────────────────────────────────────────────────────────────────
# Fig 8 — ERGM coefficients forest plot
# ─────────────────────────────────────────────────────────────────────
def fig8_ergm_coefficients(out_dir: Path, ergm_csv_path: Path = None) -> None:
    """
    APS-style forest plot of ERGM theta coefficients with 95% CI error bars.

    If ergm_csv_path points to an existing CSV (columns: group, label, estimate,
    std_error), real estimates are plotted.  Otherwise a watermarked dummy is
    produced so the file is clearly not publishable without actual MCMC output.
    """
    is_dummy = False

    if ergm_csv_path is not None and Path(ergm_csv_path).exists():
        df = pd.read_csv(ergm_csv_path)
        required = {"group", "label", "estimate", "std_error"}
        if not required.issubset(df.columns):
            print(f"  WARNING: {ergm_csv_path} missing columns {required - set(df.columns)}; "
                  "falling back to dummy data.", file=sys.stderr)
            is_dummy = True
        else:
            ergm_data = defaultdict(list)
            for _, row in df.iterrows():
                ergm_data[row["group"]].append(
                    (str(row["label"]), float(row["estimate"]), float(row["std_error"])))
            ergm_data = dict(ergm_data)
    else:
        is_dummy = True

    if is_dummy:
        ergm_data = {
            "Network Structures": [
                ("Arc Count (Eq.2 analog)",                   -3.20, 0.12),
                ("Triangles / Transitivity (AltKTriT proxy)", +0.85, 0.09),
                ("GWIDegree alpha=log(2) (AltInStars)",       +0.62, 0.11),
            ],
            "Homophily (D-Class)": [
                ("Same Primary D-Class (Eq.6)",               +1.47, 0.08),
            ],
        }

    # Build flat ordered lists
    group_labels, labels, estimates, errors, group_ids = [], [], [], [], []
    group_order = list(ergm_data.keys())
    for gid, grp in enumerate(group_order):
        for lbl, est, se in ergm_data[grp]:
            group_labels.append(grp)
            labels.append(lbl)
            estimates.append(est)
            errors.append(se * 1.96)  # 95% CI half-width
            group_ids.append(gid)

    n = len(labels)
    y_pos = list(range(n - 1, -1, -1))  # top-to-bottom

    # Group separator positions (first index of each group, reversed)
    group_starts = {}
    for i, grp in enumerate(group_labels):
        if grp not in group_starts:
            group_starts[grp] = y_pos[i]

    GROUP_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"]

    fig, ax = plt.subplots(figsize=(9, max(4, n * 0.65 + 1.5)))

    for i, (y, est, err, gid) in enumerate(zip(y_pos, estimates, errors, group_ids)):
        color = GROUP_COLORS[gid % len(GROUP_COLORS)]
        ax.errorbar(est, y, xerr=err,
                    fmt="o", color=color, ms=7,
                    ecolor=color, elinewidth=1.6, capsize=4, capthick=1.6,
                    zorder=3)

    ax.axvline(0, color="#555555", lw=1.0, ls="--", zorder=2)

    # Y-axis labels
    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9)

    # Group header lines
    group_patch = []
    for gid, grp in enumerate(group_order):
        color = GROUP_COLORS[gid % len(GROUP_COLORS)]
        group_patch.append(mpatches.Patch(color=color, label=grp))

    # Bracket lines for groups
    for gid, grp in enumerate(group_order):
        rows = [y_pos[i] for i, g in enumerate(group_labels) if g == grp]
        color = GROUP_COLORS[gid % len(GROUP_COLORS)]
        ax.barh(rows, [0] * len(rows), left=ax.get_xlim()[0],
                height=0.7, color=color, alpha=0.08, zorder=1)

    ax.legend(handles=group_patch, loc="lower right", fontsize=9, framealpha=0.88)
    ax.set_xlabel("ERGM coefficient theta  (mean +/- 1.96 SE)", fontsize=10)
    ax.set_title("ERGM Parameter Estimates — Chakraborty et al. (2020) Framework",
                 fontsize=11, fontweight="bold")
    ax.set_ylim(-0.8, n - 0.2)

    if is_dummy:
        fig.text(0.5, 0.5,
                 "ILLUSTRATIVE DATA\nREQUIRES ACTUAL MCMC ESTIMATION",
                 fontsize=16, color="gray", alpha=0.35,
                 ha="center", va="center", rotation=28,
                 transform=fig.transFigure,
                 fontweight="bold")

    fig.tight_layout()
    p = out_dir / "fig8_ergm_coefficients.pdf"
    fig.savefig(p, format="pdf", bbox_inches="tight")
    plt.close(fig)
    status = "(DUMMY — watermarked)" if is_dummy else "(real estimates)"
    print(f"  [Fig8] {status} -> {p}")

# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(description="USPTO design patent ERGM Visualizer v4")
    parser.add_argument("--ergm-dir",      default="ergm_input")
    parser.add_argument("--out-dir",       default="output")
    parser.add_argument("--top-n",         type=int, default=300)
    parser.add_argument("--bc-k",          type=int, default=500)
    parser.add_argument("--no-fig1",       action="store_true")
    parser.add_argument("--no-fig6",       action="store_true")
    # MCMC estimation flags
    parser.add_argument("--estimate-ergm", action="store_true",
                        help="Run Robbins-Monro MCMLE and save ergm_results.csv")
    parser.add_argument("--ergm-csv",      default=None,
                        help="Path to existing ergm_results CSV for fig8")
    parser.add_argument("--ergm-subgraph", type=int, default=500,
                        help="Top-degree nodes for ERGM subgraph (default 500)")
    parser.add_argument("--ergm-outer",    type=int, default=40,
                        help="Robbins-Monro outer iterations (default 40)")
    parser.add_argument("--ergm-mcmc",     type=int, default=300,
                        help="MCMC samples per outer iteration (default 300)")
    args = parser.parse_args()

    ergm_dir = Path(args.ergm_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    attr_path = ergm_dir / "attributes.txt"
    arc_path  = ergm_dir / "arc_list.txt"
    if not attr_path.exists() or not arc_path.exists():
        print(f"ERROR: Files not found in {ergm_dir}", file=sys.stderr)
        sys.exit(1)

    print("Loading data...")
    attrs = load_attrs(attr_path)
    arcs  = load_arc_list(arc_path)
    edges = arcs_to_undirected(arcs)
    print(f"  {len(attrs):,} nodes,  {len(arcs):,} arcs  ->  {len(edges):,} undirected edges")

    G = build_graph(len(attrs), edges)
    attach_attrs(G, attrs)

    # Optionally run MCMC ERGM estimation
    ergm_csv_path = Path(args.ergm_csv) if args.ergm_csv else None

    if args.estimate_ergm:
        print("\nRunning Robbins-Monro MCMLE ERGM estimation...")
        node_class_dict = {i: G.nodes[i].get("primary_class", "") for i in G.nodes()}
        ergm_df = estimate_ergm_mcmc(
            G,
            node_class_dict,
            subgraph_size=args.ergm_subgraph,
            n_outer=args.ergm_outer,
            n_mcmc=args.ergm_mcmc,
        )
        csv_out = out_dir / "ergm_results.csv"
        ergm_df.to_csv(csv_out, index=False)
        print(f"  [ERGM CSV] -> {csv_out}")
        print(ergm_df.to_string(index=False))
        ergm_csv_path = csv_out

    print("\nGenerating separated figures and LaTeX tables...")
    if not args.no_fig1:
        fig1_network_topology(G, out_dir / "fig1_network_topology.png", args.top_n)

    fig2_ergm_statistics(G, arcs, edges, attrs, out_dir)
    fig3_degree_distribution(G, out_dir, args.bc_k)
    fig4_homophily_heatmap(G, edges, out_dir)
    fig5_sender_receiver(G, arcs, out_dir)

    if not args.no_fig6:
        fig6_gw_statistics(G, out_dir)

    fig7_date_guard(G, arcs, attrs, out_dir)
    fig8_ergm_coefficients(out_dir, ergm_csv_path)

    print(f"\nDone. All outputs generated in '{out_dir}/'")


if __name__ == "__main__":
    # Usage:
    #   python visualize_ergm_network.py
    #   python visualize_ergm_network.py --no-fig1 --no-fig6
    #   python visualize_ergm_network.py --estimate-ergm --ergm-subgraph 300 --ergm-outer 20
    #   python visualize_ergm_network.py --ergm-csv output/ergm_results.csv
    main()
