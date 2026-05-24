"""
D18 閾値設計支援可視化 + Discord Triad 分析。

[閾値分析（全 triad）]
  scatter_s1_s3.png       — S1×S2 散布図（全 triad、S3 色付け）
  parallel_coordinates.png — 平行座標（S1/S2/S3）
  threshold_survival.png  — 閾値 vs 残存 triad 数の生存曲線
  threshold_grid.png      — S1×S2 閾値グリッド（GT 候補根拠図）
  threshold_grid.csv      — 同上 CSV

[Discord triad 分析（FP/FN 乖離辺を含む三角形）]
  FP 辺: rank ≤ rank_fp AND sim ≥ sim_fp AND MLLM=No（ベクトルは類似、MLLM は非類似）
  FN 辺: rank ≥ rank_fn AND sim < sim_fn AND MLLM=Yes（ベクトルは非類似、MLLM は類似）

  discord_scatter.png     — S1×S2 散布図（全 triad + FP/FN 強調）
  fp_grid.png / fn_grid.png — FP/FN triad の S1×S2 閾値グリッド
  fp.csv / fn.csv         — FP/FN triad 一覧
  fp_001.png 〜 / fn_001.png 〜 — 個別三角形画像

出力: graph/output/D18/verify/

実行:
  cd /home/sonozuka/design_similarity
  python graph/verify/discord_analysis.py
  python graph/verify/discord_analysis.py --rank-fp 5 --sim-fp 0.95 -N 30
"""

import argparse
import csv
import glob
import json
import sys
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.cm as cm
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy.ndimage import binary_dilation

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_processor import ImageProcessor

# ==============================================================================
# パス定数
# ==============================================================================

ALL_JSONL_TMPL    = '/mnt/eightthdd/uspto/class/{CLASS}/rank_judgments/cosine_numpy/all.jsonl'
SCORED_JSONL_TMPL = 'graph/output/{CLASS}/triadic_scored.jsonl'
DATA_CSV_GLOB     = '/mnt/eightthdd/uspto/data/*.csv'
OUTPUT_TMPL       = 'graph/output/{CLASS}/verify'

_GRID_THS = np.round(np.arange(0.800, 1.001, 0.025), 3)

# GT 閾値候補 (T1, T2)
_GT_PAIRS = [
    (0.90, 0.90),
    (0.95, 0.85),
    (0.95, 0.90),
]

# ==============================================================================
# スタイル定数
# ==============================================================================

SPINE_LW = 0.6
TICK_FS  = 7
LABEL_FS = 8
TITLE_FS = 9


def _style_ax(ax: plt.Axes) -> None:
    ax.tick_params(labelsize=TICK_FS, width=0.5, length=3)
    for sp in ax.spines.values():
        sp.set_linewidth(SPINE_LW)

# ==============================================================================
# データ読み込み
# ==============================================================================

