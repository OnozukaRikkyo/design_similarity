"""
Watts & Strogatz (1998) 局所クラスタリング係数による triadic スコアリング。

## 理論

各ノード v の局所クラスタリング係数 (Watts & Strogatz 1998):

    C_v = 2 * |{(u,w) ∈ E : u,w ∈ N(v), u≠w}| / (k_v * (k_v - 1))

ここで N(v) は v の近傍集合、k_v = |N(v)|。

各三角形 (A, B, C) の WCC スコア:

    S_WCC = min(C_A, C_B, C_C)

S_WCC が小さい三角形は、少なくとも 1 頂点が密なクラスタに属していない
(= グラフ上で孤立した橋渡し的な位置にある) ことを意味し、
装飾クラスタとしての整合性が低いと解釈される。

依拠文献:
    Watts, D.J. & Strogatz, S.H. (1998). Collective dynamics of 'small-world' networks.
    Nature, 393(6684), 440–442.
"""

import json
import statistics
from itertools import combinations
from pathlib import Path

import networkx as nx
import numpy as np


# ==============================================================================
# Configuration
# ==============================================================================

ALL_JSONL      = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
TRIADIC_SCORED = Path('/home/sonozuka/design_similarity/graph/output/D18/triadic_scored.jsonl')
OUTPUT_DIR     = Path('/home/sonozuka/design_similarity/graph/output/D18/verify')

# 閾値グリッドの軸刻み
_S1_GRID_THS  = np.round(np.arange(0.800, 1.001, 0.025), 3)   # Y軸: S1 (weakest-link)
_WCC_GRID_THS = np.round(np.arange(0.500, 1.001, 0.050), 3)   # X軸: S_WCC


# ==============================================================================
# Data loading
# ==============================================================================

