#!/usr/bin/env python3
"""
USPTO 意匠特許共引用 ERGM 分析スクリプト
build_ergm_input.py の出力 (ergm_input/) を対象に、
優先度1→4 の順で全分析を実施する。

優先度1: クラス分布・ヒートマップ         (attributes.txt, arc_list.txt)
優先度2: 記述統計 density/degree         (attributes.txt, arc_list.txt)
  Table 6 対応指標: density, mean_degree, transitivity, reciprocity, betweenness
  ERGM 診断:       triangle/two-path 統計
優先度3: ERGM 推定係数可視化             (EstimNetDirected 出力 *.csv)
優先度4: Gemini Yes ペアとの突合         (qwen_similarity_results/*.jsonl, attributes.txt)
Phase SW: Small-World 検証              (arc_list.txt)

出力:
  output/priority1_class_dist.png         D-class 別ノード数棒グラフ
  output/priority1_n_classes_hist.png     n_classes 分布ヒストグラム
  output/priority1_date_timeline.png      年代別ノード数折れ線
  output/priority1_cocite_heatmap.png     クラス間共引用ヒートマップ (35×35)
  output/priority2_degree_dist.png        次数分布 (PDF+CCDF × undirected/in/out)
  output/priority2_network_stats.png      transitivity / reciprocity / betweenness 棒グラフ
  output/priority2_descriptive.csv        記述統計サマリ (Table 6 完全対応)
  output/priority2_triangle_twopath.csv   ERGM 収束診断用 triangle/two-path 統計
  output/priority3_ergm_coefs.png         ERGM 係数プロット (EstimNetDirected 出力があれば)
  output/priority4_gemini_vs_class.png    Gemini Yes/No のクラス分布比較
  output/priority4_jaccard_vs_sim.png     Jaccard 類似度 vs Gemini 判定
  output/phase4_smallworld.png            Small-World λ / γ 可視化
  output/phase4_smallworld.csv            Small-World 指標 CSV
  output/analysis_summary.csv            全分析の数値サマリ

論文対応: Chakraborty et al. (2020) Table 6
  density, mean_degree, transitivity (≈0.005), reciprocity (≈0.001),
  betweenness (≈8.29e-06), λ (≈0.897), γ (≈2.346)
"""

import argparse
import json
import pickle
import sys
import warnings
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 定数
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

# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def save_meta(path: Path, caption: str, description: str = "") -> None:
    with open(str(path) + ".meta.json", "w") as f:
        json.dump({"caption": caption, "description": description}, f)


