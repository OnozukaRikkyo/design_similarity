#!/usr/bin/env python3
"""
USPTO 意匠特許共引用ネットワーク可視化スクリプト

build_ergm_input.py の出力 (ergm_input/) をもとに、
分類コードと共引用の構造を直感的に確認できるネットワーク可視化を生成する。

出力:
  output/network_patent_graph.html   特許ノードのインタラクティブ可視化（サブグラフ）
  output/network_class_graph.html    D-class 集約ネットワーク（インタラクティブ）
  output/network_class_graph.png     D-class 集約ネットワーク（静止画）
  output/network_summary.csv         可視化対象グラフの要約統計

特徴:
  - ノード色:    primary_class (D-class 別カラー)
  - ノードサイズ: degree または betweenness
  - 特許図:      高次数/高 betweenness ノード上位 N 件 + 1-hop 隣接を表示
  - D-class 図:  クラス間共引用本数をエッジ太さで表示、ノードサイズは特許数
  - HTML:        Plotly ベース、hover に patent_id / class / date / degree を表示
  - Gemini Yes ペアをエッジとして重ねて表示可能 (--sim-dir)

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

import networkx as nx
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 定数（analyze_ergm.py と共通）
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

# 35クラス分のカラーパレット
_PAL = (
    px.colors.qualitative.Alphabet      # 26色
    + px.colors.qualitative.Dark24      # 24色
    + px.colors.qualitative.Light24     # 24色
)
CLASS_COLORS: dict[str, str] = {cls: _PAL[i % len(_PAL)] for i, cls in enumerate(ALL_CLASSES)}
CLASS_COLORS["Unknown"] = "#9aa0a6"


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def save_meta(path: Path, caption: str, description: str = "") -> None:
    with open(str(path) + ".meta.json", "w", encoding="utf-8") as f:
        json.dump({"caption": caption, "description": description}, f, ensure_ascii=False)


def load_arc_list(arc_path: Path) -> list[tuple[int, int]]:
    arcs = []
    with open(arc_path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                arcs.append((int(parts[0]), int(parts[1])))
    return arcs


def arcs_to_undirected_edges(arcs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """双方向アーク → 無向エッジリスト（重複除去）"""
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


def _node_id_label(i: int, patent_cache_keys: list[str] | None) -> str:
    """ノードインデックス → 特許ID文字列（キャッシュがあれば実ID）"""
    if patent_cache_keys and i < len(patent_cache_keys):
        return patent_cache_keys[i]
    return str(i)


# ---------------------------------------------------------------------------
# NetworkX グラフ構築
# ---------------------------------------------------------------------------
def build_nx_graph(
    n_nodes: int,
    edges: list[tuple[int, int]],
    attrs: pd.DataFrame,
    patent_cache_keys: list[str] | None = None,
) -> nx.Graph:
    """
    NetworkX グラフを構築し、各ノードに属性（primary_class, n_classes, date, patent_id）を付与する。
    """
    G = nx.Graph()
    G.add_nodes_from(range(n_nodes))
    G.add_edges_from(edges)

    for i in range(n_nodes):
        if i >= len(attrs):
            break
        row = attrs.iloc[i]
        G.nodes[i]["primary_class"] = str(row.get("primary_class", "Unknown"))
        G.nodes[i]["n_classes"]     = int(row.get("n_classes", 0))
        G.nodes[i]["date"]          = str(row.get("date", ""))
        G.nodes[i]["patent_id"]     = _node_id_label(i, patent_cache_keys)

    return G


def compute_node_metrics(
    G: nx.Graph,
    betweenness_k: int = 300,
    seed: int = 42,
) -> None:
    """
    degree と betweenness centrality を計算して G のノード属性に追加する。
    N > 500 の場合は k-sample 近似を使用する。
    """
    print(f"  [Graph] degree を計算中...")
    deg = dict(G.degree())
    nx.set_node_attributes(G, deg, "degree")

    N = G.number_of_nodes()
    print(f"  [Graph] betweenness を計算中 (k={betweenness_k}, N={N:,})...")
    if N <= max(betweenness_k, 500):
        bc = nx.betweenness_centrality(G, normalized=True)
    else:
        bc = nx.betweenness_centrality(G, k=betweenness_k, normalized=True, seed=seed)
    nx.set_node_attributes(G, bc, "betweenness")


# ---------------------------------------------------------------------------
# サブグラフ抽出
# ---------------------------------------------------------------------------
def extract_focus_subgraph(
    G: nx.Graph,
    top_n: int = 250,
    hops: int = 1,
    metric: str = "degree",
) -> nx.Graph:
    """
    指定メトリクスの上位 top_n ノードをシードとし、hops 分の隣接ノードを加えたサブグラフを返す。
    """
    vals = nx.get_node_attributes(G, metric)
    if not vals:
        raise ValueError(f"ノード属性 '{metric}' が存在しません。compute_node_metrics() を先に実行してください。")

    seeds = [n for n, _ in sorted(vals.items(), key=lambda x: x[1], reverse=True)[:top_n]]
    selected = set(seeds)

    frontier = set(seeds)
    for _ in range(hops):
        next_frontier: set[int] = set()
        for u in frontier:
            next_frontier.update(G.neighbors(u))
        next_frontier -= selected
        selected |= next_frontier
        frontier = next_frontier

    SG = G.subgraph(sorted(selected)).copy()
    return SG


# ---------------------------------------------------------------------------
# Gemini Yes ペアの読み込み
# ---------------------------------------------------------------------------
def load_gemini_yes_pairs(
    sim_dir: Path,
    patent_cache_keys: list[str] | None,
) -> set[tuple[int, int]]:
    """
    similarity_results/*.jsonl から similarity=Yes のペアを読み込み、
    (min_idx, max_idx) の集合を返す。patent_cache_keys がない場合は空セット。
    """
    if patent_cache_keys is None:
        print("  [Gemini] patent_cache がないためノードID変換不可。Gemini overlay をスキップします。")
        return set()

    id_to_row: dict[str, int] = {pid: i for i, pid in enumerate(patent_cache_keys)}
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
                sim = str(rec.get("similarity", "")).lower()
                if sim not in ("yes", "true", "1", "similar"):
                    continue
                src = str(rec.get("source", rec.get("patent_a", rec.get("id_a", ""))))
                tgt = str(rec.get("target", rec.get("patent_b", rec.get("id_b", ""))))
                i = id_to_row.get(src)
                j = id_to_row.get(tgt)
                if i is not None and j is not None:
                    yes_pairs.add((min(i, j), max(i, j)))
                    n_loaded += 1

    print(f"  [Gemini] Yes ペア: {n_loaded:,} 件ロード済み")
    return yes_pairs


# ---------------------------------------------------------------------------
# 特許レベルのインタラクティブ HTML
# ---------------------------------------------------------------------------
def make_patent_network_html(
    SG: nx.Graph,
    out_path: Path,
    title: str,
    yes_pairs: set[tuple[int, int]] | None = None,
) -> None:
    """
    特許ノードのインタラクティブ Plotly HTML を生成する。
    - ノード色: primary_class
    - ノードサイズ: log(degree + 1)
    - Gemini Yes ペアを橙色エッジで重ね描き（yes_pairs が指定された場合）
    """
    N_sg = SG.number_of_nodes()
    iterations = max(30, min(100, 10000 // max(N_sg, 1)))
    print(f"  [PatentGraph] spring layout ({N_sg:,} nodes, iterations={iterations})...")
    pos = nx.spring_layout(SG, seed=42, iterations=iterations)

    # --- 通常エッジ ---
    ex, ey = [], []
    yes_set = yes_pairs or set()
    yes_ex, yes_ey = [], []

    for u, v in SG.edges():
        key = (min(u, v), max(u, v))
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        if key in yes_set:
            yes_ex += [x0, x1, None]
            yes_ey += [y0, y1, None]
        else:
            ex += [x0, x1, None]
            ey += [y0, y1, None]

    traces: list[go.BaseTraceType] = []
    traces.append(go.Scatter(
        x=ex, y=ey, mode="lines",
        line=dict(width=0.5, color="rgba(150,150,150,0.3)"),
        hoverinfo="skip", showlegend=False,
    ))
    if yes_ex:
        traces.append(go.Scatter(
            x=yes_ex, y=yes_ey, mode="lines",
            line=dict(width=1.5, color="rgba(255,127,14,0.6)"),
            name="Gemini: Yes", showlegend=True,
        ))

    # --- ノードトレース（クラス別） ---
    classes_present = sorted({SG.nodes[n].get("primary_class", "Unknown") for n in SG.nodes()})
    for cls in classes_present:
        xs, ys, texts, sizes = [], [], [], []
        for n in SG.nodes():
            if SG.nodes[n].get("primary_class", "Unknown") != cls:
                continue
            x, y = pos[n]
            xs.append(x)
            ys.append(y)
            deg = SG.nodes[n].get("degree", 0)
            bc  = SG.nodes[n].get("betweenness", 0.0)
            sizes.append(8 + 18 * np.log1p(max(deg, 1)) / np.log(10))
            texts.append(
                f"patent_id={SG.nodes[n].get('patent_id', n)}<br>"
                f"class={cls}  ({CLASS_NAMES.get(cls, '')})<br>"
                f"date={SG.nodes[n].get('date', '')}<br>"
                f"degree={deg}  betweenness={bc:.4g}<br>"
                f"n_classes={SG.nodes[n].get('n_classes', 0)}"
            )
        traces.append(go.Scatter(
            x=xs, y=ys, mode="markers",
            name=f"{cls}",
            text=texts,
            hovertemplate="%{text}<extra></extra>",
            marker=dict(
                size=sizes,
                color=CLASS_COLORS.get(cls, "#888"),
                line=dict(width=0.4, color="white"),
                opacity=0.88,
            ),
        ))

    fig = go.Figure(traces)
    fig.update_layout(
        title=dict(
            text=(
                title + "<br>"
                "<span style='font-size:15px;font-weight:normal;'>"
                "node color = primary class | size = degree | hover for details"
                "</span>"
            ),
        ),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        hovermode="closest",
        legend=dict(
            orientation="v", yanchor="top", y=1,
            xanchor="left", x=1.02, font=dict(size=10),
        ),
        width=1400, height=900,
    )
    fig.write_html(str(out_path), include_plotlyjs="cdn")
    save_meta(out_path,
              "Patent-level Co-citation Network",
              "Interactive patent network colored by D-class and sized by degree.")
    print(f"  [PatentGraph] → {out_path}")


# ---------------------------------------------------------------------------
# D-class 集約グラフ
# ---------------------------------------------------------------------------
def build_class_graph(G: nx.Graph) -> nx.Graph:
    """
    特許グラフを D-class 単位に集約する。
    - ノード属性: count（特許数）, internal_edges（クラス内エッジ数）
    - エッジ属性: weight（クラス間エッジ数）
    """
    H: nx.Graph = nx.Graph()

    # ノード初期化（全クラス + Unknown）
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

    # ノード数 0 のクラスは除去
    isolates = [n for n in H.nodes() if H.nodes[n]["count"] == 0]
    H.remove_nodes_from(isolates)
    return H


def make_class_network_plots(
    H: nx.Graph,
    out_html: Path,
    out_png: Path,
) -> None:
    """
    D-class 集約グラフの HTML + PNG を生成する。
    - エッジ太さ: クラス間共引用エッジ数（log スケール）
    - ノードサイズ: 特許数（log スケール）
    - ノード色: D-class カラー
    """
    if H.number_of_nodes() == 0:
        return

    pos = nx.spring_layout(H, seed=42, weight="weight", iterations=200)
    weights = [d.get("weight", 1) for _, _, d in H.edges(data=True)]
    w_max = max(weights) if weights else 1

    # エッジトレース（1本ずつ → hover にエッジ情報を載せる）
    edge_traces: list[go.BaseTraceType] = []
    for u, v, d in H.edges(data=True):
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        w = d.get("weight", 1)
        width = 0.5 + 9.5 * np.log1p(w) / np.log1p(w_max)
        edge_traces.append(go.Scatter(
            x=[x0, x1, None], y=[y0, y1, None],
            mode="lines",
            line=dict(width=width, color="rgba(100,100,100,0.4)"),
            hovertemplate=f"{u} ↔ {v}<br>co-cite edges: {w:,}<extra></extra>",
            showlegend=False,
        ))

    # ノードトレース
    node_x, node_y, node_sizes, node_colors, hover_texts, node_labels = [], [], [], [], [], []
    for n, d in H.nodes(data=True):
        x, y = pos[n]
        node_x.append(x)
        node_y.append(y)
        count = d.get("count", 0)
        internal = d.get("internal_edges", 0)
        total_external = H.degree(n, weight="weight")
        node_sizes.append(20 + 30 * np.log1p(max(count, 1)) / np.log1p(H.nodes[n]["count"] + 1))
        node_sizes[-1] = 20 + 30 * np.log1p(count) / max(1, np.log(max(count, 2)))
        node_colors.append(CLASS_COLORS.get(n, "#888"))
        node_labels.append(n)
        hover_texts.append(
            f"<b>{n}</b> — {CLASS_NAMES.get(n, '')}<br>"
            f"patents: {count:,}<br>"
            f"internal co-cite edges: {internal:,}<br>"
            f"external co-cite edges: {total_external:,}"
        )

    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode="markers+text",
        text=node_labels,
        textposition="top center",
        textfont=dict(size=10),
        hovertemplate="%{customdata}<extra></extra>",
        customdata=hover_texts,
        marker=dict(
            size=node_sizes,
            color=node_colors,
            line=dict(width=1, color="white"),
            opacity=0.92,
        ),
        showlegend=False,
    )

    fig = go.Figure(edge_traces + [node_trace])
    fig.update_layout(
        title=dict(
            text=(
                "D-class Co-citation Network (aggregated)<br>"
                "<span style='font-size:15px;font-weight:normal;'>"
                "node size = patent count | edge width = inter-class co-citation"
                "</span>"
            ),
        ),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        hovermode="closest",
        width=1200, height=900,
    )
    fig.write_html(str(out_html), include_plotlyjs="cdn")
    fig.write_image(str(out_png))
    save_meta(out_html,
              "D-class Co-citation Network",
              "Interactive class-level network. Edge width = inter-class co-citations.")
    save_meta(out_png,
              "D-class Co-citation Network",
              "Static class-level network showing co-citation between D-classes.")
    print(f"  [ClassGraph] → {out_html}")
    print(f"  [ClassGraph] → {out_png}")


# ---------------------------------------------------------------------------
# 要約 CSV
# ---------------------------------------------------------------------------
def save_summary(
    G: nx.Graph,
    SG: nx.Graph,
    H: nx.Graph,
    out_csv: Path,
) -> None:
    degs = [d for _, d in G.degree()]
    rows = [
        {"metric": "full_nodes",            "value": G.number_of_nodes()},
        {"metric": "full_edges",            "value": G.number_of_edges()},
        {"metric": "focus_nodes",           "value": SG.number_of_nodes()},
        {"metric": "focus_edges",           "value": SG.number_of_edges()},
        {"metric": "class_nodes",           "value": H.number_of_nodes()},
        {"metric": "class_edges",           "value": H.number_of_edges()},
        {"metric": "full_mean_degree",      "value": float(np.mean(degs)) if degs else 0},
        {"metric": "full_density",          "value": nx.density(G)},
        {"metric": "focus_density",         "value": nx.density(SG) if SG.number_of_nodes() > 1 else 0},
        {"metric": "focus_transitivity",    "value": nx.transitivity(SG) if SG.number_of_nodes() > 2 else 0},
    ]
    pd.DataFrame(rows).to_csv(out_csv, index=False)
    print(f"  [Summary]    → {out_csv}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="USPTO 意匠特許共引用ネットワーク可視化"
    )
    parser.add_argument("--ergm-dir", default="ergm_input",
                        help="build_ergm_input.py の出力ディレクトリ (default: ergm_input)")
    parser.add_argument("--out-dir", default="output",
                        help="出力ディレクトリ (default: output)")
    parser.add_argument("--sim-dir", default=None,
                        help="Gemini 類似判定 JSONL のディレクトリ（Yes ペアを重ねて表示）")
    parser.add_argument("--top-n", type=int, default=250,
                        help="サブグラフに含める上位ノード数 (default: 250)")
    parser.add_argument("--hops", type=int, default=1,
                        help="シードノードから何 hop 隣接まで含めるか (default: 1)")
    parser.add_argument("--metric", choices=["degree", "betweenness"], default="degree",
                        help="シードノード抽出メトリクス (default: degree)")
    parser.add_argument("--betweenness-k", type=int, default=300,
                        help="betweenness 近似の BFS ソース数 (default: 300)")
    args = parser.parse_args()

    ergm_dir = Path(args.ergm_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    attr_path = ergm_dir / "attributes.txt"
    arc_path  = ergm_dir / "arc_list.txt"
    for p in (attr_path, arc_path):
        if not p.exists():
            print(f"エラー: {p} が見つかりません。", file=sys.stderr)
            sys.exit(1)

    # --- データロード ---
    print(f"ロード中: {attr_path}")
    attrs = pd.read_csv(attr_path, sep="\t", low_memory=False)
    print(f"  ノード数: {len(attrs):,}")

    print(f"ロード中: {arc_path}")
    arcs  = load_arc_list(arc_path)
    edges = arcs_to_undirected_edges(arcs)
    print(f"  無向エッジ数: {len(edges):,}")

    patent_cache = load_patent_cache(ergm_dir)
    patent_cache_keys: list[str] | None = None
    if patent_cache:
        patent_cache_keys = sorted(patent_cache.keys())
        print(f"  patent_cache ロード済み: {len(patent_cache_keys):,} 件")
    else:
        print("  patent_cache なし（patent_id は node_index で代用）")

    # --- グラフ構築 ---
    print("NetworkX グラフを構築中...")
    G = build_nx_graph(len(attrs), edges, attrs, patent_cache_keys)
    compute_node_metrics(G, betweenness_k=args.betweenness_k)

    # --- サブグラフ抽出 ---
    print(f"フォーカスサブグラフを抽出中 (top_n={args.top_n}, hops={args.hops}, metric={args.metric})...")
    SG = extract_focus_subgraph(G, top_n=args.top_n, hops=args.hops, metric=args.metric)
    print(f"  サブグラフ: {SG.number_of_nodes():,} nodes, {SG.number_of_edges():,} edges")

    # --- Gemini Yes ペア ---
    yes_pairs: set[tuple[int, int]] | None = None
    if args.sim_dir:
        sim_dir = Path(args.sim_dir)
        if sim_dir.exists():
            print(f"Gemini Yes ペアをロード中: {sim_dir}")
            yes_pairs = load_gemini_yes_pairs(sim_dir, patent_cache_keys)
        else:
            print(f"  [Gemini] {sim_dir} が見つかりません。overlay をスキップします。")

    # --- 出力 ---
    print("可視化を生成中...")

    # 特許レベル HTML
    patent_title = (
        f"Patent Co-citation Network "
        f"(top {args.top_n} by {args.metric}, {args.hops}-hop, "
        f"N={SG.number_of_nodes():,} nodes)"
    )
    make_patent_network_html(
        SG,
        out_dir / "network_patent_graph.html",
        patent_title,
        yes_pairs=yes_pairs,
    )

    # D-class 集約グラフ
    print("D-class 集約グラフを構築中...")
    H = build_class_graph(G)
    make_class_network_plots(
        H,
        out_dir / "network_class_graph.html",
        out_dir / "network_class_graph.png",
    )

    # 要約 CSV
    save_summary(G, SG, H, out_dir / "network_summary.csv")

    print(f"\n完了 → {out_dir}/")
    print(f"  full graph  : nodes={G.number_of_nodes():,}  edges={G.number_of_edges():,}")
    print(f"  focus graph : nodes={SG.number_of_nodes():,}  edges={SG.number_of_edges():,}")
    print(f"  class graph : nodes={H.number_of_nodes():,}  edges={H.number_of_edges():,}")
    if yes_pairs:
        sg_yes = sum(1 for u, v in SG.edges() if (min(u, v), max(u, v)) in yes_pairs)
        print(f"  Gemini Yes  : サブグラフ内 {sg_yes:,} エッジに表示")


if __name__ == "__main__":
    # 使い方:
    #   python visualize_ergm_network.py                          # デフォルト
    #   python visualize_ergm_network.py --top-n 300 --hops 1    # 上位300件+1hop
    #   python visualize_ergm_network.py --metric betweenness    # BC ベースで抽出
    #   python visualize_ergm_network.py \
    #       --sim-dir /mnt/eightthdd/uspto/similarity_results    # Gemini Yes 重ね描き
    main()