def load_all_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def load_triadic_scored(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def build_judgment_map(records: list[dict]) -> dict[frozenset, dict]:
    """frozenset({source, target}) → edge record のマップを構築する。

    同一ペアに複数タイプが存在する場合は perspective を優先する。
    """
    m: dict[frozenset, dict] = {}
    for r in records:
        key = frozenset({r['source'], r['target']})
        if key not in m or r['type'] == 'perspective':
            m[key] = r
    return m


def build_image_map(records: list[dict]) -> dict[str, str]:
    """patent_id → image_path のマップを構築する。"""
    m: dict[str, str] = {}
    for r in records:
        if r.get('source_image'):
            m[r['source']] = r['source_image']
        if r.get('target_image'):
            m[r['target']] = r['target_image']
    return m


def build_title_map(patent_ids: set[str]) -> dict[str, str]:
    """data/{year}.csv から patent_id → title のマップを構築する。"""
    title_map: dict[str, str] = {}
    for csv_path in sorted(glob.glob(DATA_CSV_GLOB)):
        df = pd.read_csv(csv_path, usecols=['id', 'title'])
        df['id'] = df['id'].astype(str)
        for _, row in df[df['id'].isin(patent_ids)].iterrows():
            title_map[row['id']] = str(row['title'])
        if len(title_map) >= len(patent_ids):
            break
    return title_map

# ==============================================================================
# FP/FN 辺・triad の抽出
# ==============================================================================

def find_discord_edge_keys(
    judg_map: dict[frozenset, dict],
    rank_fp: int, sim_fp: float,
    rank_fn: int, sim_fn: float,
) -> tuple[set[frozenset], set[frozenset]]:
    """FP と FN の辺キーセットを返す。"""
    fp_keys: set[frozenset] = set()
    fn_keys: set[frozenset] = set()
    for key, r in judg_map.items():
        if r['rank'] <= rank_fp and r['similarity'] >= sim_fp and r['judgment'] == 'No':
            fp_keys.add(key)
        if r['rank'] >= rank_fn and r['similarity'] < sim_fn and r['judgment'] == 'Yes':
            fn_keys.add(key)
    return fp_keys, fn_keys


def find_discord_triads(
    triads: list[dict],
    discord_keys: set[frozenset],
    judg_map: dict[frozenset, dict],
) -> list[dict]:
    """Discord 辺を 1 本以上含む三角形を返す。

    戻り値の各要素:
      triad        — triadic_scored.jsonl の 1 レコード
      discord_recs — Discord 辺の edge record リスト（1〜3 本）
    """
    result = []
    for t in triads:
        A, B, C = t['A'], t['B'], t['C']
        edge_keys = {
            'AB': frozenset({A, B}),
            'BC': frozenset({B, C}),
            'AC': frozenset({A, C}),
        }
        discord_recs = []
        for label, key in edge_keys.items():
            if key in discord_keys:
                rec = judg_map.get(key)
                if rec:
                    discord_recs.append({'label': label, 'key': key, 'rec': rec})
        if discord_recs:
            result.append({'triad': t, 'discord_recs': discord_recs})
    return result

# ==============================================================================
# Fig 1: S1–S2 散布図（全 triad、S3 色付け）
# ==============================================================================

def plot_scatter_all(data: dict, out_dir: Path) -> None:
    """S1 vs S2 の散布図（GT criterion 空間）。GT 閾値候補の格子線を重ねる。"""
    fig, ax = plt.subplots(figsize=(4.0, 3.4), facecolor='white')

    sc = ax.scatter(
        data['s1'], data['s3'],
        c=data['s2'], cmap=cm.plasma,
        s=4, alpha=0.55, linewidths=0,
        rasterized=True,
    )
    cb = fig.colorbar(sc, ax=ax, pad=0.02)
    cb.set_label('S3 (angular tightness)', fontsize=LABEL_FS)
    cb.ax.tick_params(labelsize=TICK_FS)

    t1_drawn, t3_drawn = set(), set()
    for t1, t3, *_ in _GT_PAIRS:
        if t1 not in t1_drawn:
            ax.axvline(t1, color='#1f77b4', lw=0.8, ls='--', alpha=0.6)
            ax.text(t1 + 0.002, 0.62, f'T₁={t1}', fontsize=5.5,
                    color='#1f77b4', va='bottom', rotation=90)
            t1_drawn.add(t1)
        if t3 not in t3_drawn:
            ax.axhline(t3, color='#d62728', lw=0.8, ls='--', alpha=0.6)
            ax.text(0.62, t3 + 0.002, f'T₂={t3}', fontsize=5.5,
                    color='#d62728', va='bottom')
            t3_drawn.add(t3)

    ax.set_xlabel('$S_1$ (weakest-link similarity)', fontsize=LABEL_FS)
    ax.set_ylabel('$S_2$ (Schubert bound compliance)', fontsize=LABEL_FS)
    ax.set_title(
        f'D18 triads  (n={len(data["s1"])})\n'
        r'GT criterion space: $S_1 \geq T_1$ and $S_2 \geq T_2$',
        fontsize=TITLE_FS,
    )
    ax.set_xlim(0.60, 1.01)
    ax.set_ylim(0.60, 1.01)
    _style_ax(ax)

    fig.tight_layout()
    out = out_dir / 'scatter_s1_s3.png'
    fig.savefig(out, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  → {out}')

# ==============================================================================
# Fig 2: 平行座標プロット（S1 / S2 / S3, min(S1,S2) で色付け）
# ==============================================================================

def plot_parallel_coordinates(data: dict, out_dir: Path, top_n: int = 50) -> None:
    """S1, S2, S3 の 3 軸平行座標プロット。

    全 triad を薄いグレーで描き、min(S1,S2) 上位 top_n を plasma で重ね描き。
    """
    axes_keys   = ['s1', 's3', 's2']
    axes_labels = ['$S_1$\n(weakest-link)', '$S_2$\n(Schubert compliance)',
                   '$S_3$\n(angular tightness)']
    n_axes   = len(axes_keys)
    n_triads = len(data['s1'])

    vals = np.stack([data[k] for k in axes_keys], axis=1)
    vmin = vals.min(axis=0)
    vmax = vals.max(axis=0)
    norm_vals = (vals - vmin) / np.where(vmax - vmin > 0, vmax - vmin, 1)

    min_s1s2  = np.minimum(data['s1'], data['s3'])
    sorted_idx = np.argsort(min_s1s2)[::-1]
    top_idx    = sorted_idx[:min(top_n, n_triads)]
    other_idx  = sorted_idx[min(top_n, n_triads):]

    conf_norm = mcolors.Normalize(vmin=min_s1s2[top_idx[-1]], vmax=min_s1s2[top_idx[0]])
    cmap_pc   = cm.plasma

    fig, ax = plt.subplots(figsize=(5.5, 3.8), facecolor='white')
    ax.set_xlim(-0.05, n_axes - 0.95)
    ax.set_ylim(-0.05, 1.05)
    x_pos = np.arange(n_axes, dtype=float)

    for i in other_idx:
        ax.plot(x_pos, norm_vals[i], color='#cccccc', lw=0.3, alpha=0.4, rasterized=True)
    for i in reversed(top_idx):
        ax.plot(x_pos, norm_vals[i], color=cmap_pc(conf_norm(min_s1s2[i])),
                lw=0.9, alpha=0.85, rasterized=True)

    for j, (label, vn, vx) in enumerate(zip(axes_labels, vmin, vmax)):
        ax.axvline(j, color='#444444', lw=0.8)
        for tick in np.linspace(0, 1, 5):
            ax.text(j - 0.04, tick, f'{vn + tick * (vx - vn):.2f}',
                    ha='right', va='center', fontsize=5.5)
        ax.text(j, 1.07, label, ha='center', va='bottom',
                fontsize=LABEL_FS, fontweight='bold')

    sm = cm.ScalarMappable(cmap=cmap_pc, norm=conf_norm)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.8)
    cb.set_label(f'min($S_1$, $S_2$)\n(top-{top_n} colored)', fontsize=LABEL_FS)
    cb.ax.tick_params(labelsize=TICK_FS)

    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(
        f'D18 parallel coordinates  (n={n_triads},  top-{top_n} by min($S_1$,$S_2$) highlighted)',
        fontsize=TITLE_FS,
    )
    fig.tight_layout()
    out = out_dir / 'parallel_coordinates.png'
    fig.savefig(out, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  → {out}')

# ==============================================================================
# Fig 3: 閾値 vs 残存 triad 数（生存曲線）
# ==============================================================================

def plot_threshold_survival(data: dict, out_dir: Path) -> None:
    """S1, S2, S1&S2 複合条件の生存曲線を 1 パネルで比較する。"""
    thresholds = np.linspace(0.0, 1.0, 401)
    s1, s3 = data['s1'], data['s3']
    n = len(s1)

    count_s1   = np.array([(s1 >= t).sum() for t in thresholds])
    count_s3   = np.array([(s3 >= t).sum() for t in thresholds])
    count_s1s3 = np.array([((s1 >= t) & (s3 >= t)).sum() for t in thresholds])

    fig, ax = plt.subplots(figsize=(5.0, 3.4), facecolor='white')
    ax.plot(thresholds, count_s1,   color='#4477aa', lw=1.4,
            label='$S_1$ only (weakest-link)')
    ax.plot(thresholds, count_s3,   color='#ee6677', lw=1.4,
            label='$S_2$ only (Schubert compliance)')
    ax.plot(thresholds, count_s1s3, color='#228833', lw=1.8, ls='-.',
            label='$S_1$ \\& $S_2$ (GT criterion)')
    ax.axhspan(20, 50, color='#ccbb44', alpha=0.18, label='GT target zone (20–50)')

    for t1, *_ in _GT_PAIRS:
        idx = np.searchsorted(thresholds, t1)
        c   = int(count_s1s3[min(idx, len(count_s1s3) - 1)])
        ax.axvline(t1, color='#555555', lw=0.6, ls='--', alpha=0.6)
        ax.text(t1 + 0.003, c + n * 0.01, f'{c}',
                ha='left', va='bottom', fontsize=5.5, color='#228833')

    ax.set_xlabel('Threshold $T$', fontsize=LABEL_FS)
    ax.set_ylabel('# triads $\\geq T$', fontsize=LABEL_FS)
    ax.set_title(f'D18 — threshold survival curves  (total n={n})', fontsize=TITLE_FS)
    ax.set_xlim(0.60, 1.0)
    ax.set_ylim(0, n * 1.08)
    ax.legend(fontsize=6.5, framealpha=0.9, edgecolor='gray', loc='upper right')
    _style_ax(ax)

    fig.tight_layout()
    out = out_dir / 'threshold_survival.png'
    fig.savefig(out, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  → {out}')

# ==============================================================================
# Fig 4: S1×S2 閾値グリッド（論文の根拠図） — plot_s1s3_grid + CSV 出力
# ==============================================================================

def plot_threshold_grid_all(s1: np.ndarray, s3: np.ndarray, out_dir: Path) -> None:
    """全 triad の S1×S2 閾値グリッドを描画し、CSV も出力する。"""
    out_png = out_dir / 'threshold_grid.png'
    grid = plot_s1s3_grid(
        s1, s3, out_png,
        title=r'D18 — GT candidates: $S_1 \geq T_1$ and $S_2 \geq T_2$',
        cmap_name='Blues_r',
        vmax_cap=200,
        bold_range=(20, 50),
    )
    out_csv = out_dir / 'threshold_grid.csv'
    ths = _GRID_THS
    with open(out_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['s1_th \\ s2_th'] + [f'{t:.3f}' for t in ths])
        for i, t1 in enumerate(ths):
            writer.writerow([f'{t1:.3f}'] + list(grid[i]))
    print(f'  → {out_csv}')

# ==============================================================================
# Fig 5: FP/FN 散布図（S1×S2 空間、全 triad 背景 + FP/FN 強調）
# ==============================================================================

def plot_scatter_discord(
    triads: list[dict],
    fp_items: list[dict],
    fn_items: list[dict],
    out_path: Path,
) -> None:
    s1_all = np.array([t['score_weakest_link']     for t in triads])
    s3_all = np.array([t['score_bound_compliance'] for t in triads])

    fp_triads = [item['triad'] for item in fp_items]
    fn_triads = [item['triad'] for item in fn_items]

    fig, ax = plt.subplots(figsize=(4.5, 3.8), facecolor='white')

    # 全 triad（グレー背景）
    ax.scatter(s1_all, s3_all, s=4, color='#aaaaaa', alpha=0.4,
               linewidths=0, zorder=1, label=f'All triads (n={len(triads)})')

    # FP（オレンジ★）
    if fp_triads:
        s1_fp = [t['score_weakest_link']     for t in fp_triads]
        s3_fp = [t['score_bound_compliance'] for t in fp_triads]
        ax.scatter(s1_fp, s3_fp, s=50, marker='*', color='#ff7f00',
                   alpha=0.85, linewidths=0.3, edgecolors='k', zorder=4,
                   label=f'FP triads (n={len(fp_triads)})')

    # FN（緑★）
    if fn_triads:
        s1_fn = [t['score_weakest_link']     for t in fn_triads]
        s3_fn = [t['score_bound_compliance'] for t in fn_triads]
        ax.scatter(s1_fn, s3_fn, s=50, marker='*', color='#33a02c',
                   alpha=0.85, linewidths=0.3, edgecolors='k', zorder=4,
                   label=f'FN triads (n={len(fn_triads)})')

    # GT 閾値候補の格子線
    t1_drawn, t3_drawn = set(), set()
    for t1, t3 in _GT_PAIRS:
        if t1 not in t1_drawn:
            ax.axvline(t1, color='#1f77b4', lw=0.8, ls='--', alpha=0.6)
            ax.text(t1 + 0.003, 0.62, f'T₁={t1}', fontsize=5.5,
                    color='#1f77b4', va='bottom', rotation=90)
            t1_drawn.add(t1)
        if t3 not in t3_drawn:
            ax.axhline(t3, color='#d62728', lw=0.8, ls='--', alpha=0.6)
            ax.text(0.62, t3 + 0.003, f'T₂={t3}', fontsize=5.5,
                    color='#d62728', va='bottom')
            t3_drawn.add(t3)

    ax.set_xlabel('$S_1$ (weakest-link similarity)', fontsize=8)
    ax.set_ylabel('$S_2$ (Schubert bound compliance)', fontsize=8)
    ax.set_title(
        f'D18 — FP/FN triads in S₁×S₂ space\n'
        r'GT criterion: $S_1 \geq T_1$ and $S_2 \geq T_2$',
        fontsize=8,
    )
    ax.set_xlim(0.40, 1.01)
    ax.set_ylim(0.20, 1.01)
    ax.legend(fontsize=6.5, framealpha=0.9, loc='lower left')
    ax.tick_params(labelsize=7)
    for sp in ax.spines.values():
        sp.set_linewidth(0.6)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  → {out_path}')

# ==============================================================================
# S1×S3 閾値グリッド（共通関数 — threshold_analysis.py からもインポートして使用）
# ==============================================================================

def plot_s1s3_grid(
    s1: np.ndarray,
    s3: np.ndarray,
    out_path: Path,
    title: str,
    cmap_name: str = 'Blues_r',
    vmax_cap: int = 0,
    bold_range: tuple[int, int] | None = None,
) -> np.ndarray:
    """S1×S3 閾値グリッドを描画して保存する。grid 配列を返す（CSV 出力に使用）。

    凡例・カラーバー・輪郭線なし。
    セル文字色は輝度に基づいて白/黒を自動選択。
    スタイルをここ 1 箇所で管理する（threshold_analysis.py も本関数を使用）。

    Args:
        vmax_cap: カラースケール上限のキャップ値（0 = キャップなし）。
        bold_range: この範囲 [lo, hi] の値を太字で表示（None = 全セル通常）。
    """
    ths = _GRID_THS
    n_th = len(ths)

    grid = np.zeros((n_th, n_th), dtype=int)
    for i, t1 in enumerate(ths):
        for j, t3 in enumerate(ths):
            grid[i, j] = int(((s1 >= t1) & (s3 >= t3)).sum())

    fig, ax = plt.subplots(figsize=(6.5, 5.8), facecolor='white')

    vmax_display = max(1, int(grid[0, 0]))
    if vmax_cap > 0:
        vmax_display = min(vmax_cap, vmax_display)
    cmap_obj = plt.get_cmap(cmap_name)
    ax.imshow(grid, origin='upper', aspect='auto',
              cmap=cmap_obj, vmin=0, vmax=vmax_display)

    ax.set_xticks(range(n_th))
    ax.set_xticklabels([f'{t:.3f}' for t in ths],
                       fontsize=10, rotation=45, ha='right')
    ax.set_yticks(range(n_th))
    ax.set_yticklabels([f'{t:.3f}' for t in ths], fontsize=10)
    ax.set_xlabel('$T_2$ (Schubert bound threshold)', fontsize=12)
    ax.set_ylabel('$T_1$ (weakest-link threshold)', fontsize=12)
    ax.set_title(title, fontsize=13)

    # セル内の件数（輝度に基づいて白/黒を自動選択）
    for i in range(n_th):
        for j in range(n_th):
            val = grid[i, j]
            norm_val = min(val / vmax_display, 1.0)
            r, g, b, _ = cmap_obj(norm_val)
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            txt_color = 'white' if luminance < 0.5 else '#111111'
            fw = 'bold' if (bold_range and bold_range[0] <= val <= bold_range[1]) else 'normal'
            ax.text(j, i, str(val), ha='center', va='center',
                    fontsize=9, color=txt_color, fontweight=fw)

    ax.tick_params(labelsize=10, width=0.6, length=3)
    for sp in ax.spines.values():
        sp.set_linewidth(0.6)

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  → {out_path}')
    return grid

# ==============================================================================
# CSV エクスポート
# ==============================================================================

def export_csv(items: list[dict], title_map: dict[str, str], out_path: Path) -> None:
    fieldnames = [
        'seq', 'A', 'B', 'C',
        's_AB', 's_BC', 's_AC',
        'S1_weakest_link', 'S2_angular_tightness', 'S3_bound_compliance',
        'S4_snn', 'confidence', 'triad_rank',
        'discord_edge', 'edge_rank', 'edge_sim',
        'judgment', 'llm_confidence', 'reason',
        'title_A', 'title_B', 'title_C',
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for seq, item in enumerate(items, 1):
            t = item['triad']
            for dr in item['discord_recs']:
                rec = dr['rec']
                writer.writerow({
                    'seq': seq,
                    'A': t['A'], 'B': t['B'], 'C': t['C'],
                    's_AB': f"{t['s_AB']:.6f}",
                    's_BC': f"{t['s_BC']:.6f}",
                    's_AC': f"{t['s_AC']:.6f}",
                    'S1_weakest_link':       f"{t['score_weakest_link']:.6f}",
                    'S2_angular_tightness':  f"{t['score_angular_tightness']:.6f}",
                    'S3_bound_compliance':   f"{t['score_bound_compliance']:.6f}",
                    'S4_snn':                f"{t['score_snn']:.6f}",
                    'confidence':            f"{t['confidence']:.6f}",
                    'triad_rank':            t['rank'],
                    'discord_edge':          dr['label'],
                    'edge_rank':             rec['rank'],
                    'edge_sim':              f"{rec['similarity']:.6f}",
                    'judgment':              rec['judgment'],
                    'llm_confidence':        rec['confidence'],
                    'reason':                rec['reason'],
                    'title_A': title_map.get(t['A'], ''),
                    'title_B': title_map.get(t['B'], ''),
                    'title_C': title_map.get(t['C'], ''),
                })
    print(f'  → {out_path}')

# ==============================================================================
# 画像処理
# ==============================================================================

_DILATE_STRUCT = np.ones((3, 3), dtype=bool)

TITLE_FS   = 9
CAPTION_FS = 7.5
META_FS    = 7.5


def load_image(path: str | None) -> np.ndarray | None:
    if not path:
        return None
    try:
        img = ImageProcessor.process_file(path).convert('L')
        arr = np.array(img)
        line_mask = binary_dilation(arr < 128, structure=_DILATE_STRUCT, iterations=1)
        return np.where(line_mask, 0, 255).astype(np.uint8)
    except Exception as e:
        print(f'  [warn] {path}: {e}', file=sys.stderr)
        return None


def _panel(ax: plt.Axes, img_path: str | None, patent_id: str,
           title: str, caption: str,
           discord_color: str | None = None) -> None:
    """特許 1 件分の画像パネル。discord_color を指定するとスパイン（枠）を太く色付け。"""
    arr = load_image(img_path)
    ax.set_xticks([])
    ax.set_yticks([])
    if arr is not None:
        ax.imshow(arr, aspect='equal', interpolation='nearest',
                  cmap='gray', vmin=0, vmax=255)
    else:
        ax.set_facecolor('#e8e8e8')
        ax.text(0.5, 0.5, 'N/A', ha='center', va='center',
                transform=ax.transAxes, fontsize=CAPTION_FS)

    ax.set_title(patent_id, fontsize=TITLE_FS, pad=3, fontweight='bold')
    wrapped_title = '\n'.join(textwrap.wrap(title, width=22)) if title else ''
    ax.set_xlabel(f'{wrapped_title}\n{caption}', fontsize=CAPTION_FS, labelpad=4)

    lw = 2.5 if discord_color else 0.6
    color = discord_color or '#888888'
    for sp in ax.spines.values():
        sp.set_linewidth(lw)
        sp.set_color(color)

# ==============================================================================
# 個別三角形画像（triad_001.png スタイル + Discord 辺ハイライト）
# ==============================================================================

def get_cm_label(rec: dict | None, rank_fp: int, sim_fp: float) -> str:
    """辺の Confusion Matrix ラベル（TP/FP/FN/TN）を返す。

    予測 Positive: rank ≤ rank_fp AND sim ≥ sim_fp（FP 検出条件と同一）
    実態 Positive: judgment == 'Yes'（MLLM が類似と判定）
    """
    if rec is None:
        return '??'
    pred_pos = (rec.get('rank', 9999) <= rank_fp) and (rec.get('similarity', 0) >= sim_fp)
    gt_pos   = rec.get('judgment', '') == 'Yes'
    if pred_pos and gt_pos:       return 'TP'
    if pred_pos and not gt_pos:   return 'FP'
    if not pred_pos and gt_pos:   return 'FN'
    return 'TN'


def plot_triad_discord(item: dict, seq: int, title_map: dict[str, str],
                        img_map: dict[str, str],
                        judg_map: dict[frozenset, dict],
                        rank_fp: int, sim_fp: float,
                        case_label: str, out_path: Path) -> None:
    """Discord triad の 3 枚画像 + メタ情報パネルを生成する。"""
    t = item['triad']
    A, B, C = t['A'], t['B'], t['C']
    s_AB, s_BC, s_AC = t['s_AB'], t['s_BC'], t['s_AC']

    # 全 3 辺のキーと judg_map レコード
    key_AB = frozenset({A, B})
    key_BC = frozenset({B, C})
    key_AC = frozenset({A, C})
    rec_AB = judg_map.get(key_AB)
    rec_BC = judg_map.get(key_BC)
    rec_AC = judg_map.get(key_AC)

    # 全 3 辺の CM ラベル（rank ≤ rank_fp AND sim ≥ sim_fp → Vector Positive）
    cm_AB = get_cm_label(rec_AB, rank_fp, sim_fp)
    cm_BC = get_cm_label(rec_BC, rank_fp, sim_fp)
    cm_AC = get_cm_label(rec_AC, rank_fp, sim_fp)

    # Discord 辺のキーセット（triad 選出のトリガー）
    discord_key_set = {dr['key'] for dr in item['discord_recs']}
    is_d_AB = key_AB in discord_key_set
    is_d_BC = key_BC in discord_key_set
    is_d_AC = key_AC in discord_key_set

    # パネル枠色: A–B 辺か A–C 辺に Discord があれば色付け
    case_color = '#ff7f00' if case_label == 'FP' else '#33a02c'
    color_A = case_color if (is_d_AB or is_d_AC) else None
    color_B = case_color if (is_d_AB or is_d_BC) else None
    color_C = case_color if (is_d_BC or is_d_AC) else None

    # キャプション: AB:[FP]◀ 0.9912  AC:[TP] 0.9922
    def _edge_str(sim: float, cm: str, is_discord: bool, label: str) -> str:
        mark = '◀' if is_discord else ' '
        return f'{label}:[{cm}]{mark}{sim:.4f}'

    cap_A = f'{_edge_str(s_AB, cm_AB, is_d_AB, "AB")}  {_edge_str(s_AC, cm_AC, is_d_AC, "AC")}'
    cap_B = f'{_edge_str(s_AB, cm_AB, is_d_AB, "AB")}  {_edge_str(s_BC, cm_BC, is_d_BC, "BC")}'
    cap_C = f'{_edge_str(s_BC, cm_BC, is_d_BC, "BC")}  {_edge_str(s_AC, cm_AC, is_d_AC, "AC")}'

    # メタ情報テキスト: 全辺 CM テーブル + Discord 辺の reason
    def _jdg_str(rec: dict | None) -> str:
        return rec['judgment'] if rec else '?'

    meta_lines = [
        f'seq   : {seq}',
        f'triad : rank={t["rank"]}',
        f'S1(min): {t["score_weakest_link"]:.4f}',
        f'S3(ang): {t["score_angular_tightness"]:.4f}',
        f'S2(sch): {t["score_bound_compliance"]:.4f}',
        f'conf  : {t["confidence"]:.4f}',
        '─' * 26,
        'edge  sim    jdg  CM',
        '─' * 26,
        f'AB   {s_AB:.4f}  {_jdg_str(rec_AB):<3}  {cm_AB}{"◀" if is_d_AB else ""}',
        f'BC   {s_BC:.4f}  {_jdg_str(rec_BC):<3}  {cm_BC}{"◀" if is_d_BC else ""}',
        f'AC   {s_AC:.4f}  {_jdg_str(rec_AC):<3}  {cm_AC}{"◀" if is_d_AC else ""}',
        '─' * 26,
    ]
    for dr in item['discord_recs']:
        rec = dr['rec']
        meta_lines.append(f'[{case_label}: {dr["label"]}]')
        meta_lines.append(f'rank={rec["rank"]}  sim={rec["similarity"]:.4f}')
        meta_lines.append(f'LLM: {rec["judgment"]} (conf={rec["confidence"]})')
        for line in textwrap.wrap(rec.get('reason', ''), width=28)[:4]:
            meta_lines.append(line)

    # 描画
    CELL_W, CELL_H = 2.1, 3.4
    fig = plt.figure(figsize=(CELL_W * 4, CELL_H), facecolor='white')
    gs = gridspec.GridSpec(
        1, 4, figure=fig,
        width_ratios=[1, 1, 1, 1.15],
        wspace=0.28, left=0.01, right=0.99, top=0.87, bottom=0.17,
    )
    ax_A    = fig.add_subplot(gs[0, 0])
    ax_B    = fig.add_subplot(gs[0, 1])
    ax_C    = fig.add_subplot(gs[0, 2])
    ax_meta = fig.add_subplot(gs[0, 3])

    _panel(ax_A, img_map.get(A), A, title_map.get(A, ''), cap_A, color_A)
    _panel(ax_B, img_map.get(B), B, title_map.get(B, ''), cap_B, color_B)
    _panel(ax_C, img_map.get(C), C, title_map.get(C, ''), cap_C, color_C)

    ax_meta.axis('off')
    ax_meta.text(
        0.04, 0.97, '\n'.join(meta_lines),
        va='top', ha='left',
        transform=ax_meta.transAxes,
        fontsize=META_FS, family='monospace',
        bbox=dict(boxstyle='round,pad=0.5', fc='#fafafa', ec='#999', alpha=0.95),
    )

    discord_labels = '+'.join(dr['label'] for dr in item['discord_recs'])
    fig.suptitle(
        f'D18 {case_label}  '
        f'(seq={seq},  S1={t["score_weakest_link"]:.4f},  '
        f'S2={t["score_bound_compliance"]:.4f})  '
        f'[edge: {discord_labels}]',
        fontsize=9, y=0.97, color=case_color, fontweight='bold',
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)

# ==============================================================================
# ソート
# ==============================================================================

def _sort_key_fp(item: dict):
    """FP triad のソートキー: S1 降順（幾何的タイトネス最大のものを優先）。"""
    return -item['triad']['score_weakest_link']


def _sort_key_fn(item: dict):
    """FN triad のソートキー: Discord 辺の最大 rank 降順（最も極端な順位ズレを優先）。"""
    max_rank = max(dr['rec']['rank'] for dr in item['discord_recs'])
    return -max_rank

# ==============================================================================
# メイン
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description='閾値分析 + Discord triad 分析')
    parser.add_argument('--class', dest='cls', default='D18')
    parser.add_argument('--rank-fp', type=int,   default=10,   help='FP: rank ≤ this')
    parser.add_argument('--sim-fp',  type=float, default=0.90, help='FP: sim ≥ this')
    parser.add_argument('--rank-fn', type=int,   default=200,  help='FN: rank ≥ this')
    parser.add_argument('--sim-fn',  type=float, default=0.90, help='FN: sim < this')
    parser.add_argument('-N',        type=int,   default=20,   help='# individual images per case')
    args = parser.parse_args()

    scored_jsonl_path = Path(SCORED_JSONL_TMPL.format(CLASS=args.cls))
    all_jsonl_path    = Path(ALL_JSONL_TMPL.format(CLASS=args.cls))
    out_dir           = Path(OUTPUT_TMPL.format(CLASS=args.cls))
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- 全 triad 読み込み ---
    print(f'Loading {scored_jsonl_path} ...')
    triads = load_triadic_scored(scored_jsonl_path)
    print(f'  {len(triads)} triads')

    s1 = np.array([t['score_weakest_link']      for t in triads])
    s2 = np.array([t['score_angular_tightness'] for t in triads])
    s3 = np.array([t['score_bound_compliance']  for t in triads])
    data = {'s1': s1, 's2': s2, 's3': s3}

    # --- [Fig 1–4] 閾値分析 ---
    print('\n[Fig 1] S1–S2 scatter ...')
    plot_scatter_all(data, out_dir)

    print('\n[Fig 2] Parallel coordinates ...')
    plot_parallel_coordinates(data, out_dir)

    print('\n[Fig 3] Threshold survival curves ...')
    plot_threshold_survival(data, out_dir)

    print('\n[Fig 4] S1×S2 threshold grid ...')
    plot_threshold_grid_all(s1, s3, out_dir)

    # --- all.jsonl 読み込み ---
    print(f'\nLoading {all_jsonl_path} ...')
    all_records = load_all_jsonl(all_jsonl_path)
    print(f'  {len(all_records)} records')

    judg_map = build_judgment_map(all_records)
    img_map  = build_image_map(all_records)

    # --- FP/FN 辺の抽出 ---
    fp_keys, fn_keys = find_discord_edge_keys(
        judg_map, args.rank_fp, args.sim_fp, args.rank_fn, args.sim_fn
    )
    print(f'FP edges (rank≤{args.rank_fp}, sim≥{args.sim_fp}, No): {len(fp_keys)}')
    print(f'FN edges (rank≥{args.rank_fn}, sim<{args.sim_fn}, Yes): {len(fn_keys)}')

    fp_items = find_discord_triads(triads, fp_keys, judg_map)
    fn_items = find_discord_triads(triads, fn_keys, judg_map)
    print(f'FP triads: {len(fp_items)}')
    print(f'FN triads: {len(fn_items)}')

    fp_items.sort(key=_sort_key_fp)
    fn_items.sort(key=_sort_key_fn)

    all_ids = {r['source'] for r in all_records} | {r['target'] for r in all_records}
    print(f'Building title map for {len(all_ids)} patents ...')
    title_map = build_title_map(all_ids)

    # --- [Fig 5] FP/FN 散布図 ---
    print('\n[Fig 5] FP/FN scatter ...')
    plot_scatter_discord(triads, fp_items, fn_items, out_dir / 'discord_scatter.png')

    # --- [Fig 6] FP グリッド ---
    print('\n[Fig 6] FP threshold grid ...')
    s1_fp = np.array([item['triad']['score_weakest_link']     for item in fp_items])
    s3_fp = np.array([item['triad']['score_bound_compliance'] for item in fp_items])
    plot_s1s3_grid(s1_fp, s3_fp, out_dir / 'fp_grid.png',
                   title=f'D18 FP triads: $S_1\\times S_2$ grid  (n={len(fp_items)})',
                   cmap_name='Oranges_r')

    # --- [Fig 7] FN グリッド ---
    print('\n[Fig 7] FN threshold grid ...')
    s1_fn = np.array([item['triad']['score_weakest_link']     for item in fn_items])
    s3_fn = np.array([item['triad']['score_bound_compliance'] for item in fn_items])
    plot_s1s3_grid(s1_fn, s3_fn, out_dir / 'fn_grid.png',
                   title=f'D18 FN triads: $S_1\\times S_2$ grid  (n={len(fn_items)})',
                   cmap_name='Greens_r')

    # --- CSV エクスポート ---
    print('\nExporting CSVs ...')
    export_csv(fp_items, title_map, out_dir / 'fp.csv')
    export_csv(fn_items, title_map, out_dir / 'fn.csv')

    # --- 個別三角形画像: FP ---
    n_fp = min(args.N, len(fp_items))
    print(f'\nGenerating {n_fp} FP triad images ...')
    for i, item in enumerate(fp_items[:n_fp], 1):
        t = item['triad']
        out_path = out_dir / f'fp_{i:03d}.png'
        plot_triad_discord(item, seq=i, title_map=title_map,
                           img_map=img_map, judg_map=judg_map,
                           rank_fp=args.rank_fp, sim_fp=args.sim_fp,
                           case_label='FP', out_path=out_path)
        labels = '+'.join(dr['label'] for dr in item['discord_recs'])
        print(f'  → {out_path.name}  '
              f'S1={t["score_weakest_link"]:.4f}  S2={t["score_bound_compliance"]:.4f}  '
              f'edge={labels}')

    # --- 個別三角形画像: FN ---
    n_fn = min(args.N, len(fn_items))
    print(f'\nGenerating {n_fn} FN triad images ...')
    for i, item in enumerate(fn_items[:n_fn], 1):
        t = item['triad']
        out_path = out_dir / f'fn_{i:03d}.png'
        plot_triad_discord(item, seq=i, title_map=title_map,
                           img_map=img_map, judg_map=judg_map,
                           rank_fp=args.rank_fp, sim_fp=args.sim_fp,
                           case_label='FN', out_path=out_path)
        labels = '+'.join(dr['label'] for dr in item['discord_recs'])
        print(f'  → {out_path.name}  '
              f'S1={t["score_weakest_link"]:.4f}  S2={t["score_bound_compliance"]:.4f}  '
              f'edge={labels}')

    print(f'\nDone. Output: {out_dir}/')


if __name__ == '__main__':
    main()