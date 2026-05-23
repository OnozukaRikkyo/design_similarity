"""
D18 分類コードのペアを対象とした三角形確信度スコアリング。

## 設計方針

LLM の Yes/No 判定は Ground Truth ではなく「検証対象のノイズラベル」である。
GT 候補の評価は cosine 類似度とグラフ幾何のみに基づく。
閾値・Tier 分類は設けず、全 3-clique のスコアをそのまま出力する。

### 三角形確信度スコアリング

共引用グラフの全 3-clique に 4 種の独立スコアを付与する。

    Score 1  weakest-link similarity    — 三辺の最小 cosine 類似度
    Score 2  angular tightness          — Schubert (2021) 角距離タイトネス
    Score 3  Schubert bound compliance  — Schubert (2021) 三角不等式境界適合度
    Score 4  SNN similarity             — Jarvis & Patrick (1973) 共有最近傍

依拠文献:
    Schubert 2021  — SISAP. arXiv:2107.04071
    Jarvis & Patrick 1973  — IEEE Trans. Computers C-22(11)
    Houle et al. 2010  — SSDBM. LNCS 6187
"""

import json
import math
from pathlib import Path

import networkx as nx


# ==============================================================================
# Configuration
# ==============================================================================

ALL_JSONL  = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
OUTPUT_DIR = Path('/home/sonozuka/design_similarity/graph/output/D18')


# ==============================================================================
# Data loading
# ==============================================================================