def load_data(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


# ==============================================================================
# グラフ構築
# ==============================================================================

def build_similarity_graph(data: list[dict]) -> nx.Graph:
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
# Watts-Strogatz 局所クラスタリング係数
# ==============================================================================

def compute_clustering_coefficients(adj: dict[str, set]) -> dict[str, float]:
    """
    Watts & Strogatz (1998) 局所クラスタリング係数。

    C_v = (2 * triangles_at_v) / (k_v * (k_v - 1))

    triangles_at_v = |{(u,w) ∈ E : u,w ∈ N(v), u≠w}|
    """
    C = {}
    for v, N in adj.items():
        k = len(N)
        if k < 2:
            C[v] = 0.0
            continue
        triangles_at_v = sum(1 for u, w in combinations(N, 2) if w in adj[u])
        C[v] = triangles_at_v / (k * (k - 1) / 2)
    return C


def score_wcc(C_a: float, C_b: float, C_c: float) -> float:
    """S_WCC = min(C_A, C_B, C_C)"""
    return min(C_a, C_b, C_c)


# ==============================================================================
# Visualization
# ==============================================================================

def plot_wcc_distribution(results: list[dict], output_path: Path) -> None:
    """S_WCC の分布と各頂点の C_v 分布を 3 パネルで描画する。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    wcc_vals = [r['score_wcc'] for r in results]
    c_a_vals = [r['C_A'] for r in results]
    c_b_vals = [r['C_B'] for r in results]
    c_c_vals = [r['C_C'] for r in results]

    panels = [
        (wcc_vals,
         'S_WCC = min(C_A, C_B, C_C)\n(per triangle)',
         '# triangles', '#ee6677'),
        (c_a_vals,
         'C_A — clustering coeff of vertex A\n(per triangle)',
         '# triangles', '#4477aa'),
        (c_b_vals + c_c_vals,
         'C_B ∪ C_C — vertices B & C combined\n(per triangle × 2)',
         '# occurrences', '#66ccee'),
    ]

    fig, axes = plt.subplots(1, 3, figsize=(15, 4), facecolor='#f5f5f5')
    for ax, (vals, title, ylabel, color) in zip(axes, panels):
        ax.set_facecolor('#f5f5f5')
        ax.hist(vals, bins=40, color=color, alpha=0.8, edgecolor='white', linewidth=0.4)
        ax.set_title(title, fontsize=9)
        ax.set_xlabel('Score', fontsize=8)
        ax.set_ylabel(ylabel, fontsize=8)
        ax.tick_params(labelsize=7)
        med = float(np.median(vals))
        ax.axvline(med, color='#333333', linewidth=1.0, linestyle='--',
                   label=f'median={med:.3f}')
        ax.legend(fontsize=6.5)

    fig.suptitle(
        f'D18 — Watts-Strogatz Clustering Coefficient Score  ({len(results)} triangles)',
        fontsize=11,
    )
    plt.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'WCC distribution figure → {output_path}')


def plot_node_clustering(G: nx.Graph, clustering: dict[str, float], output_path: Path) -> None:
    """全ノードの C_v 分布・次数との関係を 3 パネルで描画する。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    nodes_ordered = list(G.nodes())
    deg_arr = np.array([G.degree(n) for n in nodes_ordered])
    cv_arr  = np.array([clustering[n] for n in nodes_ordered])
    cv_vals = cv_arr.tolist()

    fig, axes = plt.subplots(1, 3, figsize=(15, 4), facecolor='#f5f5f5')

    # ---- Panel 1: C_v histogram ----
    ax = axes[0]
    ax.set_facecolor('#f5f5f5')
    ax.hist(cv_vals, bins=30, color='#4477aa', alpha=0.8, edgecolor='white', linewidth=0.4)
    ax.set_title(f'Node C_v distribution\n({len(cv_vals)} nodes)', fontsize=9)
    ax.set_xlabel('C_v (local clustering coefficient)', fontsize=8)
    ax.set_ylabel('# nodes', fontsize=8)
    ax.tick_params(labelsize=7)
    med = float(np.median(cv_vals))
    ax.axvline(med, color='#333', linewidth=1.0, linestyle='--', label=f'median={med:.3f}')
    ax.legend(fontsize=6.5)

    # ---- Panel 2: degree vs C_v scatter ----
    ax = axes[1]
    ax.set_facecolor('#f5f5f5')
    ax.scatter(deg_arr, cv_arr, alpha=0.45, s=8, color='#66ccee', rasterized=True)
    ax.set_title('Degree vs. C_v\n(each node)', fontsize=9)
    ax.set_xlabel('Degree k_v', fontsize=8)
    ax.set_ylabel('C_v', fontsize=8)
    ax.tick_params(labelsize=7)
    corr = float(np.corrcoef(deg_arr, cv_arr)[0, 1])
    ax.text(0.97, 0.97, f'r = {corr:.3f}', transform=ax.transAxes,
            ha='right', va='top', fontsize=7.5,
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))

    # ---- Panel 3: C_v category breakdown ----
    ax = axes[2]
    ax.set_facecolor('#f5f5f5')
    n_total = len(cv_vals)
    n_zero  = sum(1 for v in cv_vals if v == 0.0)
    n_one   = sum(1 for v in cv_vals if v == 1.0)
    n_mid   = n_total - n_zero - n_one
    labels  = ['C_v = 0', '0 < C_v < 1', 'C_v = 1']
    counts  = [n_zero, n_mid, n_one]
    colors  = ['#ee6677', '#4477aa', '#228833']
    bars = ax.bar(labels, [c / n_total for c in counts],
                  color=colors, alpha=0.85, edgecolor='white')
    ax.set_title('Node C_v category breakdown', fontsize=9)
    ax.set_ylabel('Fraction of nodes', fontsize=8)
    ax.tick_params(labelsize=7)
    for bar, cnt in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.005,
                f'{cnt} ({cnt/n_total:.1%})',
                ha='center', va='bottom', fontsize=7.5)

    fig.suptitle('D18 — Node-level Clustering Coefficient (Watts & Strogatz 1998)', fontsize=11)
    plt.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'Node clustering figure → {output_path}')