def load_arc_list(arc_path: Path) -> list[tuple[int, int]]:
    arcs = []
    with open(arc_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                arcs.append((int(parts[0]), int(parts[1])))
    return arcs


def _load_patent_cache(ergm_dir: Path) -> dict | None:
    """_patent_attr_cache.pkl をロードして返す。存在しない場合は None。"""
    cache_path = ergm_dir / "_patent_attr_cache.pkl"
    if not cache_path.exists():
        return None
    with open(cache_path, "rb") as f:
        return pickle.load(f)


# ---------------------------------------------------------------------------
# グラフデータ構築（一括）
# ---------------------------------------------------------------------------
def _build_graph_data(arcs: list[tuple[int, int]], n_nodes: int) -> dict:
    """
    アークリストから各種グラフ表現を一括構築する。
    arc_set, edges_set, adj (無向隣接), in_deg, out_deg, undir_deg を返す。
    """
    arc_set: set[tuple[int, int]] = set()
    edges_set: set[tuple[int, int]] = set()
    adj: dict[int, set[int]] = defaultdict(set)
    in_deg  = np.zeros(n_nodes, np.int32)
    out_deg = np.zeros(n_nodes, np.int32)

    for u, v in arcs:
        if u == v:
            continue
        arc_set.add((u, v))
        in_deg[v]  += 1
        out_deg[u] += 1
        key = (min(u, v), max(u, v))
        if key not in edges_set:
            edges_set.add(key)
            adj[u].add(v)
            adj[v].add(u)

    undir_deg = np.array([len(adj.get(i, ())) for i in range(n_nodes)], np.int32)
    return {
        "arc_set":   arc_set,
        "edges_set": edges_set,
        "adj":       adj,
        "in_deg":    in_deg,
        "out_deg":   out_deg,
        "undir_deg": undir_deg,
        "M":         len(edges_set),
    }


# ---------------------------------------------------------------------------
# グラフアルゴリズム
# ---------------------------------------------------------------------------
def _compute_transitivity(
    edges_set: set[tuple[int, int]],
    adj: dict[int, set[int]],
    n_nodes: int,
) -> tuple[int, int, float]:
    """
    三角形数・連結三つ組数・Transitivity（大域クラスタリング係数）を返す。
    transitivity = 3 * triangles / connected_triples
    """
    triangles = sum(
        len(adj.get(u, set()) & adj.get(v, set()))
        for u, v in edges_set
    )
    triangles //= 3  # 各三角形はエッジを跨いで3回カウントされる

    connected_triples = sum(
        len(adj.get(i, set())) * (len(adj.get(i, set())) - 1) // 2
        for i in range(n_nodes)
        if len(adj.get(i, set())) >= 2
    )
    transitivity = 3 * triangles / connected_triples if connected_triples > 0 else 0.0
    return triangles, connected_triples, transitivity


def _compute_reciprocity(arc_set: set[tuple[int, int]]) -> float:
    """有向グラフの相互性（双方向アーク数 / 全アーク数）を返す。"""
    if not arc_set:
        return 0.0
    recip = sum(1 for (u, v) in arc_set if (v, u) in arc_set)
    return recip / len(arc_set)


def _find_lcc(adj: dict[int, set[int]], n_nodes: int) -> list[int]:
    """最大連結成分（LCC）のノードリストを返す（DFS）。"""
    visited: set[int] = set()
    best: list[int] = []

    for start in range(n_nodes):
        if start in visited:
            continue
        comp: list[int] = []
        stack = [start]
        visited.add(start)
        while stack:
            node = stack.pop()
            comp.append(node)
            for nbr in adj.get(node, ()):
                if nbr not in visited:
                    visited.add(nbr)
                    stack.append(nbr)
        if len(comp) > len(best):
            best = comp

    return best


def _avg_path_length_sample(
    adj: dict[int, set[int]],
    nodes: list[int],
    k: int = 500,
    seed: int = 42,
) -> float:
    """
    k 個のランダムサンプルノードから BFS で平均最短路長を推定する。
    到達不能ノードは除外して平均を取る。
    """
    rng = np.random.default_rng(seed)
    sources = rng.choice(nodes, min(k, len(nodes)), replace=False)

    total_dist = 0
    n_pairs = 0
    for src in sources:
        dist = {src: 0}
        queue = [src]
        head = 0
        while head < len(queue):
            v = queue[head]; head += 1
            for w in adj.get(v, ()):
                if w not in dist:
                    dist[w] = dist[v] + 1
                    queue.append(w)
        for d in dist.values():
            if d > 0:
                total_dist += d
                n_pairs += 1

    return total_dist / n_pairs if n_pairs > 0 else float("inf")


def _compute_betweenness_approx(
    adj: dict[int, set[int]],
    n_nodes: int,
    k: int = 200,
    seed: int = 42,
) -> np.ndarray:
    """
    Brandes アルゴリズムの k サンプル近似で betweenness 中心性を計算する。
    正規化: (N/k) × 2/((N-1)(N-2)) （無向グラフ用）
    """
    rng = np.random.default_rng(seed)
    sources = rng.choice(n_nodes, min(k, n_nodes), replace=False)
    betweenness = np.zeros(n_nodes, np.float64)

    for s in sources:
        stack: list[int] = []
        pred: dict[int, list[int]] = defaultdict(list)
        sigma = np.zeros(n_nodes, np.float64)
        dist  = np.full(n_nodes, -1, np.int32)

        sigma[s] = 1.0
        dist[s]  = 0
        queue = [s]
        head = 0

        while head < len(queue):
            v = queue[head]; head += 1
            stack.append(v)
            for w in adj.get(v, ()):
                if dist[w] < 0:
                    queue.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        delta = np.zeros(n_nodes, np.float64)
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                betweenness[w] += delta[w]

    if n_nodes > 2:
        norm = (n_nodes / k) * 2.0 / ((n_nodes - 1) * (n_nodes - 2))
        betweenness *= norm
    return betweenness


# ===========================================================================
# 優先度 1: クラス分布・ヒートマップ
# ===========================================================================

def priority1_class_distribution(attrs: pd.DataFrame, out_dir: Path) -> None:
    """D-class 別ノード数棒グラフ"""
    counts = (
        attrs["primary_class"]
        .value_counts()
        .reindex(ALL_CLASSES, fill_value=0)
        .reset_index()
    )
    counts.columns = ["class", "count"]

    fig = px.bar(
        counts, x="class", y="count",
        title="D-class Distribution of Design Patents<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Primary class per node (ergm_input/attributes.txt)</span>",
        color="count",
        color_continuous_scale="Blues",
        text="count",
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside", cliponaxis=False)
    fig.update_xaxes(title_text="D-class")
    fig.update_yaxes(title_text="Node count")
    fig.update_layout(coloraxis_showscale=False, xaxis_tickangle=0)
    out_path = out_dir / "priority1_class_dist.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "D-class Distribution of Design Patents",
              "Bar chart showing node counts per USPTO design class (D1–D99).")
    print("  [P1] class_dist done")


def priority1_nclasses_hist(attrs: pd.DataFrame, out_dir: Path) -> None:
    """n_classes 分布ヒストグラム"""
    vc = attrs["n_classes"].value_counts().sort_index().reset_index()
    vc.columns = ["n_classes", "count"]

    fig = px.bar(
        vc, x="n_classes", y="count",
        title="Multi-class Patent Distribution<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Share of patents assigned to multiple D-classes</span>",
        text="count",
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside", cliponaxis=False)
    fig.update_xaxes(title_text="# classes")
    fig.update_yaxes(title_text="Node count")
    out_path = out_dir / "priority1_n_classes_hist.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Distribution of # D-classes per Patent",
              "Histogram showing how many D-classes each patent belongs to.")
    print("  [P1] n_classes_hist done")


def priority1_date_timeline(attrs: pd.DataFrame, out_dir: Path) -> None:
    """年代別ノード数折れ線グラフ"""
    df = attrs.copy()
    df["year"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce").dt.year
    yearly = df["year"].value_counts().sort_index().reset_index()
    yearly.columns = ["year", "count"]
    yearly = yearly.dropna().query("year >= 1970 and year <= 2030")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=yearly["year"], y=yearly["count"],
        mode="lines+markers", fill="tozeroy", line=dict(width=2), name="Nodes",
    ))
    fig.update_layout(
        title="Network Growth by Year<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Number of patents (nodes) per filing year</span>",
        showlegend=False,
    )
    fig.update_xaxes(title_text="Year")
    fig.update_yaxes(title_text="Node count")
    out_path = out_dir / "priority1_date_timeline.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Patent Network Growth Over Time",
              "Line chart showing node count growth by year.")
    print("  [P1] date_timeline done")