def load_data(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


# ==============================================================================
# Patent metadata (LLM 非依存)
# ==============================================================================

def patent_number_gap(a: str, b: str) -> int | None:
    """D0XXXXXX 形式の特許 ID から番号差を返す。補足情報として使用する。"""
    try:
        return abs(int(a[1:]) - int(b[1:]))
    except (ValueError, IndexError):
        return None


# ==============================================================================
# 類似度グラフ構築
# ==============================================================================

def build_similarity_graph(data: list[dict]) -> nx.Graph:
    """cosine similarity のみを重みとして無向グラフを構築する。
    LLM 判定フィールド (judgment / confidence / reason) は参照しない。
    """
    G = nx.Graph()
    for d in data:
        src, tgt = d['source'], d['target']
        sim = d['similarity']
        if G.has_edge(src, tgt):
            if sim > G[src][tgt]['sim']:
                G[src][tgt]['sim'] = sim
        else:
            G.add_edge(src, tgt, sim=sim)
    return G


# ==============================================================================
# 三角形列挙
# ==============================================================================

def enumerate_triangles(G: nx.Graph) -> list[tuple]:
    """G 内の全 3-clique を辞書順で列挙する。"""
    adj = {n: set(G.neighbors(n)) for n in G.nodes()}
    triangles = []
    for a in sorted(G.nodes()):
        for b in adj[a]:
            if b <= a:
                continue
            for c in adj[a] & adj[b]:
                if c <= b:
                    continue
                triangles.append((a, b, c))
    return triangles


# ==============================================================================
# 三角形確信度スコア (4種)
# ==============================================================================

def angular_distance(s: float) -> float:
    """cosine 類似度 → 角距離 [0, π]。単位球面上の proper metric (Schubert 2021)。"""
    return math.acos(max(-1.0, min(1.0, s)))


def schubert_lower_bound(s_ab: float, s_bc: float) -> float:
    return s_ab * s_bc - math.sqrt(max(0, 1 - s_ab**2)) * math.sqrt(max(0, 1 - s_bc**2))


def schubert_upper_bound(s_ab: float, s_bc: float) -> float:
    return s_ab * s_bc + math.sqrt(max(0, 1 - s_ab**2)) * math.sqrt(max(0, 1 - s_bc**2))


def score_min_similarity(s_ab: float, s_bc: float, s_ac: float) -> float:
    """Score 1: weakest-link similarity。三辺中の最小 cosine 類似度。"""
    return min(s_ab, s_bc, s_ac)


def score_angular_tightness(s_ab: float, s_bc: float, s_ac: float) -> float:
    """Score 2: 角距離タイトネス (Schubert 2021)。1 - max_d / (π/2) で [0,1] にスケール。"""
    max_d = max(angular_distance(s_ab), angular_distance(s_bc), angular_distance(s_ac))
    return max(0.0, 1.0 - max_d / (math.pi / 2))


def score_bound_compliance(s_ab: float, s_bc: float, s_ac: float) -> float:
    """Score 3: Schubert 三角不等式境界への適合度。上界で 1.0、下界で 0.0。"""
    lb = schubert_lower_bound(s_ab, s_bc)
    ub = schubert_upper_bound(s_ab, s_bc)
    if ub - lb < 1e-9:
        return 1.0 if s_ac > 0.99 else 0.0
    return (s_ac - lb) / (ub - lb)


def score_snn(snn_a: set, snn_b: set, snn_c: set, k_norm: int) -> float:
    """Score 4: 3-way Shared Nearest Neighbor 類似度 (Jarvis & Patrick 1973)。"""
    return 0.0 if k_norm == 0 else len(snn_a & snn_b & snn_c) / k_norm


def triadic_confidence(
    triangle: tuple,
    G: nx.Graph,
    neighborhoods: dict[str, set],
    weights: tuple = (0.30, 0.30, 0.25, 0.15),
) -> dict:
    """1つの 3-clique に対する統合確信度スコアを計算する。"""
    w1, w2, w3, w4 = weights
    a, b, c = triangle

    s_ab = G[a][b]['sim']
    s_bc = G[b][c]['sim']
    s_ac = G[a][c]['sim']

    s1 = score_min_similarity(s_ab, s_bc, s_ac)
    s2 = score_angular_tightness(s_ab, s_bc, s_ac)
    s3 = score_bound_compliance(s_ab, s_bc, s_ac)

    snn_a = neighborhoods[a] - {a, b, c}
    snn_b = neighborhoods[b] - {a, b, c}
    snn_c = neighborhoods[c] - {a, b, c}
    k_norm = max(1, min(len(snn_a), len(snn_b), len(snn_c)))
    s4 = score_snn(snn_a, snn_b, snn_c, k_norm)

    return {
        'triangle': triangle,
        'sims': (s_ab, s_bc, s_ac),
        's1_weakest_link': s1,
        's2_angular_tightness': s2,
        's3_bound_compliance': s3,
        's4_snn': s4,
        'confidence': w1 * s1 + w2 * s2 + w3 * s3 + w4 * s4,
    }


# ==============================================================================
# Visualization
# ==============================================================================

def plot_score_distribution(scored: list[dict], output_path: Path) -> None:
    """全三角形の 4 スコアと統合確信度の分布を描画する。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    s1 = [r['s1_weakest_link']       for r in scored]
    s2 = [r['s2_angular_tightness']  for r in scored]
    s3 = [r['s3_bound_compliance']   for r in scored]
    s4 = [r['s4_snn']                for r in scored]
    cf = [r['confidence']            for r in scored]

    fig, axes = plt.subplots(1, 5, figsize=(15, 4), facecolor='#f5f5f5')
    titles = [
        'Score 1\nweakest-link sim',
        'Score 2\nangular tightness',
        'Score 3\nSchubert compliance',
        'Score 4\nSNN similarity',
        'Confidence\n(weighted sum)',
    ]
    data_list = [s1, s2, s3, s4, cf]
    colors = ['#4477aa', '#66ccee', '#228833', '#ccbb44', '#ee6677']

    for ax, vals, title, color in zip(axes, data_list, titles, colors):
        ax.set_facecolor('#f5f5f5')
        ax.hist(vals, bins=40, color=color, alpha=0.8, edgecolor='white', linewidth=0.4)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel('Score', fontsize=8)
        ax.set_ylabel('# triangles', fontsize=8)
        ax.tick_params(labelsize=7)
        ax.axvline(np.median(vals), color='#333333', linewidth=1.0, linestyle='--',
                   label=f'median={np.median(vals):.3f}')
        ax.legend(fontsize=6.5)

    fig.suptitle(
        f'D18 — Triadic confidence score distributions  (all {len(scored)} triangles)',
        fontsize=11,
    )
    plt.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'Score distribution figure → {output_path}')


def plot_top_triangles_network(
    data: list[dict],
    scored: list[dict],
    top_n: int,
    output_path: Path,
) -> None:
    """確信度上位 top_n 件の三角形をネットワーク図として描画する。

    視覚エンコーディング:
        ノード色・サイズ  → 次数 (D18 共引用グラフ内の接続数)
        エッジ色・太さ    → cosine similarity (画像埋め込み間の類似度)
        三角形塗り        → 半透明 (存在を示すのみ)
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.cm as cm
    import matplotlib.colors as mcolors
    import numpy as np
    from matplotlib.gridspec import GridSpec

    top = scored[:top_n]

    G_full = build_similarity_graph(data)
    full_degree = dict(G_full.degree())

    # 上位 top_n 三角形に含まれるノードとエッジ
    node_tri_count: dict[str, int] = {}
    for r in top:
        for n in r['triangle']:
            node_tri_count[n] = node_tri_count.get(n, 0) + 1
    top_nodes = set(node_tri_count)
    top_node_list = sorted(top_nodes)

    edge_sim: dict[frozenset, float] = {}
    for r in top:
        a, b, c = r['triangle']
        for u, v, s in zip(
            [a, b, a], [b, c, c], [r['sims'][0], r['sims'][1], r['sims'][2]]
        ):
            k = frozenset([u, v])
            edge_sim[k] = max(edge_sim.get(k, 0), s)

    # 1-hop 近傍
    hop1 = set(top_nodes)
    for n in top_nodes:
        hop1.update(G_full.neighbors(n))
    peripheral = hop1 - top_nodes
    G_sub = G_full.subgraph(hop1).copy()

    # レイアウト
    G_cluster = G_full.subgraph(top_nodes).copy()
    pos_cluster = nx.kamada_kawai_layout(G_cluster, weight='sim')
    pos_sub = nx.spring_layout(
        G_sub,
        pos={n: pos_cluster[n] for n in top_nodes},
        fixed=top_nodes,
        weight='sim', seed=42, k=0.6, iterations=120,
    )

    # ---- カラーマップ ----
    # エッジ: cosine similarity → plasma
    sim_cmap = cm.plasma
    sim_norm = mcolors.Normalize(
        vmin=min(edge_sim.values()), vmax=max(edge_sim.values())
    )

    # ノード: 次数 → YlOrRd (全グラフの次数範囲で正規化)
    all_degrees = list(full_degree.values())
    deg_cmap = cm.YlOrRd
    deg_norm = mcolors.Normalize(vmin=min(all_degrees), vmax=max(all_degrees))

    conf_vals = [r['confidence'] for r in top]
    conf_norm = mcolors.Normalize(vmin=min(conf_vals), vmax=max(conf_vals))

    # ---- Figure: 2パネル + 下段2カラーバー ----
    fig = plt.figure(figsize=(15, 7.5), facecolor='#f5f5f5')
    gs = GridSpec(
        2, 2, figure=fig,
        height_ratios=[20, 1],
        hspace=0.40, wspace=0.12,
    )
    ax_left   = fig.add_subplot(gs[0, 0])
    ax_right  = fig.add_subplot(gs[0, 1])
    ax_cbar_e = fig.add_subplot(gs[1, 0])   # エッジ: cosine similarity
    ax_cbar_n = fig.add_subplot(gs[1, 1])   # ノード: 次数
    for ax in (ax_left, ax_right):
        ax.set_facecolor('#f5f5f5')

    # ============================================================
    # 左パネル: D18グラフ内の位置付け
    # ============================================================
    ax_left.set_title(
        f'(Left) Top-{top_n} triangles in the D18 co-citation graph\n'
        f'node color/size = degree  ·  edge color/width = cosine similarity',
        fontsize=9, pad=8,
    )

    # 非対象エッジ (薄グレー)
    non_top_edges = [(u, v) for u, v in G_sub.edges() if frozenset([u, v]) not in edge_sim]
    nx.draw_networkx_edges(
        G_sub, pos_sub, edgelist=non_top_edges,
        edge_color='#cccccc', width=0.5, alpha=0.5, ax=ax_left,
    )

    # 上位三角形エッジ (cosine sim → 色・太さ)
    top_edgelist = [(list(k)[0], list(k)[1]) for k in edge_sim]
    w_range = sim_norm.vmax - sim_norm.vmin
    nx.draw_networkx_edges(
        G_sub, pos_sub, edgelist=top_edgelist,
        edge_color=[sim_cmap(sim_norm(edge_sim[k])) for k in edge_sim],
        width=[1.0 + 5.0 * (edge_sim[k] - sim_norm.vmin) / w_range for k in edge_sim],
        alpha=0.92, ax=ax_left,
    )

    # 三角形塗り (半透明)
    for r in top:
        a, b, c = r['triangle']
        pts = np.array([pos_sub[a], pos_sub[b], pos_sub[c]])
        ax_left.add_patch(mpatches.Polygon(
            pts, closed=True, facecolor='#888888', alpha=0.08, edgecolor='none',
        ))

    # 周辺ノード (次数 → 色・サイズ)
    nx.draw_networkx_nodes(
        G_sub, pos_sub, nodelist=list(peripheral),
        node_size=[10 + 12 * full_degree[n] for n in peripheral],
        node_color=[deg_cmap(deg_norm(full_degree[n])) for n in peripheral],
        alpha=0.55, ax=ax_left,
    )

    # 上位三角形ノード (次数 → 色・サイズ, 枠線で強調)
    nx.draw_networkx_nodes(
        G_sub, pos_sub, nodelist=top_node_list,
        node_size=[40 + 20 * full_degree[n] for n in top_node_list],
        node_color=[deg_cmap(deg_norm(full_degree[n])) for n in top_node_list],
        edgecolors='#333333', linewidths=1.0,
        alpha=0.95, ax=ax_left,
    )

    ax_left.axis('off')
    ax_left.legend(
        handles=[
            mpatches.Patch(facecolor=deg_cmap(deg_norm(3)),  label='Low degree node'),
            mpatches.Patch(facecolor=deg_cmap(deg_norm(10)), label='Mid degree node'),
            mpatches.Patch(facecolor=deg_cmap(deg_norm(20)), label='High degree node'),
            mpatches.Patch(facecolor=deg_cmap(0.5), edgecolor='#333', linewidth=1.0,
                           label=f'Node in top-{top_n} triangles (outline)'),
            mpatches.Patch(facecolor='#888888', alpha=0.2, label='Triangle fill'),
            mpatches.Patch(facecolor='#cccccc', label='Other edge (gray)'),
        ],
        loc='lower left', fontsize=7, framealpha=0.85, edgecolor='#cccccc',
    )

    # ============================================================
    # 右パネル: クラスター内部構造
    # ============================================================
    ax_right.set_title(
        f'(Right) Internal structure of top-{top_n} triangle cluster\n'
        f'{len(top_nodes)} nodes, {len(edge_sim)} edges'
        f'  ·  node color/size = degree  ·  label = patent ID (last 6 digits) / degree',
        fontsize=9, pad=8,
    )

    # 三角形塗り
    for r in top:
        a, b, c = r['triangle']
        pts = np.array([pos_cluster[a], pos_cluster[b], pos_cluster[c]])
        alpha_tri = float(np.clip(0.06 + 0.25 * conf_norm(r['confidence']), 0.06, 0.32))
        ax_right.add_patch(mpatches.Polygon(
            pts, closed=True, facecolor='#aaaaaa', alpha=alpha_tri, edgecolor='none',
        ))

    # エッジ (cosine sim → 色・太さ)
    for k, s in edge_sim.items():
        u, v = list(k)
        ax_right.plot(
            [pos_cluster[u][0], pos_cluster[v][0]],
            [pos_cluster[u][1], pos_cluster[v][1]],
            color=sim_cmap(sim_norm(s)),
            linewidth=1.0 + 6.0 * (s - sim_norm.vmin) / w_range,
            alpha=0.88, solid_capstyle='round', zorder=2,
        )

    # ノード (次数 → 色・サイズ)
    node_r_base = 0.018
    node_r_scale = 0.022
    deg_max_top = max(full_degree[n] for n in top_nodes)
    deg_min_top = min(full_degree[n] for n in top_nodes)
    for n in top_node_list:
        x, y = pos_cluster[n]
        d = full_degree[n]
        r_size = node_r_base + node_r_scale * (d - deg_min_top) / max(1, deg_max_top - deg_min_top)
        ax_right.add_patch(mpatches.Circle(
            (x, y), r_size,
            facecolor=deg_cmap(deg_norm(d)),
            edgecolor='#333333', linewidth=0.9, zorder=4,
        ))
        # ラベル: 特許番号末尾6桁
        ax_right.text(
            x, y + r_size + 0.016, n[-6:],
            ha='center', va='bottom', fontsize=5.8,
            color='#111111', zorder=6,
        )
        # ノード内: 次数の数値
        ax_right.text(
            x, y, str(d),
            ha='center', va='center',
            fontsize=5.5, color='white', fontweight='bold', zorder=5,
        )

    ax_right.set_aspect('equal')
    ax_right.axis('off')

    stats_lines = [
        f'Total triangles : {len(scored)}',
        f'Shown (top-{top_n}): {top_n}',
        f'Nodes           : {len(top_nodes)}',
        f'Edges           : {len(edge_sim)}',
        f'Degree range    : {deg_min_top}–{deg_max_top}  (shown nodes)',
        f'Cosine sim      : {min(edge_sim.values()):.4f}–{max(edge_sim.values()):.4f}',
        f'Confidence      : {min(conf_vals):.4f}–{max(conf_vals):.4f}',
    ]
    ax_right.text(
        0.98, 0.02, '\n'.join(stats_lines),
        transform=ax_right.transAxes,
        fontsize=6.5, ha='right', va='bottom', fontfamily='monospace',
        bbox=dict(boxstyle='round,pad=0.4', facecolor='white',
                  alpha=0.85, edgecolor='#cccccc'),
    )

    # ============================================================
    # 下段カラーバー (左: エッジ cosine sim、右: ノード次数)
    # ============================================================
    sm_edge = cm.ScalarMappable(cmap=sim_cmap, norm=sim_norm)
    sm_edge.set_array([])
    cb_e = fig.colorbar(sm_edge, cax=ax_cbar_e, orientation='horizontal')
    cb_e.set_label('Edge color / width  ←  Cosine similarity (image embeddings)', fontsize=8)
    cb_e.ax.tick_params(labelsize=7)

    sm_node = cm.ScalarMappable(cmap=deg_cmap, norm=deg_norm)
    sm_node.set_array([])
    cb_n = fig.colorbar(sm_node, cax=ax_cbar_n, orientation='horizontal')
    cb_n.set_label('Node color / size  ←  Degree (# co-citation pairs in D18 graph)', fontsize=8)
    cb_n.ax.tick_params(labelsize=7)

    fig.suptitle(
        f'D18 Design Patents — Top-{top_n} triangles by triadic confidence score\n'
        f'(no threshold applied; ranked by weighted sum of 4 geometric scores)',
        fontsize=11, y=1.02,
    )

    plt.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'Network figure → {output_path}')