def plot_wcc_vs_scores(
    results: list[dict],
    scored_map: dict,
    output_path: Path,
) -> None:
    """S_WCC と既存スコア (confidence, S1, S2, S4) の相関散布図を描画する。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    wcc_vals, conf_vals, s1_vals, s2_vals, s4_vals = [], [], [], [], []
    for r in results:
        key = (r['A'], r['B'], r['C'])
        if key not in scored_map:
            continue
        ex = scored_map[key]
        wcc_vals.append(r['score_wcc'])
        conf_vals.append(ex['confidence'])
        s1_vals.append(ex['score_weakest_link'])
        s2_vals.append(ex['score_angular_tightness'])
        s4_vals.append(ex['score_snn'])

    if not wcc_vals:
        print('  [skip] triadic_scored.jsonl not found — skipping correlation plot')
        return

    w = np.array(wcc_vals)
    comparisons = [
        (conf_vals, 'Confidence (weighted sum)',          '#4477aa'),
        (s1_vals,   'S1 weakest-link similarity',        '#ee6677'),
        (s2_vals,   'S2 angular tightness (Schubert)',   '#228833'),
        (s4_vals,   'S4 SNN similarity (Jarvis-Patrick)', '#ccbb44'),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(20, 4.5), facecolor='#f5f5f5')
    for ax, (other, label, color) in zip(axes, comparisons):
        y = np.array(other)
        ax.set_facecolor('#f5f5f5')
        ax.scatter(w, y, alpha=0.35, s=6, color=color, rasterized=True)
        corr = float(np.corrcoef(w, y)[0, 1])
        ax.set_xlabel('S_WCC = min(C_A, C_B, C_C)', fontsize=8)
        ax.set_ylabel(label, fontsize=8)
        ax.set_title(f'r = {corr:.3f}', fontsize=9)
        ax.tick_params(labelsize=7)

    fig.suptitle(
        f'D18 — S_WCC vs. existing scores  ({len(wcc_vals)} triangles)',
        fontsize=11,
    )
    plt.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'WCC vs scores figure → {output_path}')


# ==============================================================================
# Fig: S1 × S_WCC 閾値グリッド（threshold_grid.png と同構造）
# ==============================================================================

def plot_wcc_threshold_grid(
    s1_arr: np.ndarray,
    wcc_arr: np.ndarray,
    out_path: Path,
    title: str = r'D18 — GT candidates: $S_1 \geq T_1$ and $S_{\rm WCC} \geq T_{\rm WCC}$',
    cmap_name: str = 'Blues_r',
    bold_range: tuple[int, int] | None = (20, 50),
) -> np.ndarray:
    """横軸 S_WCC × 縦軸 S1 の閾値グリッドを描画する。

    threshold_grid.png (discord_analysis.py) と同構造。
    セルの値 = S1 ≥ T1 かつ S_WCC ≥ T_WCC を満たす三角形の件数。
    bold_range の範囲の件数を太字で強調（None = 強調なし）。
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    ths_s1  = _S1_GRID_THS    # Y軸 (行): 0.800 → 1.000, step 0.025
    ths_wcc = _WCC_GRID_THS   # X軸 (列): 0.500 → 1.000, step 0.050
    n_s1  = len(ths_s1)
    n_wcc = len(ths_wcc)

    grid = np.zeros((n_s1, n_wcc), dtype=int)
    for i, t1 in enumerate(ths_s1):
        for j, tw in enumerate(ths_wcc):
            grid[i, j] = int(((s1_arr >= t1) & (wcc_arr >= tw)).sum())

    fig, ax = plt.subplots(figsize=(8.0, 5.8), facecolor='white')

    cmap_obj = plt.get_cmap(cmap_name)
    vmax_display = min(300, int(grid[0, 0]) or 1)
    ax.imshow(grid, origin='upper', aspect='auto',
              cmap=cmap_obj, vmin=0, vmax=vmax_display)

    ax.set_xticks(range(n_wcc))
    ax.set_xticklabels([f'{t:.3f}' for t in ths_wcc],
                       fontsize=9, rotation=45, ha='right')
    ax.set_yticks(range(n_s1))
    ax.set_yticklabels([f'{t:.3f}' for t in ths_s1], fontsize=9)
    ax.set_xlabel(r'$T_{\rm WCC}$ (Watts-Strogatz clustering threshold)', fontsize=12)
    ax.set_ylabel(r'$T_1$ (weakest-link threshold)', fontsize=12)
    ax.set_title(title, fontsize=13)

    for i in range(n_s1):
        for j in range(n_wcc):
            val = grid[i, j]
            norm_val = min(val / vmax_display, 1.0)
            r, g, b, _ = cmap_obj(norm_val)
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            txt_color = 'white' if luminance < 0.5 else '#111111'
            fw = ('bold'
                  if bold_range and bold_range[0] <= val <= bold_range[1]
                  else 'normal')
            ax.text(j, i, str(val), ha='center', va='center',
                    fontsize=8, color=txt_color, fontweight=fw)

    ax.tick_params(labelsize=9, width=0.6, length=3)
    for sp in ax.spines.values():
        sp.set_linewidth(0.6)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'WCC threshold grid → {out_path}')
    return grid


