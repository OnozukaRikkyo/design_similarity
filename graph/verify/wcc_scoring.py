"""
Watts-Strogatz 局所クラスタリング係数による triadic スコアリング。

## 理論

Barabási (2016) に従い、無向引用グラフの各ノード v に対して局所クラスタリング係数を計算:

    C_v = 2 * L_v / (k_v * (k_v - 1))    (k_v >= 2 のとき、k_v < 2 のとき 0)

ここで k_v はノード v の次数、L_v は v の近傍ノード間に存在する辺数。
C_v は v の引用近傍がどれだけ密に接続しているかを示す。C_v ∈ [0, 1]。

各閉引用三角形 (A, B, C) に対して局所引用支持スコアを定義:

    S2 = min(C_A, C_B, C_C)

S2 はすべての3頂点が局所的に密な引用近傍に埋め込まれているときのみ高くなる。

計算は **無重み無向グラフ** に対して行う（networkx.clustering を使用）。
重み付きグラフを渡すと Barrat 式（加重クラスタリング）になり結果が変わるため注意。

依拠文献:
    Barabási, A.-L. (2016). Network science. Cambridge University Press.
    Opsahl, T. & Panzarasa, P. (2009). Clustering in weighted networks.
    Social Networks, 31(2):155–163.
    Watts, D.J. & Strogatz, S.H. (1998). Collective dynamics of 'small-world' networks.
    Nature, 393:440–442.
"""

import json
import statistics
import sys
from pathlib import Path

import networkx as nx
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from triad_plotter import has_consecutive_d_ids


# ==============================================================================
# Configuration
# ==============================================================================

ALL_JSONL      = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
TRIADIC_SCORED = Path('/home/sonozuka/design_similarity/graph/output/D18/triadic_scored.jsonl')
OUTPUT_DIR     = Path('/home/sonozuka/design_similarity/graph/output/D18/verify')
TRIADS_DIR     = Path('/home/sonozuka/design_similarity/graph/output/D18/triads')

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

def build_citation_graph(data: list[dict]) -> nx.Graph:
    """無重み無向引用グラフを構築する。局所クラスタリング係数の計算に使用。

    networkx.clustering() は重み付きグラフに対して Barrat 式（加重クラスタリング）を
    使うため、Watts-Strogatz 係数を得るには必ず無重みグラフを渡すこと。
    """
    G = nx.Graph()
    for d in data:
        G.add_edge(d['source'], d['target'])
    return G


def triad_adjusted_clustering_coeff(G: nx.Graph, a: str, b: str, c: str) -> list:
    """Triad-adjusted local clustering coefficient for each node in triad (a, b, c).

    Excludes the other two triad members from each node's neighborhood before
    computing the local clustering coefficient (C'_v). This removes the artificial
    inflation caused by the triad's own B–C, A–C, A–B edges being self-referential.

    For node v:
        N'(v) = N(v) \\ {A, B, C}
        k' = |N'(v)|
        C'_v = 2 * L'(v) / (k' * (k' - 1))    if k' >= 2
        C'_v = None                              if k' < 2  (undefined)

    Returns [C'_a, C'_b, C'_c]. Each element is None when k' < 2.
    """
    triad_set = {a, b, c}
    c_adjs = []
    for v in (a, b, c):
        N_v_ext = set(G.neighbors(v)) - triad_set
        k_ext = len(N_v_ext)
        if k_ext < 2:
            c_adjs.append(None)
        else:
            n_pairs = G.subgraph(N_v_ext).number_of_edges()
            c_adjs.append(2.0 * n_pairs / (k_ext * (k_ext - 1)))
    return c_adjs


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
# Visualization
# ==============================================================================

