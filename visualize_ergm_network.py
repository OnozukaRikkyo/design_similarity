#!/usr/bin/env python3
"""
USPTO 意匠特許共引用ネットワーク可視化スクリプト（論文出版品質）

build_ergm_input.py の出力 (ergm_input/) をもとに、
分類コードと共引用の構造を可視化した論文品質 PNG を生成する。

出力:
  output/network_patent_graph.png    特許ノードの共引用ネットワーク（サブグラフ）
  output/network_class_graph.png     D-class 集約ネットワーク
  output/network_degree_dist.png     次数分布（log-log スケール）
  output/network_summary.csv         グラフ要約統計

実行例:
  python visualize_ergm_network.py
  python visualize_ergm_network.py --top-n 300 --hops 1 --metric degree
  python visualize_ergm_network.py --top-n 150 --metric betweenness --betweenness-k 500
  python visualize_ergm_network.py --sim-dir /mnt/eightthdd/uspto/similarity_results
"""

import argparse
import json
import pickle
import sys
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Publication-quality matplotlib settings
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family":        "sans-serif",
    "font.sans-serif":    ["Helvetica", "Arial", "DejaVu Sans"],
    "font.size":          11,
    "axes.labelsize":     12,
    "axes.titlesize":     13,
    "axes.linewidth":     0.8,
    "xtick.labelsize":    10,
    "ytick.labelsize":    10,
    "xtick.major.width":  0.8,
    "ytick.major.width":  0.8,
    "legend.fontsize":    9,
    "legend.framealpha":  0.92,
    "legend.edgecolor":   "0.75",
    "figure.dpi":         150,
    "savefig.dpi":        300,
    "savefig.bbox":       "tight",
    "savefig.facecolor":  "white",
})

# ---------------------------------------------------------------------------
# D-class constants
# ---------------------------------------------------------------------------
ALL_CLASSES: list[str] = [f"D{i}" for i in range(1, 35)] + ["D99"]

CLASS_NAMES: dict[str, str] = {
    "D1":  "Edible Products",        "D2":  "Apparel",
    "D3":  "Travel Goods",           "D4":  "Brushware",
    "D5":  "Textile",                "D6":  "Furnishings",
    "D7":  "Food Equipment",         "D8":  "Tools & Hardware",
    "D9":  "Tools (misc)",           "D10": "Measuring Devices",
    "D11": "Jewelry",                "D12": "Transportation",
    "D13": "Production Equipment",   "D14": "Recording/Comm/Info",
    "D15": "Machines",               "D16": "Photography/Optics",
    "D17": "Musical Instruments",    "D18": "Printing/Office Mach.",
    "D19": "Office Supplies",        "D20": "Sales/Advertising",
    "D21": "Amusement Devices",      "D22": "Arms/Pyrotechnics",
    "D23": "Heating/Cooling",        "D24": "Medical/Lab Equipment",
    "D25": "Building/Construction",  "D26": "Lighting",
    "D27": "Tobacco/Smoking",        "D28": "Pharma/Cosmetics",
    "D29": "Animal Husbandry",       "D30": "Outdoor/Garden",
    "D31": "Articles of Mfg",        "D32": "Washing/Cleaning",
    "D33": "Food/Bev Service",       "D34": "Material Handling",
    "D99": "Miscellaneous",
}

# 35 distinct qualitative colors: tab20 (20) + tab20b[:15]
_c20a = list(plt.cm.tab20.colors)
_c20b = list(plt.cm.tab20b.colors)
_palette = _c20a + _c20b[:15]