def plot_fp_fn_wcc_grids(results: list[dict], out_dir: Path) -> None:
    """fp.csv / fn.csv の triad を対象に S1 × S_WCC 閾値グリッドを描画する。

    fp.csv・fn.csv は discord_analysis.py が出力したもの。
    1 triad が複数行にわたる場合（辺ごとの行）は (A, B, C) で重複除去する。
    """
    import csv

    wcc_map = {(r['A'], r['B'], r['C']): r['score_wcc'] for r in results}

    for case, csv_name, out_name, cmap_name in [
        ('FP', 'fp.csv', 'wcc_fp_grid.png', 'Oranges_r'),
        ('FN', 'fn.csv', 'wcc_fn_grid.png', 'Greens_r'),
    ]:
        csv_path = out_dir / csv_name
        if not csv_path.exists():
            print(f'  [skip] {csv_path} not found')
            continue

        # (A, B, C) で重複除去しつつ S1 と S_WCC を収集
        seen: set[tuple] = set()
        s1_list:  list[float] = []
        wcc_list: list[float] = []
        with open(csv_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                key = (row['A'], row['B'], row['C'])
                if key in seen:
                    continue
                seen.add(key)
                if key not in wcc_map:
                    continue
                s1_list.append(float(row['S1_weakest_link']))
                wcc_list.append(wcc_map[key])

        if not s1_list:
            print(f'  [skip] no matching triads for {case}')
            continue

        n = len(s1_list)
        print(f'  {case}: {n} unique triads')
        plot_wcc_threshold_grid(
            np.array(s1_list),
            np.array(wcc_list),
            out_dir / out_name,
            title=rf'D18 {case} triads: $S_1 \times S_{{\rm WCC}}$ grid  (n={n})',
            cmap_name=cmap_name,
            bold_range=None,
        )


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
    print(f'Total records: {len(data)}')

    # ------------------------------------------------------------------
    # グラフ構築
    # ------------------------------------------------------------------
    print_section('Similarity Graph')
    G = build_similarity_graph(data)
    print(f'|V| = {G.number_of_nodes()}  |E| = {G.number_of_edges()}')

    # ------------------------------------------------------------------
    # Watts-Strogatz 局所クラスタリング係数
    # ------------------------------------------------------------------
    print_section('Watts-Strogatz Clustering Coefficients')
    adj = {n: set(G.neighbors(n)) for n in G.nodes()}
    clustering = compute_clustering_coefficients(adj)

    cv_vals = list(clustering.values())
    cv_sorted = sorted(cv_vals)
    n_cv = len(cv_vals)
    print(f'  C_v  min={cv_sorted[0]:.4f}  '
          f'median={cv_sorted[n_cv // 2]:.4f}  '
          f'max={cv_sorted[-1]:.4f}')
    print(f'  C_v = 0.0 : {sum(1 for v in cv_vals if v == 0.0)} nodes '
          f'({sum(1 for v in cv_vals if v == 0.0) / n_cv:.1%})')
    print(f'  C_v = 1.0 : {sum(1 for v in cv_vals if v == 1.0)} nodes '
          f'({sum(1 for v in cv_vals if v == 1.0) / n_cv:.1%})')

    # ------------------------------------------------------------------
    # 三角形列挙 + S_WCC スコアリング
    # ------------------------------------------------------------------
    print_section('Triadic WCC Scoring')
    triangles = enumerate_triangles(G)
    print(f'3-cliques: {len(triangles)}')

    results = []
    for a, b, c in triangles:
        s_ab = G[a][b]['sim']
        s_bc = G[b][c]['sim']
        s_ac = G[a][c]['sim']
        c_a, c_b, c_c = clustering[a], clustering[b], clustering[c]
        results.append({
            'A': a, 'B': b, 'C': c,
            's_AB': s_ab, 's_BC': s_bc, 's_AC': s_ac,
            'C_A': c_a, 'C_B': c_b, 'C_C': c_c,
            'score_wcc': score_wcc(c_a, c_b, c_c),
        })

    results.sort(key=lambda r: -r['score_wcc'])

    wcc_vals = [r['score_wcc'] for r in results]
    print(f'  S_WCC  min={min(wcc_vals):.4f}  '
          f'median={statistics.median(wcc_vals):.4f}  '
          f'max={max(wcc_vals):.4f}')

    print(f'\n  Top 20 triangles by S_WCC:')
    print(f'  {"rank":>4}  {"A":10}  {"B":10}  {"C":10}  '
          f'{"s_AB":6}  {"s_BC":6}  {"s_AC":6}  '
          f'{"C_A":6}  {"C_B":6}  {"C_C":6}  {"wcc":6}')
    for i, r in enumerate(results[:20], 1):
        print(f'  {i:4d}  {r["A"]:10}  {r["B"]:10}  {r["C"]:10}  '
              f'{r["s_AB"]:.4f}  {r["s_BC"]:.4f}  {r["s_AC"]:.4f}  '
              f'{r["C_A"]:.4f}  {r["C_B"]:.4f}  {r["C_C"]:.4f}  '
              f'{r["score_wcc"]:.4f}')

    # ------------------------------------------------------------------
    # 既存スコアとの対応マップ (triadic_scored.jsonl)
    # ------------------------------------------------------------------
    scored_map: dict[tuple, dict] = {}
    if TRIADIC_SCORED.exists():
        for row in load_data(TRIADIC_SCORED):
            scored_map[(row['A'], row['B'], row['C'])] = row
        print(f'\n  Loaded {len(scored_map)} records from triadic_scored.jsonl')
    else:
        print(f'\n  triadic_scored.jsonl not found — existing scores will be omitted')

    # ------------------------------------------------------------------
    # 結果保存
    # ------------------------------------------------------------------
    print_section('Saving Results')
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    out_path = OUTPUT_DIR / 'wcc_scored.jsonl'
    with open(out_path, 'w') as f:
        for rank, r in enumerate(results, 1):
            row: dict = {'rank': rank}
            row.update(r)
            key = (r['A'], r['B'], r['C'])
            if key in scored_map:
                ex = scored_map[key]
                row['score_weakest_link']      = ex['score_weakest_link']
                row['score_angular_tightness'] = ex['score_angular_tightness']
                row['score_bound_compliance']  = ex['score_bound_compliance']
                row['score_snn']               = ex['score_snn']
                row['confidence']              = ex['confidence']
            f.write(json.dumps(row) + '\n')
    print(f'All {len(results)} triangles → {out_path}')

    # ------------------------------------------------------------------
    # 可視化
    # ------------------------------------------------------------------
    print_section('Visualization')

    plot_wcc_distribution(
        results,
        OUTPUT_DIR / 'wcc_distribution.png',
    )
    plot_node_clustering(
        G, clustering,
        OUTPUT_DIR / 'wcc_node_clustering.png',
    )
    if scored_map:
        plot_wcc_vs_scores(
            results, scored_map,
            OUTPUT_DIR / 'wcc_vs_scores.png',
        )

    if scored_map:
        pairs = [
            (scored_map[key]['score_weakest_link'], r['score_wcc'])
            for r in results
            if (key := (r['A'], r['B'], r['C'])) in scored_map
        ]
        s1_arr  = np.array([p[0] for p in pairs])
        wcc_arr = np.array([p[1] for p in pairs])
        plot_wcc_threshold_grid(
            s1_arr, wcc_arr,
            OUTPUT_DIR / 'wcc_threshold_grid.png',
        )

    print('\nFP/FN WCC grids ...')
    plot_fp_fn_wcc_grids(results, OUTPUT_DIR)

    return results


if __name__ == '__main__':
    results = main()