def priority1_cocite_heatmap(
    attrs: pd.DataFrame, arcs: list[tuple[int, int]], out_dir: Path,
) -> None:
    """クラス間共引用ヒートマップ (35×35)"""
    present = set(attrs["primary_class"].values)
    cls_list = [c for c in ALL_CLASSES if c in present]
    cls_idx  = {c: i for i, c in enumerate(cls_list)}
    node_cls = attrs["primary_class"].values

    mat = np.zeros((len(cls_list), len(cls_list)), np.int64)
    seen: set[tuple[int, int]] = set()
    for u, v in arcs:
        if u == v:
            continue
        key = (min(u, v), max(u, v))
        if key in seen:
            continue
        seen.add(key)
        cu = node_cls[u] if u < len(node_cls) else "Unknown"
        cv = node_cls[v] if v < len(node_cls) else "Unknown"
        if cu in cls_idx and cv in cls_idx:
            mat[cls_idx[cu], cls_idx[cv]] += 1
            if cu != cv:
                mat[cls_idx[cv], cls_idx[cu]] += 1

    log_mat = np.log1p(mat).astype(np.float32)
    fig = go.Figure(go.Heatmap(
        z=log_mat, x=cls_list, y=cls_list,
        colorscale="Blues", colorbar=dict(title="log(1+count)"),
        hovertemplate="From %{y} → To %{x}<br>Edges: %{customdata:,}<extra></extra>",
        customdata=mat,
    ))
    fig.update_layout(
        title="Co-citation Heatmap by D-class (35×35)<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "log(1+edge count) between primary classes</span>",
    )
    fig.update_xaxes(title_text="D-class (target)")
    fig.update_yaxes(title_text="D-class (source)")
    out_path = out_dir / "priority1_cocite_heatmap.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Co-citation Heatmap Between D-classes (35×35)",
              "Heatmap showing co-citation frequencies between USPTO design classes.")
    print("  [P1] cocite_heatmap done")


# ===========================================================================
# 優先度 2: 記述統計 / Table 6 完全対応
# ===========================================================================

def priority2_descriptive(
    attrs: pd.DataFrame,
    graph: dict,
    out_dir: Path,
    betweenness_k: int = 200,
) -> dict:
    """
    記述統計サマリ（Chakraborty et al. 2020 Table 6 完全対応）。
    transitivity / reciprocity / betweenness を追加で計算する。
    """
    N = len(attrs)
    M = graph["M"]
    undir_deg = graph["undir_deg"]
    arc_set   = graph["arc_set"]
    edges_set = graph["edges_set"]
    adj       = graph["adj"]

    max_possible = N * (N - 1) / 2
    density = M / max_possible if max_possible > 0 else 0.0

    # --- transitivity ---
    print("  [P2] transitivity を計算中...")
    n_tri, n_triples, transitivity = _compute_transitivity(edges_set, adj, N)

    # --- reciprocity ---
    reciprocity = _compute_reciprocity(arc_set)

    # --- betweenness (k-sample Brandes) ---
    print(f"  [P2] betweenness 近似計算中 (k={betweenness_k})...")
    bc = _compute_betweenness_approx(adj, N, k=betweenness_k)
    mean_betweenness = float(bc.mean())
    max_betweenness  = float(bc.max())

    # --- LCC ---
    lcc_nodes = _find_lcc(adj, N)
    lcc_size  = len(lcc_nodes)

    summary = {
        "n_nodes":          N,
        "n_edges":          M,
        "n_arcs":           len(arc_set),
        "density":          density,
        "mean_degree":      float(undir_deg.mean()),
        "median_degree":    float(np.median(undir_deg)),
        "max_degree":       int(undir_deg.max()),
        "min_degree":       int(undir_deg.min()),
        "std_degree":       float(undir_deg.std()),
        "n_isolates":       int((undir_deg == 0).sum()),
        "transitivity":     transitivity,
        "reciprocity":      reciprocity,
        "mean_betweenness": mean_betweenness,
        "max_betweenness":  max_betweenness,
        "lcc_size":         lcc_size,
        "lcc_fraction":     lcc_size / N if N > 0 else 0.0,
        "pct_multi_class":  float((attrs["n_classes"] > 1).mean() * 100),
        "unique_primary_classes": int(attrs["primary_class"].nunique()),
    }

    pd.DataFrame([summary]).to_csv(out_dir / "priority2_descriptive.csv", index=False)
    print(
        f"  [P2] N={N:,} M={M:,} density={density:.2e} "
        f"transitivity={transitivity:.4f} reciprocity={reciprocity:.4f} "
        f"mean_bc={mean_betweenness:.3e}"
    )
    return {"summary": summary, "lcc_nodes": lcc_nodes,
            "bc": bc, "n_tri": n_tri, "n_triples": n_triples}