# ==============================================================================
# Output helper
# ==============================================================================

def print_section(title: str) -> None:
    print(f'\n{"=" * 60}')
    print(f'  {title}')
    print('=' * 60)


# ==============================================================================
# Main
# ==============================================================================

def main() -> list[dict]:
    print(f'Loading D18 data from {ALL_JSONL}')
    data = load_data(ALL_JSONL)
    print(f'Total records (co-citation pairs): {len(data)}')

    from collections import Counter
    type_dist = Counter(d['type'] for d in data)
    print(f'Image type distribution: {dict(type_dist)}')

    # ------------------------------------------------------------------
    # 類似度グラフ
    # ------------------------------------------------------------------
    print_section('Similarity Graph')
    G_full = build_similarity_graph(data)
    print(f'|V| = {G_full.number_of_nodes()} patents')
    print(f'|E| = {G_full.number_of_edges()} co-citation pairs')

    all_sims = sorted(G_full[u][v]['sim'] for u, v in G_full.edges())
    n = len(all_sims)
    print(f'cosine similarity — min={all_sims[0]:.4f}  '
          f'median={all_sims[n//2]:.4f}  max={all_sims[-1]:.4f}')

    # ------------------------------------------------------------------
    # 三角形列挙 + 確信度スコアリング
    # ------------------------------------------------------------------
    print_section('Triadic Confidence Scoring')
    triangles = enumerate_triangles(G_full)
    print(f'3-cliques: {len(triangles)}')

    neighborhoods = {node: set(G_full.neighbors(node)) for node in G_full.nodes()}
    scored = [triadic_confidence(t, G_full, neighborhoods) for t in triangles]
    scored.sort(key=lambda r: -r['confidence'])

    # 各スコアの記述統計
    import statistics
    for key, label in [
        ('s1_weakest_link',      'Score 1 weakest-link'),
        ('s2_angular_tightness', 'Score 2 angular tightness'),
        ('s3_bound_compliance',  'Score 3 Schubert compliance'),
        ('s4_snn',               'Score 4 SNN'),
        ('confidence',           'Confidence (weighted sum)'),
    ]:
        vals = [r[key] for r in scored]
        print(f'  {label:30s}  '
              f'min={min(vals):.4f}  '
              f'median={statistics.median(vals):.4f}  '
              f'max={max(vals):.4f}')

    # 上位 20 件
    print(f'\n  Top 20 triangles by confidence:')
    print(f'  {"rank":>4}  {"A":10}  {"B":10}  {"C":10}  '
          f'{"s_AB":6}  {"s_BC":6}  {"s_AC":6}  '
          f'{"s1":6}  {"s2":6}  {"s3":6}  {"s4":6}  {"conf":6}')
    for i, r in enumerate(scored[:20], 1):
        a, b, c = r['triangle']
        s_ab, s_bc, s_ac = r['sims']
        print(f'  {i:4d}  {a:10}  {b:10}  {c:10}  '
              f'{s_ab:.4f}  {s_bc:.4f}  {s_ac:.4f}  '
              f'{r["s1_weakest_link"]:.4f}  {r["s2_angular_tightness"]:.4f}  '
              f'{r["s3_bound_compliance"]:.4f}  {r["s4_snn"]:.4f}  '
              f'{r["confidence"]:.4f}')

    # ------------------------------------------------------------------
    # 特許番号差（補足情報、全上位 20 ペア）
    # ------------------------------------------------------------------
    print_section('Patent Number Gap for Top-20 Triangle Pairs')
    print('  ※ 補足情報。GT 分類の条件ではない。')
    seen: set[frozenset] = set()
    for r in scored[:20]:
        a, b, c = r['triangle']
        for u, v in [(a, b), (b, c), (a, c)]:
            k = frozenset([u, v])
            if k not in seen:
                seen.add(k)
                g = patent_number_gap(u, v)
                print(f'    {u} ↔ {v}  gap={g}')

    # ------------------------------------------------------------------
    # 結果保存（全三角形）
    # ------------------------------------------------------------------
    print_section('Saving Results')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    out_path = OUTPUT_DIR / 'triadic_scored.jsonl'
    with open(out_path, 'w') as f:
        for rank, r in enumerate(scored, 1):
            f.write(json.dumps({
                'rank': rank,
                'A': r['triangle'][0],
                'B': r['triangle'][1],
                'C': r['triangle'][2],
                's_AB': r['sims'][0],
                's_BC': r['sims'][1],
                's_AC': r['sims'][2],
                'score_weakest_link':    r['s1_weakest_link'],
                'score_angular_tightness': r['s2_angular_tightness'],
                'score_bound_compliance':  r['s3_bound_compliance'],
                'score_snn':             r['s4_snn'],
                'confidence':            r['confidence'],
            }) + '\n')
    print(f'All {len(scored)} triangles → {out_path}')

    # ------------------------------------------------------------------
    # 要約統計 CSV
    # ------------------------------------------------------------------
    print_section('Summary CSV')
    import csv, statistics as _stat

    degrees = [d for _, d in G_full.degree()]
    conf_vals = [r['confidence'] for r in scored]
    s1_vals   = [r['s1_weakest_link']      for r in scored]
    s2_vals   = [r['s2_angular_tightness'] for r in scored]
    s3_vals   = [r['s3_bound_compliance']  for r in scored]
    s4_vals   = [r['s4_snn']               for r in scored]

    rows = [
        # ── グラフ構造 ──────────────────────────────────────────
        ('patents_nodes',           G_full.number_of_nodes()),
        ('pairs_edges',             G_full.number_of_edges()),
        ('triangles_3cliques',      len(triangles)),
        # ── 画像タイプ別ペア数 ───────────────────────────────────
        ('pairs_perspective',       type_dist.get('perspective', 0)),
        ('pairs_overview',          type_dist.get('overview',    0)),
        ('pairs_front',             type_dist.get('front',       0)),
        # ── ノード次数 ──────────────────────────────────────────
        ('degree_min',              min(degrees)),
        ('degree_median',           _stat.median(degrees)),
        ('degree_max',              max(degrees)),
        # ── cosine 類似度（エッジ） ──────────────────────────────
        ('cosine_sim_min',          round(all_sims[0],    6)),
        ('cosine_sim_median',       round(all_sims[n//2], 6)),
        ('cosine_sim_max',          round(all_sims[-1],   6)),
        # ── 三角形スコア記述統計 ─────────────────────────────────
        ('s1_weakest_link_min',     round(min(s1_vals),              6)),
        ('s1_weakest_link_median',  round(_stat.median(s1_vals),     6)),
        ('s1_weakest_link_max',     round(max(s1_vals),              6)),
        ('s2_angular_tightness_min',    round(min(s2_vals),          6)),
        ('s2_angular_tightness_median', round(_stat.median(s2_vals), 6)),
        ('s2_angular_tightness_max',    round(max(s2_vals),          6)),
        ('s3_bound_compliance_min',    round(min(s3_vals),           6)),
        ('s3_bound_compliance_median', round(_stat.median(s3_vals),  6)),
        ('s3_bound_compliance_max',    round(max(s3_vals),           6)),
        ('s4_snn_min',              round(min(s4_vals),              6)),
        ('s4_snn_median',           round(_stat.median(s4_vals),     6)),
        ('s4_snn_max',              round(max(s4_vals),              6)),
        ('confidence_min',          round(min(conf_vals),            6)),
        ('confidence_median',       round(_stat.median(conf_vals),   6)),
        ('confidence_max',          round(max(conf_vals),            6)),
    ]

    csv_path = OUTPUT_DIR / 'summary.csv'
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['metric', 'value'])
        writer.writerows(rows)
    print(f'Summary CSV → {csv_path}')

    # ------------------------------------------------------------------
    # 可視化
    # ------------------------------------------------------------------
    print_section('Visualization')

    dist_path = OUTPUT_DIR / 'score_distribution.png'
    plot_score_distribution(scored, dist_path)

    net_path = OUTPUT_DIR / 'top_triangles_network.png'
    plot_top_triangles_network(data, scored, top_n=20, output_path=net_path)

    return scored


if __name__ == '__main__':
    scored = main()