CLASS_COLORS: dict[str, tuple] = {cls: _palette[i] for i, cls in enumerate(ALL_CLASSES)}
CLASS_COLORS["Unknown"] = (0.60, 0.60, 0.60)


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------
def load_arc_list(arc_path: Path) -> list[tuple[int, int]]:
    arcs = []
    with open(arc_path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                arcs.append((int(parts[0]), int(parts[1])))
    return arcs


def arcs_to_undirected_edges(arcs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    edges = []
    for u, v in arcs:
        if u == v:
            continue
        key = (min(u, v), max(u, v))
        if key not in seen:
            seen.add(key)
            edges.append(key)
    return edges


def load_patent_cache(ergm_dir: Path) -> dict | None:
    path = ergm_dir / "_patent_attr_cache.pkl"
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------
def build_nx_graph(
    n_nodes: int,
    edges: list[tuple[int, int]],
    attrs: pd.DataFrame,
    patent_cache_keys: list[str] | None = None,
) -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(range(n_nodes))
    G.add_edges_from(edges)
    for i in range(min(n_nodes, len(attrs))):
        row = attrs.iloc[i]
        G.nodes[i]["primary_class"] = str(row.get("primary_class", "Unknown"))
        G.nodes[i]["n_classes"]     = int(row.get("n_classes", 0))
        G.nodes[i]["date"]          = str(row.get("date", ""))
        G.nodes[i]["patent_id"]     = (
            patent_cache_keys[i]
            if patent_cache_keys and i < len(patent_cache_keys)
            else str(i)
        )
    return G


def compute_node_metrics(G: nx.Graph, betweenness_k: int = 300, seed: int = 42) -> None:
    print("  [Graph] degree を計算中...")
    nx.set_node_attributes(G, dict(G.degree()), "degree")
    N = G.number_of_nodes()
    print(f"  [Graph] betweenness を計算中 (k={betweenness_k}, N={N:,})...")
    bc = (
        nx.betweenness_centrality(G, normalized=True)
        if N <= max(betweenness_k, 500)
        else nx.betweenness_centrality(G, k=betweenness_k, normalized=True, seed=seed)
    )
    nx.set_node_attributes(G, bc, "betweenness")


def extract_focus_subgraph(
    G: nx.Graph, top_n: int = 250, hops: int = 1, metric: str = "degree"
) -> nx.Graph:
    vals = nx.get_node_attributes(G, metric)
    if not vals:
        raise ValueError(f"ノード属性 '{metric}' が存在しません。")
    seeds = [n for n, _ in sorted(vals.items(), key=lambda x: x[1], reverse=True)[:top_n]]
    selected = set(seeds)
    frontier = set(seeds)
    for _ in range(hops):
        nxt: set[int] = set()
        for u in frontier:
            nxt.update(G.neighbors(u))
        nxt -= selected
        selected |= nxt
        frontier = nxt
    return G.subgraph(sorted(selected)).copy()


def load_gemini_yes_pairs(
    sim_dir: Path, patent_cache_keys: list[str] | None
) -> set[tuple[int, int]]:
    if patent_cache_keys is None:
        print("  [Gemini] patent_cache なし。overlay スキップ。")
        return set()
    id_to_row = {pid: i for i, pid in enumerate(patent_cache_keys)}
    yes_pairs: set[tuple[int, int]] = set()
    n_loaded = 0
    for jsonl in sorted(sim_dir.glob("*.jsonl")):
        with open(jsonl, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(rec.get("similarity", "")).lower() not in ("yes", "true", "1", "similar"):
                    continue
                src = str(rec.get("source", rec.get("patent_a", "")))
                tgt = str(rec.get("target", rec.get("patent_b", "")))
                i, j = id_to_row.get(src), id_to_row.get(tgt)
                if i is not None and j is not None:
                    yes_pairs.add((min(i, j), max(i, j)))
                    n_loaded += 1
    print(f"  [Gemini] Yes ペア: {n_loaded:,} 件")
    return yes_pairs


# ---------------------------------------------------------------------------
# D-class aggregation
# ---------------------------------------------------------------------------
def build_class_graph(G: nx.Graph) -> nx.Graph:
    H: nx.Graph = nx.Graph()
    for cls in ALL_CLASSES + ["Unknown"]:
        H.add_node(cls, count=0, internal_edges=0)
    for n in G.nodes():
        cls = G.nodes[n].get("primary_class", "Unknown")
        if not H.has_node(cls):
            H.add_node(cls, count=0, internal_edges=0)
        H.nodes[cls]["count"] += 1
    for u, v in G.edges():
        cu = G.nodes[u].get("primary_class", "Unknown")
        cv = G.nodes[v].get("primary_class", "Unknown")
        if cu == cv:
            H.nodes[cu]["internal_edges"] += 1
        else:
            if not H.has_edge(cu, cv):
                H.add_edge(cu, cv, weight=0)
            H[cu][cv]["weight"] += 1
    H.remove_nodes_from([n for n in H.nodes() if H.nodes[n]["count"] == 0])
    return H


# ---------------------------------------------------------------------------
# Sizing utilities
# ---------------------------------------------------------------------------
def _log_scale(values: np.ndarray, v_min: float, v_max: float) -> np.ndarray:
    """配列を log1p スケールで [v_min, v_max] に正規化する。"""
    lv = np.log1p(np.maximum(values, 0.0))
    lo, hi = lv.min(), lv.max()
    norm = (lv - lo) / (hi - lo + 1e-12)
    return v_min + (v_max - v_min) * norm


def _ref_val(x: float, all_vals: np.ndarray, v_min: float, v_max: float) -> float:
    """_log_scale と同じ変換を単一参照値に適用する。"""
    lv = np.log1p(np.maximum(all_vals, 0.0))
    lo, hi = lv.min(), lv.max()
    norm = float(np.clip((np.log1p(max(x, 0)) - lo) / (hi - lo + 1e-12), 0.0, 1.0))
    return v_min + (v_max - v_min) * norm


# ---------------------------------------------------------------------------
# Figure 1: Patent subgraph  (network_patent_graph.png)
# ---------------------------------------------------------------------------
def plot_patent_network(
    SG: nx.Graph,
    out_path: Path,
    yes_pairs: set[tuple[int, int]] | None = None,
    metric: str = "degree",
) -> None:
    """特許レベルの共引用ネットワーク（論文品質 PNG）。

    ノード色    : primary D-class
    ノードサイズ : degree（log スケール）
    エッジ色    : グレー（通常）/ 橙（Gemini Yes）
    """
    N, E = SG.number_of_nodes(), SG.number_of_edges()
    iters = max(30, min(100, 10_000 // max(N, 1)))
    print(f"  [PatentGraph] spring layout (N={N:,}, iter={iters})...")
    pos = nx.spring_layout(SG, seed=42, iterations=iters)

    nodes  = list(SG.nodes())
    vals   = np.array([max(SG.nodes[n].get(metric, 0), 1) for n in nodes], dtype=float)
    S_MIN, S_MAX = 15.0, 450.0
    sizes  = _log_scale(vals, S_MIN, S_MAX)
    colors = [CLASS_COLORS.get(SG.nodes[n].get("primary_class", "Unknown"),
                               CLASS_COLORS["Unknown"]) for n in nodes]

    yes_set      = yes_pairs or set()
    normal_edges = [(u, v) for u, v in SG.edges() if (min(u, v), max(u, v)) not in yes_set]
    yes_edges    = [(u, v) for u, v in SG.edges() if (min(u, v), max(u, v)) in yes_set]

    fig, ax = plt.subplots(figsize=(12, 9))
    ax.set_aspect("equal")
    ax.axis("off")

    # --- edges ---
    nx.draw_networkx_edges(SG, pos, edgelist=normal_edges, ax=ax,
                           edge_color="0.72", alpha=0.22, width=0.35, arrows=False)
    if yes_edges:
        nx.draw_networkx_edges(SG, pos, edgelist=yes_edges, ax=ax,
                               edge_color="#ff7f0e", alpha=0.72, width=1.5, arrows=False)

    # --- nodes ---
    nx.draw_networkx_nodes(SG, pos, nodelist=nodes, ax=ax,
                           node_color=colors, node_size=list(sizes),
                           linewidths=0.4, edgecolors="white")

    # ---- 凡例 1: D-class 色（件数降順、最大 20 件） ----
    class_counts: dict[str, int] = {}
    for n in SG.nodes():
        cls = SG.nodes[n].get("primary_class", "Unknown")
        class_counts[cls] = class_counts.get(cls, 0) + 1
    sorted_cls = sorted(class_counts.items(), key=lambda x: x[1], reverse=True)

    MAX_L = 20
    handles_cls = [
        mpatches.Patch(
            facecolor=CLASS_COLORS.get(c, CLASS_COLORS["Unknown"]),
            edgecolor="0.55", linewidth=0.5,
            label=f"{c}  {CLASS_NAMES.get(c, '')[:18]}  (n = {cnt:,})",
        )
        for c, cnt in sorted_cls[:MAX_L]
    ]
    if len(sorted_cls) > MAX_L:
        handles_cls.append(mpatches.Patch(
            facecolor="none", edgecolor="none",
            label=f"… +{len(sorted_cls) - MAX_L} other class(es)",
        ))

    leg1 = ax.legend(handles=handles_cls,
                     loc="upper left", bbox_to_anchor=(1.01, 1.0),
                     title="Design Class", title_fontsize=10,
                     fontsize=8.5, framealpha=0.92, edgecolor="0.72",
                     handlelength=1.0, handleheight=1.0, borderpad=0.8)
    ax.add_artist(leg1)

    # ---- 凡例 2: ノードサイズ（degree スケール） ----
    max_val = int(vals.max())
    ref_vals = sorted({1, max(2, max_val // 4), max(4, max_val // 2), max_val})
    handles_sz = [
        plt.scatter([], [],
                    s=_ref_val(v, vals, S_MIN, S_MAX),
                    color="#555555", edgecolors="white", linewidths=0.4,
                    label=f"$k$ = {v:,}")
        for v in ref_vals
    ]
    leg2 = ax.legend(handles=handles_sz,
                     loc="lower left", bbox_to_anchor=(1.01, 0.0),
                     title=f"Node size  ({metric})", title_fontsize=10,
                     fontsize=8.5, framealpha=0.92, edgecolor="0.72",
                     scatterpoints=1, borderpad=0.8)
    ax.add_artist(leg2)

    # ---- 凡例 3: Gemini Yes エッジ（オプション） ----
    if yes_edges:
        leg3 = ax.legend(
            handles=[mlines.Line2D([], [], color="#ff7f0e", linewidth=1.5,
                                   label=f"Visually similar  ($n$ = {len(yes_edges):,})")],
            loc="center left", bbox_to_anchor=(1.01, 0.52),
            fontsize=8.5, framealpha=0.92, edgecolor="0.72",
        )
        ax.add_artist(leg3)

    ax.set_title(
        f"Design Patent Co-citation Network  ($N$ = {N:,},  $E$ = {E:,})",
        fontsize=13, pad=12,
    )
    fig.savefig(str(out_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  [PatentGraph] → {out_path}")


# ---------------------------------------------------------------------------
# Figure 2: D-class aggregated network  (network_class_graph.png)
# ---------------------------------------------------------------------------
def plot_class_network(H: nx.Graph, out_path: Path) -> None:
    """D-class 単位に集約した共引用ネットワーク（論文品質 PNG）。

    ノードサイズ : 特許件数（log スケール）
    エッジ太さ  : クラス間共引用本数（log スケール）
    """
    if H.number_of_nodes() == 0:
        return

    pos = nx.spring_layout(H, seed=42, weight="weight", iterations=300)

    # Node sizes [pt²]
    counts     = np.array([H.nodes[n]["count"] for n in H.nodes()], dtype=float)
    N_MIN, N_MAX = 200.0, 3500.0
    node_sizes = _log_scale(counts, N_MIN, N_MAX)
    node_colors = [CLASS_COLORS.get(n, CLASS_COLORS["Unknown"]) for n in H.nodes()]

    # Edge widths [pt] and alpha
    weights = np.array([d.get("weight", 1) for _, _, d in H.edges(data=True)], dtype=float)
    W_MIN, W_MAX = 0.3, 6.0
    if len(weights):
        edge_widths = _log_scale(weights, W_MIN, W_MAX)
        edge_alphas = 0.20 + 0.65 * (np.log1p(weights) / (np.log1p(weights.max()) + 1e-12))
    else:
        edge_widths = np.array([])
        edge_alphas = np.array([])

    fig, ax = plt.subplots(figsize=(13, 10))
    ax.set_aspect("equal")
    ax.axis("off")

    # Draw edges individually (per-edge width / alpha)
    for (u, v, d), w_pt, alpha in zip(H.edges(data=True), edge_widths, edge_alphas):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        ax.plot([x0, x1], [y0, y1],
                color="0.40", linewidth=float(w_pt), alpha=float(alpha), zorder=1,
                solid_capstyle="round")

    # Draw nodes
    nx.draw_networkx_nodes(H, pos, ax=ax,
                           node_size=list(node_sizes),
                           node_color=node_colors,
                           linewidths=0.8, edgecolors="white", zorder=2)

    # Labels just above each node (offset = 4% of y-range)
    pos_arr = np.array(list(pos.values()))
    y_range = float(pos_arr[:, 1].ptp()) + 1e-9
    label_pos = {n: (pos[n][0], pos[n][1] + 0.04 * y_range) for n in H.nodes()}
    nx.draw_networkx_labels(H, label_pos, ax=ax,
                            labels={n: n for n in H.nodes()},
                            font_size=8, font_color="#111111",
                            font_weight="bold", zorder=3)

    # ---- 凡例 1: ノードサイズ（特許件数） ----
    max_cnt = int(counts.max())
    ref_cnts = sorted({1, max(2, max_cnt // 4), max(4, max_cnt // 2), max_cnt})
    handles_sz = [
        plt.scatter([], [],
                    s=_ref_val(c, counts, N_MIN, N_MAX),
                    color="#555555", edgecolors="white", linewidths=0.5,
                    label=f"{c:,} patents")
        for c in ref_cnts
    ]
    leg1 = ax.legend(handles=handles_sz,
                     loc="lower left", bbox_to_anchor=(1.01, 0.0),
                     title="Node size  (patent count)", title_fontsize=10,
                     fontsize=9, framealpha=0.92, edgecolor="0.72",
                     scatterpoints=1, borderpad=0.9)
    ax.add_artist(leg1)

    # ---- 凡例 2: エッジ太さ（クラス間共引用数） ----
    if len(weights):
        max_w = int(weights.max())
        ref_ws = sorted({1, max(2, max_w // 4), max(4, max_w // 2), max_w})
        handles_ew = [
            mlines.Line2D([], [],
                          color="0.40",
                          linewidth=_ref_val(w, weights, W_MIN, W_MAX),
                          solid_capstyle="round",
                          label=f"{w:,} co-citations")
            for w in ref_ws
        ]
        leg2 = ax.legend(handles=handles_ew,
                         loc="upper left", bbox_to_anchor=(1.01, 1.0),
                         title="Edge width  (inter-class co-citations)", title_fontsize=10,
                         fontsize=9, framealpha=0.92, edgecolor="0.72",
                         borderpad=0.9)
        ax.add_artist(leg2)

    ax.set_title(
        f"Design Patent Class Co-citation Network  "
        f"($N_{{\\rm class}}$ = {H.number_of_nodes()},  "
        f"$E_{{\\rm inter}}$ = {H.number_of_edges():,})",
        fontsize=13, pad=12,
    )
    fig.savefig(str(out_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  [ClassGraph] → {out_path}")


# ---------------------------------------------------------------------------
# Figure 3: Degree distribution log-log  (network_degree_dist.png)
# ---------------------------------------------------------------------------
def plot_degree_distribution(G: nx.Graph, out_path: Path) -> None:
    """次数分布の log-log プロット + べき乗則フィット。"""
    degrees = np.array([d for _, d in G.degree() if d > 0], dtype=float)
    if len(degrees) == 0:
        return

    unique_k, counts = np.unique(degrees, return_counts=True)
    pk = counts / counts.sum()
    k_mean = degrees.mean()

    # Power-law fit on tail (k >= mean, minimum 4 points)
    tail_mask = unique_k >= max(k_mean, 2.0)
    fit_result: tuple | None = None
    if tail_mask.sum() >= 4:
        log_k = np.log10(unique_k[tail_mask])
        log_p = np.log10(pk[tail_mask])
        coeffs = np.polyfit(log_k, log_p, 1)
        gamma  = -coeffs[0]
        k_fit  = np.logspace(np.log10(unique_k[tail_mask].min()),
                             np.log10(unique_k.max()), 120)
        p_fit  = 10 ** np.polyval(coeffs, np.log10(k_fit))
        fit_result = (k_fit, p_fit, gamma)

    fig, ax = plt.subplots(figsize=(6, 5))

    ax.scatter(unique_k, pk, s=22, color="#1f77b4", alpha=0.82,
               edgecolors="white", linewidths=0.3, zorder=3,
               label=f"$P(k)$  ($N$ = {G.number_of_nodes():,})")

    if fit_result is not None:
        k_fit, p_fit, gamma = fit_result
        ax.plot(k_fit, p_fit, "--", color="#d62728", linewidth=1.6, alpha=0.88, zorder=2,
                label=f"Power-law fit  ($\\gamma = {gamma:.2f}$)")

    ax.axvline(k_mean, color="#2ca02c", linewidth=1.2, linestyle=":",
               alpha=0.80, zorder=2,
               label=f"$\\langle k \\rangle = {k_mean:.1f}$")

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Degree  $k$", fontsize=12)
    ax.set_ylabel("$P(k)$", fontsize=12)
    ax.set_title("Degree Distribution of Co-citation Network", fontsize=13)
    ax.legend(fontsize=9, framealpha=0.92, edgecolor="0.75")
    ax.grid(True, which="both", alpha=0.20, linewidth=0.5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    fig.tight_layout()
    fig.savefig(str(out_path), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  [DegDist] → {out_path}")


# ---------------------------------------------------------------------------
# Summary CSV
# ---------------------------------------------------------------------------
def save_summary(G: nx.Graph, SG: nx.Graph, H: nx.Graph, out_csv: Path) -> None:
    degs = [d for _, d in G.degree()]
    rows = [
        {"metric": "full_nodes",         "value": G.number_of_nodes()},
        {"metric": "full_edges",         "value": G.number_of_edges()},
        {"metric": "focus_nodes",        "value": SG.number_of_nodes()},
        {"metric": "focus_edges",        "value": SG.number_of_edges()},
        {"metric": "class_nodes",        "value": H.number_of_nodes()},
        {"metric": "class_edges",        "value": H.number_of_edges()},
        {"metric": "full_mean_degree",   "value": float(np.mean(degs)) if degs else 0},
        {"metric": "full_density",       "value": nx.density(G)},
        {"metric": "focus_density",      "value": nx.density(SG) if SG.number_of_nodes() > 1 else 0},
        {"metric": "focus_transitivity", "value": nx.transitivity(SG) if SG.number_of_nodes() > 2 else 0},
    ]
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"  [Summary] → {out_csv}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="USPTO 意匠特許共引用ネットワーク可視化（論文品質 PNG）"
    )
    parser.add_argument("--ergm-dir",      default="ergm_input",
                        help="build_ergm_input.py 出力ディレクトリ (default: ergm_input)")
    parser.add_argument("--out-dir",       default="output",
                        help="出力先ディレクトリ (default: output)")
    parser.add_argument("--sim-dir",       default=None,
                        help="Gemini 類似判定 JSONL ディレクトリ（Yes ペアを重ねて表示）")
    parser.add_argument("--top-n",         type=int, default=250,
                        help="サブグラフのシードノード数 (default: 250)")
    parser.add_argument("--hops",          type=int, default=1,
                        help="BFS 拡張 hop 数 (default: 1)")
    parser.add_argument("--metric",        choices=["degree", "betweenness"], default="degree",
                        help="シード抽出メトリクス (default: degree)")
    parser.add_argument("--betweenness-k", type=int, default=300,
                        help="betweenness 近似 BFS ソース数 (default: 300)")
    args = parser.parse_args()

    ergm_dir = Path(args.ergm_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for p in (ergm_dir / "attributes.txt", ergm_dir / "arc_list.txt"):
        if not p.exists():
            print(f"エラー: {p} が見つかりません。", file=sys.stderr)
            sys.exit(1)

    # Load
    print(f"ロード中: {ergm_dir / 'attributes.txt'}")
    attrs = pd.read_csv(ergm_dir / "attributes.txt", sep="\t", low_memory=False)
    print(f"  ノード数: {len(attrs):,}")

    print(f"ロード中: {ergm_dir / 'arc_list.txt'}")
    arcs  = load_arc_list(ergm_dir / "arc_list.txt")
    edges = arcs_to_undirected_edges(arcs)
    print(f"  無向エッジ数: {len(edges):,}")

    patent_cache      = load_patent_cache(ergm_dir)
    patent_cache_keys = sorted(patent_cache.keys()) if patent_cache else None
    if patent_cache_keys:
        print(f"  patent_cache: {len(patent_cache_keys):,} 件")

    # Build graph
    print("NetworkX グラフを構築中...")
    G = build_nx_graph(len(attrs), edges, attrs, patent_cache_keys)
    compute_node_metrics(G, betweenness_k=args.betweenness_k)

    # Focus subgraph
    print(f"フォーカスサブグラフを抽出中 "
          f"(top_n={args.top_n}, hops={args.hops}, metric={args.metric})...")
    SG = extract_focus_subgraph(G, top_n=args.top_n, hops=args.hops, metric=args.metric)
    print(f"  サブグラフ: {SG.number_of_nodes():,} nodes, {SG.number_of_edges():,} edges")

    # Gemini Yes pairs
    yes_pairs: set[tuple[int, int]] | None = None
    if args.sim_dir:
        sim_dir = Path(args.sim_dir)
        if sim_dir.exists():
            print(f"Gemini Yes ペアをロード中: {sim_dir}")
            yes_pairs = load_gemini_yes_pairs(sim_dir, patent_cache_keys)
        else:
            print(f"  [Gemini] {sim_dir} が見つかりません。overlay スキップ。")

    # Generate figures
    print("図を生成中...")
    plot_patent_network(
        SG, out_dir / "network_patent_graph.png",
        yes_pairs=yes_pairs, metric=args.metric,
    )
    H = build_class_graph(G)
    plot_class_network(H, out_dir / "network_class_graph.png")
    plot_degree_distribution(G, out_dir / "network_degree_dist.png")
    save_summary(G, SG, H, out_dir / "network_summary.csv")

    print(f"\n完了 → {out_dir}/")
    print(f"  full graph  : nodes = {G.number_of_nodes():,}  edges = {G.number_of_edges():,}")
    print(f"  focus graph : nodes = {SG.number_of_nodes():,}  edges = {SG.number_of_edges():,}")
    print(f"  class graph : nodes = {H.number_of_nodes():,}  edges = {H.number_of_edges():,}")
    if yes_pairs:
        sg_yes = sum(1 for u, v in SG.edges() if (min(u, v), max(u, v)) in yes_pairs)
        print(f"  Gemini Yes  : サブグラフ内 {sg_yes:,} エッジに表示")


if __name__ == "__main__":
    # 使い方:
    #   python visualize_ergm_network.py                                         # デフォルト
    #   python visualize_ergm_network.py --top-n 300 --hops 2                   # 上位300+2hop
    #   python visualize_ergm_network.py --metric betweenness                   # BC ベース
    #   python visualize_ergm_network.py \
    #       --sim-dir /mnt/eightthdd/uspto/similarity_results                   # Gemini overlay
    main()