def priority2_triangle_twopath(
    n_tri: int,
    n_triples: int,
    arcs: list[tuple[int, int]],
    adj: dict[int, set[int]],
    n_nodes: int,
    out_dir: Path,
) -> None:
    """
    ERGM 収束診断用の Triangle / Two-path 統計を CSV 保存する。
    AltKTriangleT (GWESP) と AltTwoPathsTD (GWDSP) の事前確認に使用。
    """
    # two-paths (directed): for each arc (u,v), count paths u→w→v (w ≠ u, v)
    arc_set = set(map(tuple, arcs))
    two_paths_directed = sum(
        len(adj.get(u, set()) - {v})
        for u, v in arc_set
    )

    stats = {
        "n_triangles":           n_tri,
        "n_connected_triples":   n_triples,
        "triangle_to_triple_ratio": 3 * n_tri / n_triples if n_triples > 0 else 0.0,
        "n_two_paths_directed":  two_paths_directed,
        "n_arcs":                len(arc_set),
        "two_path_per_arc":      two_paths_directed / len(arc_set) if arc_set else 0.0,
    }

    pd.DataFrame([stats]).to_csv(out_dir / "priority2_triangle_twopath.csv", index=False)
    print(
        f"  [P2] triangles={n_tri:,}  connected_triples={n_triples:,}  "
        f"two_paths_directed={two_paths_directed:,}"
    )


def priority2_degree_dist(
    undir_deg: np.ndarray,
    in_deg: np.ndarray,
    out_deg: np.ndarray,
    out_dir: Path,
) -> None:
    """
    無向・In・Out 次数の PDF + CCDF を対数軸で重ね描きする。
    """
    def _ccdf(deg_arr: np.ndarray) -> tuple[list, list]:
        d_pos = deg_arr[deg_arr > 0]
        if len(d_pos) == 0:
            return [], []
        cnt = np.bincount(d_pos)
        xs, ys, cum = [], [], 0
        for d in range(len(cnt) - 1, -1, -1):
            if cnt[d] > 0:
                cum += cnt[d]
                xs.append(d)
                ys.append(cum / len(d_pos))
        return xs[::-1], ys[::-1]

    colors = {"Undirected": "#1f77b4", "In-degree": "#2ca02c", "Out-degree": "#d62728"}

    fig = go.Figure()
    for label, deg_arr in [("Undirected", undir_deg), ("In-degree", in_deg), ("Out-degree", out_deg)]:
        d_pos = deg_arr[deg_arr > 0]
        if len(d_pos) == 0:
            continue
        cnt = np.bincount(d_pos)
        d_vals = np.arange(len(cnt))
        pdf = cnt / len(d_pos)
        # PDF (bar → scatter for log-log readability)
        fig.add_trace(go.Scatter(
            x=d_vals[d_vals > 0], y=pdf[d_vals > 0],
            mode="markers", name=f"{label} PDF",
            marker=dict(color=colors[label], size=4, opacity=0.6),
        ))
        # CCDF
        cx, cy = _ccdf(deg_arr)
        fig.add_trace(go.Scatter(
            x=cx, y=cy, mode="lines", name=f"{label} CCDF",
            line=dict(color=colors[label], width=2),
        ))

    fig.update_layout(
        title="Degree Distribution (PDF & CCDF)<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Log-log scale; undirected / in / out degree</span>",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    fig.update_xaxes(title_text="Degree", type="log")
    fig.update_yaxes(title_text="Probability", type="log")
    out_path = out_dir / "priority2_degree_dist.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Degree Distribution (PDF & CCDF)",
              "Log-log degree distribution (undirected/in/out) and CCDF.")
    print("  [P2] degree_dist done")


def priority2_network_stats(summary: dict, out_dir: Path) -> None:
    """
    Transitivity / Reciprocity / Mean Betweenness の棒グラフ。
    論文 Table 6 の主要指標を視覚化する。
    """
    metrics = {
        "Transitivity":       summary["transitivity"],
        "Reciprocity":        summary["reciprocity"],
        "Mean Betweenness":   summary["mean_betweenness"],
        "Density":            summary["density"],
    }
    # 論文参考値（Chakraborty et al. 2020）
    paper_ref = {
        "Transitivity":     0.005,
        "Reciprocity":      0.001,
        "Mean Betweenness": 8.29e-6,
        "Density":          None,
    }

    names = list(metrics.keys())
    vals  = [metrics[n] for n in names]
    refs  = [paper_ref.get(n) for n in names]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="This network", x=names, y=vals,
        text=[f"{v:.3e}" for v in vals], textposition="outside",
        marker_color="#1f77b4",
    ))
    # 参考値をライン表示（あるものだけ）
    for i, (n, r) in enumerate(zip(names, refs)):
        if r is not None:
            fig.add_shape(
                type="line", x0=i - 0.4, x1=i + 0.4,
                y0=r, y1=r,
                line=dict(color="red", width=2, dash="dash"),
            )
    # 凡例用ダミートレース
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="lines",
        line=dict(color="red", dash="dash"),
        name="Paper ref (Chakraborty 2020)",
    ))
    fig.update_layout(
        title="Network Statistics (Table 6 Comparison)<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Dashed red = paper reference values</span>",
        yaxis_type="log",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    )
    fig.update_xaxes(title_text="Metric")
    fig.update_yaxes(title_text="Value (log scale)")
    out_path = out_dir / "priority2_network_stats.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Network Statistics (Table 6 Comparison)",
              "Bar chart comparing key network statistics against paper reference values.")
    print("  [P2] network_stats done")


# ===========================================================================
# Phase SW: Small-World 検証（Chakraborty et al. 2020 Table 6）
# ===========================================================================

def _build_er_adj(n: int, m: int, seed: int) -> dict[int, set[int]]:
    """G(n, m) Erdős-Rényi ランダムグラフを rejection sampling で生成。"""
    rng = np.random.default_rng(seed)
    adj: dict[int, set[int]] = defaultdict(set)
    added = 0
    while added < m:
        u = int(rng.integers(0, n))
        v = int(rng.integers(0, n))
        if u != v and v not in adj[u]:
            adj[u].add(v)
            adj[v].add(u)
            added += 1
    return adj