def plot_wcc_distribution(results: list[dict], output_path: Path) -> None:
    """S_WCC = min(C_A, C_B, C_C) (Watts-Strogatz 局所クラスタリング係数) の分布を描画する。"""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np

    wcc_vals = [r['score_wcc'] for r in results]

    fig, ax = plt.subplots(1, 1, figsize=(6, 4), facecolor='#f5f5f5')
    ax.set_facecolor('#f5f5f5')
    ax.hist(wcc_vals, bins=40, color='#ee6677', alpha=0.8, edgecolor='white', linewidth=0.4)
    ax.set_title('S_WCC = min(C_A, C_B, C_C)\n(Watts-Strogatz local clustering, per triangle)', fontsize=9)
    ax.set_xlabel('Score', fontsize=8)
    ax.set_ylabel('# triangles', fontsize=8)
    ax.tick_params(labelsize=7)
    med = float(np.median(wcc_vals))
    ax.axvline(med, color='#333333', linewidth=1.0, linestyle='--',
               label=f'median={med:.3f}')
    ax.legend(fontsize=6.5)

    fig.suptitle(
        f'D18 — Watts-Strogatz Local Clustering Score  ({len(results)} triangles)',
        fontsize=11,
    )
    plt.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f'WCC distribution figure → {output_path}')



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
# Fig: S1 × S_WCC 閾値グリッド — 共有ヘルパー
# ==============================================================================