def phase4_small_world(
    adj: dict[int, set[int]],
    edges_set: set[tuple[int, int]],
    n_nodes: int,
    out_dir: Path,
    er_samples: int = 5,
    path_k: int = 500,
) -> dict:
    """
    Watts-Strogatz Small-World 検証。
      λ = C_real / C_ER  （クラスタリング比）
      γ = L_real / L_ER  （平均最短路長比）
      σ = λ / γ          （Small-World index; σ >> 1 ならば Small-World）

    論文参考値: λ=0.897, γ=2.346 → σ≈0.382 （Small-World でない）
    """
    N = n_nodes
    M = len(edges_set)

    # --- LCC の特定 ---
    print("  [SW] LCC を特定中...")
    lcc_nodes = _find_lcc(adj, N)
    N_lcc = len(lcc_nodes)
    lcc_set = set(lcc_nodes)
    M_lcc = sum(1 for u, v in edges_set if u in lcc_set and v in lcc_set)

    print(f"  [SW] LCC: {N_lcc:,} nodes ({N_lcc/N*100:.1f}%), {M_lcc:,} edges")

    # --- C_real（実ネットワークの Transitivity） ---
    _, _, c_real = _compute_transitivity(edges_set, adj, N)

    # --- L_real（LCC の平均最短路長、BFS サンプリング） ---
    print(f"  [SW] L_real を BFS サンプリング中 (k={path_k})...")
    l_real = _avg_path_length_sample(adj, lcc_nodes, k=path_k, seed=42)

    # --- C_ER（解析値: ER グラフの期待クラスタリング = 密度） ---
    c_er = 2 * M_lcc / (N_lcc * (N_lcc - 1)) if N_lcc > 1 else 0.0

    # --- L_ER（ER ランダムグラフのシミュレーション） ---
    # er_samples=0 の場合は解析近似 ln(N)/ln(k_avg) を使用
    k_avg_lcc = 2 * M_lcc / N_lcc if N_lcc > 0 else 1.0
    l_er_analytic = np.log(N_lcc) / np.log(k_avg_lcc) if k_avg_lcc > 1 else float("inf")

    if er_samples > 0:
        print(f"  [SW] ER ランダムグラフ {er_samples} 回シミュレーション中...")
        l_er_sims = []
        for trial in range(er_samples):
            er_adj = _build_er_adj(N_lcc, M_lcc, seed=42 + trial)
            er_nodes = list(range(N_lcc))
            l_sim = _avg_path_length_sample(
                er_adj, er_nodes, k=min(100, N_lcc), seed=42 + trial,
            )
            l_er_sims.append(l_sim)
            print(f"    trial {trial+1}/{er_samples}: L_ER={l_sim:.4f}")
        l_er = float(np.mean(l_er_sims))
        l_er_std = float(np.std(l_er_sims))
    else:
        l_er = l_er_analytic
        l_er_std = 0.0

    lam   = c_real / c_er  if c_er  > 0 else float("inf")
    gam   = l_real / l_er  if l_er  > 0 and l_er != float("inf") else float("inf")
    sigma = lam    / gam   if gam   > 0 and gam   != float("inf") else float("inf")
    is_sw = sigma > 1.0 and gam < 2.0

    print(
        f"  [SW] C_real={c_real:.5f}  L_real={l_real:.4f}\n"
        f"       C_ER  ={c_er:.5f}  L_ER  ={l_er:.4f} (analytic={l_er_analytic:.4f})\n"
        f"       λ={lam:.4f}  γ={gam:.4f}  σ={sigma:.4f}  "
        f"→ {'Small-World' if is_sw else 'NOT Small-World'}"
    )

    result = {
        "N_lcc": N_lcc, "M_lcc": M_lcc,
        "C_real": c_real, "L_real": l_real,
        "C_ER":  c_er,   "L_ER":  l_er, "L_ER_std": l_er_std,
        "L_ER_analytic": l_er_analytic,
        "lambda": lam, "gamma": gam, "sigma": sigma,
        "is_small_world": is_sw,
        "paper_lambda": 0.897, "paper_gamma": 2.346,
    }
    pd.DataFrame([result]).to_csv(out_dir / "phase4_smallworld.csv", index=False)

    # --- プロット ---
    fig = go.Figure()

    # λ / γ 比較バー（実測 vs 論文）
    categories = ["λ (C_real/C_ER)", "γ (L_real/L_ER)"]
    this_vals  = [lam, gam]
    paper_vals = [0.897, 2.346]

    fig.add_trace(go.Bar(
        name="This network", x=categories, y=this_vals,
        text=[f"{v:.3f}" for v in this_vals], textposition="outside",
        marker_color="#1f77b4",
    ))
    fig.add_trace(go.Bar(
        name="Paper (Chakraborty 2020)", x=categories, y=paper_vals,
        text=[f"{v:.3f}" for v in paper_vals], textposition="outside",
        marker_color="#ff7f0e", opacity=0.6,
    ))
    fig.add_hline(y=1.0, line_dash="dash", line_color="gray", line_width=1,
                  annotation_text="1.0 (ER baseline)")

    fig.update_layout(
        barmode="group",
        title=(
            f"Small-World Analysis (λ={lam:.3f}, γ={gam:.3f}, σ={sigma:.3f})<br>"
            "<span style='font-size:13px;font-weight:normal;'>"
            f"{'✓ Small-World (σ>1)' if is_sw else '✗ Not Small-World (σ≤1)'}"
            " | Paper ref: λ=0.897, γ=2.346</span>"
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.08, xanchor="center", x=0.5),
    )
    fig.update_xaxes(title_text="Metric")
    fig.update_yaxes(title_text="Ratio (real / ER random)")
    out_path = out_dir / "phase4_smallworld.png"
    fig.write_image(str(out_path))
    save_meta(out_path, f"Small-World Analysis (λ={lam:.3f}, γ={gam:.3f})",
              "Comparison of clustering and path-length ratios against ER random graph.")
    print("  [SW] smallworld done")
    return result


# ===========================================================================
# 優先度 3: ERGM 推定係数可視化
# ===========================================================================

def priority3_ergm_coefs(ergm_dir: Path, out_dir: Path) -> bool:
    """
    EstimNetDirected の出力 CSV (*theta*.csv 等) を読み込んで係数プロットを生成。
    ファイルが存在しない場合は False を返してスキップ。
    """
    candidates = list(ergm_dir.glob("*theta*.csv")) + list(ergm_dir.glob("*coef*.csv"))
    if not candidates:
        print("  [P3] EstimNetDirected 出力が見つかりません。スキップします。")
        print(f"       探索パス: {ergm_dir}")
        return False

    coef_path = sorted(candidates)[-1]
    print(f"  [P3] 係数ファイル: {coef_path}")
    df = pd.read_csv(coef_path)

    col_map = {}
    for col in df.columns:
        lc = col.lower().strip()
        if lc in ("param", "parameter", "term", "name", "statistic"):
            col_map[col] = "param"
        elif lc in ("theta", "estimate", "coef", "coefficient"):
            col_map[col] = "theta"
        elif lc in ("stderr", "se", "std_error", "std.error"):
            col_map[col] = "se"
    df = df.rename(columns=col_map)

    if "param" not in df.columns or "theta" not in df.columns:
        print(f"  [P3] 列 'param'/'theta' が見つかりません。列: {df.columns.tolist()}")
        return False

    df["theta"] = pd.to_numeric(df["theta"], errors="coerce")
    df = df.dropna(subset=["theta"])

    if "se" in df.columns:
        df["se"] = pd.to_numeric(df["se"], errors="coerce").fillna(0)
        df["ci_low"]  = df["theta"] - 1.96 * df["se"]
        df["ci_high"] = df["theta"] + 1.96 * df["se"]
    else:
        df["ci_low"]  = df["theta"]
        df["ci_high"] = df["theta"]

    df = df[~df["param"].str.contains("date", case=False, na=False)]
    df = df.sort_values("theta")
    colors = ["#d62728" if t > 0 else "#1f77b4" for t in df["theta"]]

    fig = go.Figure()
    for _, row in df.iterrows():
        fig.add_shape(
            type="line",
            x0=row["ci_low"], x1=row["ci_high"],
            y0=row["param"],  y1=row["param"],
            line=dict(color="gray", width=1),
        )
    fig.add_trace(go.Scatter(
        x=df["theta"], y=df["param"],
        mode="markers", marker=dict(color=colors, size=8), name="θ",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="black", line_width=1)
    fig.update_layout(
        title="ERGM Coefficients (EstimNetDirected)<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Red=positive, Blue=negative; bars=95% CI</span>",
        showlegend=False,
    )
    fig.update_xaxes(title_text="θ estimate")
    fig.update_yaxes(title_text="Parameter", automargin=True)
    out_path = out_dir / "priority3_ergm_coefs.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "ERGM Coefficients (EstimNetDirected)",
              "Forest plot of ERGM parameter estimates with 95% CIs.")
    print("  [P3] ergm_coefs done")
    return True


# ===========================================================================
# 優先度 4: Gemini Yes ペアとの突合
# ===========================================================================

def _load_similarity_results(sim_dir: Path) -> pd.DataFrame | None:
    records = []
    for p in sorted(sim_dir.glob("*.jsonl")):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return pd.DataFrame(records) if records else None