def _compute_threshold_grids(
    s1_arr: np.ndarray,
    wcc_arr: np.ndarray,
    ths_s1: np.ndarray,
    ths_wcc: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """閾値グリッドのカウントを計算する。

    wcc_arr の np.nan は Undefined 扱いとして undef_col に集計し、
    main_grid には含めない。

    Returns:
        undef_col:  shape (n_s1,)   — S1 ≥ T1 かつ wcc が nan な件数
        main_grid:  shape (n_s1, n_wcc) — S1 ≥ T1 かつ wcc ≥ T2 な件数
    """
    n_s1  = len(ths_s1)
    n_wcc = len(ths_wcc)
    is_nan = np.isnan(wcc_arr)
    undef_col = np.zeros(n_s1, dtype=int)
    main_grid = np.zeros((n_s1, n_wcc), dtype=int)
    for i, t1 in enumerate(ths_s1):
        mask_s1 = s1_arr >= t1
        undef_col[i] = int((mask_s1 & is_nan).sum())
        for j, tw in enumerate(ths_wcc):
            main_grid[i, j] = int((mask_s1 & ~is_nan & (wcc_arr >= tw)).sum())
    return undef_col, main_grid


def _render_two_panel_grid(
    undef_col: np.ndarray,
    main_grid: np.ndarray,
    ths_s1: np.ndarray,
    ths_wcc: np.ndarray,
    out_path: Path,
    xlabel: str,
    bold_range: tuple[int, int] | None = None,
) -> None:
    """Undefined 列 + T2 グリッドの 2 パネルレイアウトを描画して保存する。

    両パネルとも Blues カラーマップを使用し、カラーバーのスケールを共有する。
    Undefined 列の幅は T2 グリッドの 1 列分と同じ幅に設定する。
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as mgridspec

    n_s1  = len(ths_s1)
    n_wcc = len(ths_wcc)
    cmap_obj  = plt.get_cmap('Blues')
    vmax_m    = max(1, min(300, int(main_grid[0, 0])))

    fig = plt.figure(figsize=(12.0, 6.0), facecolor='white')
    gs  = mgridspec.GridSpec(1, 2, figure=fig,
                             width_ratios=[1, n_wcc], wspace=0.015)
    ax_u = fig.add_subplot(gs[0, 0])
    ax_m = fig.add_subplot(gs[0, 1])

    # ---- Undefined 列 ----
    ax_u.imshow(undef_col.reshape(n_s1, 1), origin='upper', aspect='auto',
                cmap=cmap_obj, vmin=0, vmax=vmax_m)
    for i, val in enumerate(undef_col):
        norm_val = min(val / vmax_m, 1.0)
        r, g, b, _ = cmap_obj(norm_val)
        txt_color = 'white' if 0.299 * r + 0.587 * g + 0.114 * b < 0.5 else '#111111'
        ax_u.text(0, i, str(val), ha='center', va='center',
                  fontsize=13, color=txt_color)
    ax_u.set_xticks([0])
    ax_u.set_xticklabels(['Undefined'], fontsize=14, rotation=45, ha='right')
    ax_u.set_yticks(range(n_s1))
    ax_u.set_yticklabels([f'{t:.3f}' for t in ths_s1], fontsize=16)
    ax_u.set_ylabel('T1 (Weakest-Link Threshold)', fontsize=24)
    ax_u.tick_params(labelsize=16, width=0.6, length=3)
    for sp in ax_u.spines.values():
        sp.set_linewidth(0.6)
    ax_u.spines['right'].set_linewidth(2.2)

    # ---- T2 グリッド ----
    im = ax_m.imshow(main_grid, origin='upper', aspect='auto',
                     cmap=cmap_obj, vmin=0, vmax=vmax_m)
    for i in range(n_s1):
        for j in range(n_wcc):
            val = main_grid[i, j]
            norm_val = min(val / vmax_m, 1.0)
            r, g, b, _ = cmap_obj(norm_val)
            txt_color = 'white' if 0.299 * r + 0.587 * g + 0.114 * b < 0.5 else '#111111'
            fw = 'bold' if bold_range and bold_range[0] <= val <= bold_range[1] else 'normal'
            ax_m.text(j, i, str(val), ha='center', va='center',
                      fontsize=13, color=txt_color, fontweight=fw)
    ax_m.set_xticks(range(n_wcc))
    ax_m.set_xticklabels([f'{t:.3f}' for t in ths_wcc],
                          fontsize=16, rotation=45, ha='right')
    ax_m.set_yticks(range(n_s1))
    ax_m.set_yticklabels([])
    ax_m.set_xlabel(xlabel, fontsize=24)
    ax_m.tick_params(labelsize=16, width=0.6, length=3)
    for sp in ax_m.spines.values():
        sp.set_linewidth(0.6)

    cbar = fig.colorbar(im, ax=ax_m, shrink=0.85)
    cbar.set_label('Count', fontsize=24)
    cbar.ax.tick_params(labelsize=16)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'Threshold grid → {out_path}')


def plot_wcc_threshold_grid(
    s1_arr: np.ndarray,
    wcc_arr: np.ndarray,
    out_path: Path,
    bold_range: tuple[int, int] | None = None,
    undef_mask: np.ndarray | None = None,
) -> np.ndarray:
    """横軸 T_2 × 縦軸 T_1 の閾値グリッドを描画する。

    undef_mask が None のとき（FP/FN グリッドなど）は既存の 1 パネルレイアウトで描画する。
    undef_mask が与えられたとき（主グリッド）は _render_two_panel_grid を使った
    2 パネルレイアウト（Undefined 列 + T2 グリッド）で描画する。
    """
    ths_s1  = _S1_GRID_THS
    ths_wcc = _WCC_GRID_THS

    if undef_mask is not None:
        wcc_with_nan = wcc_arr.astype(float).copy()
        wcc_with_nan[undef_mask] = np.nan
        undef_col, main_grid = _compute_threshold_grids(s1_arr, wcc_with_nan, ths_s1, ths_wcc)
        _render_two_panel_grid(
            undef_col, main_grid, ths_s1, ths_wcc, out_path,
            xlabel='T2 (Local Clustering Coefficient Threshold)',
            bold_range=bold_range,
        )
        return main_grid

    # ---- 後方互換: 1 パネル（FP/FN グリッド用）----
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    n_s1  = len(ths_s1)
    n_wcc = len(ths_wcc)
    grid = np.zeros((n_s1, n_wcc), dtype=int)
    for i, t1 in enumerate(ths_s1):
        for j, tw in enumerate(ths_wcc):
            grid[i, j] = int(((s1_arr >= t1) & (wcc_arr >= tw)).sum())

    fig, ax = plt.subplots(figsize=(8.5, 6.0), facecolor='white')
    cmap_obj     = plt.get_cmap('Blues')
    vmax_display = max(1, min(300, int(grid[0, 0])))
    im = ax.imshow(grid, origin='upper', aspect='auto',
                   cmap=cmap_obj, vmin=0, vmax=vmax_display)
    ax.set_xticks(range(n_wcc))
    ax.set_xticklabels([f'{t:.3f}' for t in ths_wcc],
                       fontsize=16, rotation=45, ha='right')
    ax.set_yticks(range(n_s1))
    ax.set_yticklabels([f'{t:.3f}' for t in ths_s1], fontsize=16)
    ax.set_xlabel('T2 (Local Clustering Coefficient Threshold)', fontsize=24)
    ax.set_ylabel('T1 (Weakest-Link Threshold)', fontsize=24)
    for i in range(n_s1):
        for j in range(n_wcc):
            val = grid[i, j]
            norm_val = min(val / vmax_display, 1.0)
            r, g, b, _ = cmap_obj(norm_val)
            txt_color = 'white' if 0.299 * r + 0.587 * g + 0.114 * b < 0.5 else '#111111'
            fw = 'bold' if bold_range and bold_range[0] <= val <= bold_range[1] else 'normal'
            ax.text(j, i, str(val), ha='center', va='center',
                    fontsize=13, color=txt_color, fontweight=fw)
    ax.tick_params(labelsize=16, width=0.6, length=3)
    for sp in ax.spines.values():
        sp.set_linewidth(0.6)
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label('Count', fontsize=24)
    cbar.ax.tick_params(labelsize=16)
    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'WCC threshold grid → {out_path}')
    return grid


def plot_adj_wcc_threshold_grid(
    s1_arr: np.ndarray,
    wcc_adj_arr: np.ndarray,
    out_path: Path,
) -> None:
    """S1 × S2_adj 閾値グリッド（Triad-adjusted WCC）。_render_two_panel_grid に委譲する。

    wcc_adj_arr の np.nan は Undefined（k_ext < 2）として左端列に集計する。
    """
    undef_col, main_grid = _compute_threshold_grids(
        s1_arr, wcc_adj_arr, _S1_GRID_THS, _WCC_GRID_THS,
    )
    _render_two_panel_grid(
        undef_col, main_grid, _S1_GRID_THS, _WCC_GRID_THS, out_path,
        xlabel='T2 (Triad-Adjusted Local Clustering Coefficient Threshold)',
    )


def plot_fp_fn_wcc_grids(results: list[dict], out_dir: Path, suffix: str = '') -> None:
    """fp.csv / fn.csv の triad を対象に S1 × S_WCC 閾値グリッドを描画する。

    fp.csv・fn.csv は discord_analysis.py が出力したもの。
    1 triad が複数行にわたる場合（辺ごとの行）は (A, B, C) で重複除去する。

    Args:
        suffix: 出力ファイル名のサフィックス（例: '_no_consec'）。
    """
    import csv

    wcc_map     = {(r['A'], r['B'], r['C']): r['score_wcc']     for r in results}
    wcc_adj_map = {(r['A'], r['B'], r['C']): r.get('score_wcc_adj') for r in results}

    for case, csv_name, out_stem in [
        ('FP', 'fp.csv', 'wcc_fp_grid'),
        ('FN', 'fn.csv', 'wcc_fn_grid'),
    ]:
        csv_path = out_dir / csv_name
        if not csv_path.exists():
            print(f'  [skip] {csv_path} not found')
            continue

        # (A, B, C) で重複除去しつつ S1, S_WCC, S_WCC_adj を収集
        seen: set[tuple] = set()
        s1_list:    list[float] = []
        wcc_list:   list[float] = []
        undef_list: list[bool]  = []
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
                undef_list.append(wcc_adj_map.get(key) is None)

        if not s1_list:
            print(f'  [skip] no matching triads for {case}')
            continue

        n = len(s1_list)
        print(f'  {case}{suffix}: {n} unique triads')
        plot_wcc_threshold_grid(
            np.array(s1_list),
            np.array(wcc_list),
            out_dir / f'{out_stem}{suffix}.png',
            bold_range=None,
            undef_mask=np.array(undef_list),
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

    # 局所クラスタリング係数は無重み無向グラフで計算する。
    # nx.clustering() は重み付きグラフを渡すと Barrat 加重式を使うため
    # Watts-Strogatz の結果と異なる値になる。
    G_unweighted = build_citation_graph(data)
    clustering = nx.clustering(G_unweighted)
    cv_vals_all = list(clustering.values())
    print(f'  Local clustering: min={min(cv_vals_all):.4f}  '
          f'median={statistics.median(cv_vals_all):.4f}  '
          f'max={max(cv_vals_all):.4f}')
    n_zero = sum(1 for v in cv_vals_all if v == 0.0)
    n_one  = sum(1 for v in cv_vals_all if v == 1.0)
    print(f'  C_v=0: {n_zero}  C_v=1: {n_one}  0<C_v<1: {len(cv_vals_all)-n_zero-n_one}')

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
        # S2 (standard): min(C_A, C_B, C_C) Watts-Strogatz
        wcc = min(clustering[a], clustering[b], clustering[c])
        # S2_adj: triad 内部エッジを除外した調整済み局所クラスタリング係数
        c_adjs = triad_adjusted_clustering_coeff(G_unweighted, a, b, c)
        wcc_adj = min(c_adjs) if all(x is not None for x in c_adjs) else None
        results.append({
            'A': a, 'B': b, 'C': c,
            's_AB': s_ab, 's_BC': s_bc, 's_AC': s_ac,
            'score_wcc': wcc,
            'score_wcc_adj': wcc_adj,
            'cc_adj_A': c_adjs[0], 'cc_adj_B': c_adjs[1], 'cc_adj_C': c_adjs[2],
        })

    results.sort(key=lambda r: -r['score_wcc'])

    wcc_vals = [r['score_wcc'] for r in results]
    print(f'  S_WCC (standard)  min={min(wcc_vals):.4f}  '
          f'median={statistics.median(wcc_vals):.4f}  '
          f'max={max(wcc_vals):.4f}')

    wcc_adj_defined = [r['score_wcc_adj'] for r in results if r['score_wcc_adj'] is not None]
    wcc_adj_undef   = sum(1 for r in results if r['score_wcc_adj'] is None)
    print(f'  S_WCC_adj         defined={len(wcc_adj_defined)}  undefined={wcc_adj_undef}')
    if wcc_adj_defined:
        print(f'  S_WCC_adj         min={min(wcc_adj_defined):.4f}  '
              f'median={statistics.median(wcc_adj_defined):.4f}  '
              f'max={max(wcc_adj_defined):.4f}')

    print(f'\n  Top 20 triangles by S_WCC (standard):')
    print(f'  {"rank":>4}  {"A":10}  {"B":10}  {"C":10}  '
          f'{"s_AB":6}  {"s_BC":6}  {"s_AC":6}  {"wcc":6}  {"wcc_adj":8}')
    for i, r in enumerate(results[:20], 1):
        adj_str = f'{r["score_wcc_adj"]:.4f}' if r['score_wcc_adj'] is not None else 'Undef'
        print(f'  {i:4d}  {r["A"]:10}  {r["B"]:10}  {r["C"]:10}  '
              f'{r["s_AB"]:.4f}  {r["s_BC"]:.4f}  {r["s_AC"]:.4f}  '
              f'{r["score_wcc"]:.4f}  {adj_str:>8}')

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
    if scored_map:
        plot_wcc_vs_scores(
            results, scored_map,
            OUTPUT_DIR / 'wcc_vs_scores.png',
        )

    if scored_map:
        pairs = [
            (scored_map[key]['score_weakest_link'], r['score_wcc'], r['score_wcc_adj'])
            for r in results
            if (key := (r['A'], r['B'], r['C'])) in scored_map
        ]
        s1_arr   = np.array([p[0] for p in pairs])
        wcc_arr  = np.array([p[1] for p in pairs])
        undef_m  = np.array([p[2] is None for p in pairs])
        plot_wcc_threshold_grid(
            s1_arr, wcc_arr,
            OUTPUT_DIR / 'wcc_threshold_grid.png',
            bold_range=None,
            undef_mask=undef_m,
        )

        # Adj WCC グリッド（全体）
        pairs_adj = [
            (scored_map[key]['score_weakest_link'], r['score_wcc_adj'])
            for r in results
            if (key := (r['A'], r['B'], r['C'])) in scored_map
        ]
        s1_adj_arr  = np.array([p[0] for p in pairs_adj])
        wcc_adj_arr = np.array([
            x if x is not None else np.nan
            for x in (p[1] for p in pairs_adj)
        ])
        plot_adj_wcc_threshold_grid(
            s1_adj_arr, wcc_adj_arr,
            OUTPUT_DIR / 'wcc_adj_threshold_grid.png',
        )

        # 連番D-IDを含むtriadを除去したグリッド + JSONL保存
        results_nc = [
            r for r in results
            if (r['A'], r['B'], r['C']) in scored_map
            and not has_consecutive_d_ids(r['A'], r['B'], r['C'])
        ]
        n_removed = len(pairs) - len(results_nc)
        print(f'  consecutive-D filter: {n_removed} triads removed, {len(results_nc)} remain')

        TRIADS_DIR.mkdir(parents=True, exist_ok=True)
        nc_jsonl = TRIADS_DIR / 'wcc_no_consec.jsonl'
        with open(nc_jsonl, 'w') as f:
            for rank, r in enumerate(results_nc, 1):
                row = dict(r)
                row['rank'] = rank
                ex = scored_map[(r['A'], r['B'], r['C'])]
                row['score_weakest_link']      = ex['score_weakest_link']
                row['score_angular_tightness'] = ex['score_angular_tightness']
                row['score_snn']               = ex['score_snn']
                row['confidence']              = ex['confidence']
                row['cc_A'] = clustering.get(r['A'], 0.0)
                row['cc_B'] = clustering.get(r['B'], 0.0)
                row['cc_C'] = clustering.get(r['C'], 0.0)
                f.write(json.dumps(row) + '\n')
        print(f'  → {nc_jsonl}  ({len(results_nc)} triads)')

        s1_nc    = np.array([scored_map[(r['A'], r['B'], r['C'])]['score_weakest_link'] for r in results_nc])
        wcc_nc   = np.array([r['score_wcc'] for r in results_nc])
        undef_nc = np.array([r['score_wcc_adj'] is None for r in results_nc])
        plot_wcc_threshold_grid(
            s1_nc, wcc_nc,
            OUTPUT_DIR / 'wcc_threshold_grid_no_consec.png',
            bold_range=None,
            undef_mask=undef_nc,
        )

        # Adj WCC グリッド（non-consecutive）
        s1_nc_adj  = np.array([scored_map[(r['A'], r['B'], r['C'])]['score_weakest_link'] for r in results_nc])
        wcc_nc_adj = np.array([
            r['score_wcc_adj'] if r['score_wcc_adj'] is not None else np.nan
            for r in results_nc
        ])
        plot_adj_wcc_threshold_grid(
            s1_nc_adj, wcc_nc_adj,
            OUTPUT_DIR / 'wcc_adj_threshold_grid_no_consec.png',
        )

    print('\nFP/FN WCC grids (original) ...')
    plot_fp_fn_wcc_grids(results, OUTPUT_DIR)

    if scored_map:
        print('\nFP/FN WCC grids (no_consec) ...')
        plot_fp_fn_wcc_grids(results_nc, OUTPUT_DIR, suffix='_no_consec')

    return results


if __name__ == '__main__':
    results = main()