def _normalize_sim_cols(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {}
    for col in df.columns:
        lc = col.lower()
        if lc in ("source", "patent_a", "id_a", "src", "patent1"):
            col_map[col] = "id_a"
        elif lc in ("target", "patent_b", "id_b", "tgt", "patent2"):
            col_map[col] = "id_b"
        elif lc in ("similarity", "label", "result", "similar"):
            col_map[col] = "similarity"
    return df.rename(columns=col_map)


def priority4_gemini_vs_class(
    patent_cache: dict | None, sim_dir: Path, out_dir: Path,
) -> bool:
    sim_df = _load_similarity_results(sim_dir)
    if sim_df is None:
        print("  [P4] similarity_results が見つかりません。スキップします。")
        return False

    sim_df = _normalize_sim_cols(sim_df)
    if "similarity" not in sim_df.columns:
        print(f"  [P4] 'similarity' 列が見つかりません。列: {sim_df.columns.tolist()}")
        return False

    is_yes = sim_df["similarity"].astype(str).str.lower().isin(["yes", "true", "1", "similar"])
    df_yes = sim_df[is_yes]
    df_no  = sim_df[~is_yes]

    if patent_cache is not None and "id_a" in sim_df.columns:
        def _get_primary(pid: str) -> str:
            return patent_cache.get(str(pid), {}).get("primary_class", "Unknown")

        sim_df["cls_a"]     = sim_df["id_a"].map(_get_primary)
        sim_df["same_class"] = sim_df["cls_a"] == sim_df["id_b"].map(_get_primary)

        yes_cls = sim_df[is_yes]["cls_a"].value_counts().reindex(ALL_CLASSES, fill_value=0)
        no_cls  = sim_df[~is_yes]["cls_a"].value_counts().reindex(ALL_CLASSES, fill_value=0)

        fig = go.Figure()
        fig.add_trace(go.Bar(name="Gemini: Yes", x=ALL_CLASSES, y=yes_cls.values))
        fig.add_trace(go.Bar(name="Gemini: No",  x=ALL_CLASSES, y=no_cls.values))
        fig.update_layout(
            barmode="group",
            title="Gemini Similarity by D-class<br>"
                  "<span style='font-size:14px;font-weight:normal;'>"
                  "Yes/No distribution across USPTO design classes</span>",
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
        )
        fig.update_xaxes(title_text="D-class")
        fig.update_yaxes(title_text="Pair count")
        out_path = out_dir / "priority4_gemini_vs_class.png"
        fig.write_image(str(out_path))
        save_meta(out_path, "Gemini Similarity Judgment by D-class",
                  "Grouped bar chart comparing Yes/No Gemini judgments across D-classes.")

        same_yes = sim_df[sim_df["same_class"]]["similarity"].astype(str).str.lower().isin(
            ["yes", "true", "1", "similar"]).mean()
        diff_yes = sim_df[~sim_df["same_class"]]["similarity"].astype(str).str.lower().isin(
            ["yes", "true", "1", "similar"]).mean()
        print(
            f"  [P4] same_class Yes率: {same_yes*100:.1f}%  "
            f"diff_class Yes率: {diff_yes*100:.1f}%"
        )
    else:
        print("  [P4] patent_cache が利用できないため、クラス別集計をスキップします。")

    print(f"  [P4] gemini_vs_class done  total_pairs={len(sim_df):,} yes={len(df_yes):,}")
    return True


def priority4_jaccard_vs_sim(
    patent_cache: dict | None,
    sim_dir: Path,
    out_dir: Path,
    jac_path: Path,
    node_list: list[str] | None = None,
) -> bool:
    if not jac_path.exists():
        print(f"  [P4] {jac_path.name} が見つかりません。スキップします。")
        return False

    sim_df = _load_similarity_results(sim_dir)
    if sim_df is None:
        print("  [P4] similarity_results が見つかりません。スキップします。")
        return False

    sim_df = _normalize_sim_cols(sim_df)
    if "id_a" not in sim_df.columns or "id_b" not in sim_df.columns:
        print("  [P4] id_a / id_b 列が見つかりません。スキップします。")
        return False

    if node_list is not None:
        id_to_row = {pid: i for i, pid in enumerate(node_list)}
    elif patent_cache is not None:
        print("  [P4] node_list 未指定。patent_cache のソート済みキーで代用します。")
        id_to_row = {pid: i for i, pid in enumerate(sorted(patent_cache.keys()))}
    else:
        print("  [P4] ノード順が不明なため Jaccard 分析をスキップします。")
        return False

    print(f"  [P4] Jaccard 行列をメモリマップでロード中: {jac_path}")
    jac = np.load(str(jac_path), mmap_mode="r")

    jac_vals, labels = [], []
    for _, row in sim_df.head(50_000).iterrows():
        i = id_to_row.get(str(row.get("id_a", "")))
        j = id_to_row.get(str(row.get("id_b", "")))
        if i is None or j is None or i >= jac.shape[0] or j >= jac.shape[1]:
            continue
        jac_vals.append(float(jac[i, j]))
        lbl = str(row.get("similarity", "")).lower()
        labels.append("Yes" if lbl in ("yes", "true", "1", "similar") else "No")

    if not jac_vals:
        print("  [P4] Jaccard マッチングでペアが見つかりません。スキップします。")
        return False

    df_plot = pd.DataFrame({"jaccard": jac_vals, "gemini": labels})
    fig = px.box(
        df_plot, x="gemini", y="jaccard", color="gemini",
        title="Jaccard Similarity vs Gemini Judgment<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "D-class Jaccard score for Gemini Yes/No pairs</span>",
        points="outliers",
    )
    fig.update_xaxes(title_text="Gemini result")
    fig.update_yaxes(title_text="Jaccard score")
    fig.update_layout(showlegend=False)
    out_path = out_dir / "priority4_jaccard_vs_sim.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Jaccard Similarity vs Gemini Judgment",
              "Boxplot comparing D-class Jaccard scores between Gemini Yes and No pairs.")
    print(f"  [P4] jaccard_vs_sim done  matched_pairs={len(jac_vals):,}")
    return True


# ===========================================================================
# 分析サマリ CSV
# ===========================================================================

def save_analysis_summary(summary: dict, sw_result: dict | None, out_dir: Path) -> None:
    rows = [{"metric": k, "value": v} for k, v in summary.items()]
    if sw_result:
        rows += [{"metric": f"sw_{k}", "value": v} for k, v in sw_result.items()]
    pd.DataFrame(rows).to_csv(out_dir / "analysis_summary.csv", index=False)
    print(f"  [Summary] {out_dir / 'analysis_summary.csv'}")


# ===========================================================================
# メイン
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="USPTO 意匠特許 ERGM 分析スクリプト（優先度 1–4 + Small-World）"
    )
    parser.add_argument(
        "--ergm-dir", default="ergm_input",
        help="build_ergm_input.py の出力ディレクトリ (default: ergm_input)",
    )
    parser.add_argument(
        "--sim-dir", default="/mnt/eightthdd/uspto/qwen_similarity_results",
        help="類似判定 jsonl のディレクトリ",
    )
    parser.add_argument(
        "--out-dir", default="output",
        help="グラフ・CSV の出力先 (default: output)",
    )
    parser.add_argument(
        "--betweenness-k", type=int, default=200, metavar="K",
        help="Betweenness 近似の BFS ソース数 (default: 200)",
    )
    parser.add_argument(
        "--er-samples", type=int, default=5, metavar="N",
        help="Small-World の ER ランダムグラフ試行数 (default: 5, 0=解析近似のみ)",
    )
    parser.add_argument("--skip-p3", action="store_true",
                        help="優先度3（ERGM係数可視化）をスキップ")
    parser.add_argument("--skip-p4", action="store_true",
                        help="優先度4（Gemini突合）をスキップ")
    parser.add_argument("--skip-sw", action="store_true",
                        help="Small-World 検証をスキップ")
    args = parser.parse_args()

    ergm_dir = Path(args.ergm_dir)
    sim_dir  = Path(args.sim_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    attr_path = ergm_dir / "attributes.txt"
    arc_path  = ergm_dir / "arc_list.txt"
    jac_path  = ergm_dir / "class_sim_jaccard.npy"

    for p in (attr_path, arc_path):
        if not p.exists():
            print(f"エラー: {p} が見つかりません。", file=sys.stderr)
            sys.exit(1)

    print(f"ロード中: {attr_path}")
    attrs = pd.read_csv(attr_path, sep="\t", low_memory=False)
    N = len(attrs)
    print(f"  ノード数: {N:,}")

    print(f"ロード中: {arc_path}")
    arcs = load_arc_list(arc_path)
    print(f"  アーク数: {len(arcs):,}")

    print("グラフデータ構築中...")
    graph = _build_graph_data(arcs, N)
    print(f"  無向エッジ数: {graph['M']:,}")

    patent_cache = _load_patent_cache(ergm_dir)
    if patent_cache:
        print(f"  patent_cache ロード済み: {len(patent_cache):,} 件")
    else:
        print("  patent_cache なし（P4 クラス別集計は制限されます）")

    # ---------- 優先度 1 ----------
    print("\n=== 優先度1: クラス分布・ヒートマップ ===")
    priority1_class_distribution(attrs, out_dir)
    priority1_nclasses_hist(attrs, out_dir)
    priority1_date_timeline(attrs, out_dir)
    priority1_cocite_heatmap(attrs, arcs, out_dir)

    # ---------- 優先度 2 ----------
    print("\n=== 優先度2: 記述統計（Table 6 完全対応） ===")
    p2 = priority2_descriptive(attrs, graph, out_dir, betweenness_k=args.betweenness_k)
    priority2_triangle_twopath(
        p2["n_tri"], p2["n_triples"], arcs, graph["adj"], N, out_dir,
    )
    priority2_degree_dist(
        graph["undir_deg"], graph["in_deg"], graph["out_deg"], out_dir,
    )
    priority2_network_stats(p2["summary"], out_dir)

    # ---------- 優先度 3 ----------
    if not args.skip_p3:
        print("\n=== 優先度3: ERGM 係数可視化 ===")
        priority3_ergm_coefs(ergm_dir, out_dir)

    # ---------- 優先度 4 ----------
    if not args.skip_p4:
        if sim_dir.exists():
            print("\n=== 優先度4: Gemini 突合 ===")
            priority4_gemini_vs_class(patent_cache, sim_dir, out_dir)
            priority4_jaccard_vs_sim(patent_cache, sim_dir, out_dir, jac_path)
        else:
            print(f"\n=== 優先度4: {sim_dir} が存在しません。スキップします。===")

    # ---------- Small-World ----------
    sw_result: dict | None = None
    if not args.skip_sw:
        print("\n=== Small-World 検証（Chakraborty et al. 2020 Table 6） ===")
        sw_result = phase4_small_world(
            graph["adj"], graph["edges_set"], N, out_dir,
            er_samples=args.er_samples,
        )

    # ---------- サマリ ----------
    summary = p2["summary"]
    save_analysis_summary(summary, sw_result, out_dir)

    print(f"\n完了 → {out_dir}/")
    print(f"  ノード数:          {summary['n_nodes']:,}")
    print(f"  エッジ数:          {summary['n_edges']:,}")
    print(f"  密度:              {summary['density']:.3e}")
    print(f"  平均次数:          {summary['mean_degree']:.2f}")
    print(f"  Transitivity:      {summary['transitivity']:.5f}")
    print(f"  Reciprocity:       {summary['reciprocity']:.5f}")
    print(f"  Mean Betweenness:  {summary['mean_betweenness']:.3e}")
    if sw_result:
        print(f"  λ (C_real/C_ER):  {sw_result['lambda']:.4f}")
        print(f"  γ (L_real/L_ER):  {sw_result['gamma']:.4f}")
        print(f"  σ (SW index):      {sw_result['sigma']:.4f}")


if __name__ == "__main__":
    # 使い方:
    #   python analyze_ergm.py                            # デフォルト（全分析）
    #   python analyze_ergm.py --skip-p3 --skip-p4       # 記述統計のみ高速実行
    #   python analyze_ergm.py --skip-sw                  # Small-World をスキップ
    #   python analyze_ergm.py --betweenness-k 1000      # Betweenness 精度を上げる
    #   python analyze_ergm.py --er-samples 10           # ER 試行数を増やす
    #   python analyze_ergm.py --er-samples 0            # ER 解析近似のみ（高速）
    #   python analyze_ergm.py --out-dir ./my_output     # 出力先を変更
    main()