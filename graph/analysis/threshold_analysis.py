"""
triadic スコア（S1, S2, S3）の閾値設計支援可視化。

全 1593 三角形の triadic_scored.jsonl を読み込み、以下の図を生成する。

  Fig 1: 2D 散布図（3 組み合わせ）
    scatter_s1_s3_s2.png  — x=S1, y=S3, color=S2
    scatter_s1_s2_s3.png  — x=S1, y=S2, color=S3
    scatter_s2_s3_s1.png  — x=S2, y=S3, color=S1

  Fig 2: 平行座標プロット
    parallel_coordinates.png  — S1 / S2 / S3 / confidence 軸

  Fig 3: 閾値 vs 残存 triad 数（生存曲線）
    threshold_survival.png  — 各スコアと複合条件（S1 & S3）のカウント

  Fig 4: S1 × S3 閾値グリッドのヒートマップ
    threshold_grid.png
    threshold_grid.csv

実行:
  cd /home/sonozuka/design_similarity
  python graph/analysis/threshold_analysis.py
"""

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.cm as cm
import numpy as np

# ==============================================================================
# パス
# ==============================================================================

SCORED_JSONL = Path('graph/output/D18/triadic_scored.jsonl')
OUTPUT_DIR   = Path('graph/output/D18/analysis')

# ==============================================================================
# データ読み込み
# ==============================================================================

def load_scored(path: Path) -> dict[str, np.ndarray]:
    rows = []
    with open(path) as f:
        for line in f:
            rows.append(json.loads(line))
    return {
        's1': np.array([r['score_weakest_link']       for r in rows]),
        's2': np.array([r['score_angular_tightness']  for r in rows]),
        's3': np.array([r['score_bound_compliance']   for r in rows]),
        's4': np.array([r['score_snn']                for r in rows]),
        'conf': np.array([r['confidence']             for r in rows]),
    }

# ==============================================================================
# 共通スタイル
# ==============================================================================

SPINE_LW = 0.6
TICK_FS  = 7
LABEL_FS = 8
TITLE_FS = 9

def _style_ax(ax):
    ax.tick_params(labelsize=TICK_FS, width=0.5, length=3)
    for sp in ax.spines.values():
        sp.set_linewidth(SPINE_LW)

# ==============================================================================
# Fig 1: 2D 散布図
# ==============================================================================

_SCATTER_CONFIGS = [
    ('s1', 's3', 's2', 'S1 (weakest-link)', 'S3 (Schubert compliance)', 'S2 (angular tightness)'),
    ('s1', 's2', 's3', 'S1 (weakest-link)', 'S2 (angular tightness)',   'S3 (Schubert compliance)'),
    ('s2', 's3', 's1', 'S2 (angular tightness)', 'S3 (Schubert compliance)', 'S1 (weakest-link)'),
]

# 参考閾値候補（縦横線として描画）
_TH_S1 = [0.85, 0.90, 0.95]
_TH_S2 = [0.70, 0.80, 0.85]
_TH_S3 = [0.70, 0.80, 0.90]

_TH_MAP = {'s1': _TH_S1, 's2': _TH_S2, 's3': _TH_S3}


def plot_scatter(data: dict, out_dir: Path) -> None:
    cmap = cm.plasma

    for xk, yk, ck, xlabel, ylabel, clabel in _SCATTER_CONFIGS:
        fig, ax = plt.subplots(figsize=(4.0, 3.4), facecolor='white')

        sc = ax.scatter(
            data[xk], data[yk],
            c=data[ck], cmap=cmap,
            s=4, alpha=0.55, linewidths=0,
            rasterized=True,
        )
        cb = fig.colorbar(sc, ax=ax, pad=0.02)
        cb.set_label(clabel, fontsize=LABEL_FS)
        cb.ax.tick_params(labelsize=TICK_FS)

        # 閾値線（破線）
        for th in _TH_MAP[xk]:
            ax.axvline(th, color='#333333', lw=0.7, ls='--', alpha=0.5)
            ax.text(th + 0.003, ax.get_ylim()[0] + 0.01, f'{th}',
                    fontsize=6, color='#333333', va='bottom')
        for th in _TH_MAP[yk]:
            ax.axhline(th, color='#1f77b4', lw=0.7, ls='--', alpha=0.5)
            ax.text(ax.get_xlim()[0] + 0.003, th + 0.005, f'{th}',
                    fontsize=6, color='#1f77b4', va='bottom')

        ax.set_xlabel(xlabel, fontsize=LABEL_FS)
        ax.set_ylabel(ylabel, fontsize=LABEL_FS)
        ax.set_title(
            f'D18 triads  (n={len(data[xk])})\n'
            f'x={xk.upper()}, y={yk.upper()}, color={ck.upper()}',
            fontsize=TITLE_FS,
        )
        _style_ax(ax)

        fig.tight_layout()
        out = out_dir / f'scatter_{xk}_{yk}_{ck}.png'
        fig.savefig(out, dpi=200, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        print(f'  {out.name}')

# ==============================================================================
# Fig 2: 平行座標プロット
# ==============================================================================

def plot_parallel_coordinates(data: dict, out_dir: Path,
                              top_n: int = 50) -> None:
    """S1, S2, S3, confidence の 4 軸平行座標プロット。

    全 triad を薄いグレーで描き、confidence 上位 top_n を
    plasma カラーマップで重ね描きする。
    """
    axes_keys   = ['s1', 's2', 's3', 'conf']
    axes_labels = ['S1\n(weakest-link)', 'S2\n(angular tightness)',
                   'S3\n(Schubert compliance)', 'Confidence']
    n_axes = len(axes_keys)
    n_triads = len(data['s1'])

    # 各軸の値を [0, 1] に正規化（実際にはすでに 0-1 だが min/max で統一）
    vals = np.stack([data[k] for k in axes_keys], axis=1)  # (N, 4)
    vmin = vals.min(axis=0)
    vmax = vals.max(axis=0)
    norm_vals = (vals - vmin) / np.where(vmax - vmin > 0, vmax - vmin, 1)

    # confidence 上位 top_n のインデックス（data は confidence 降順）
    top_idx = np.arange(min(top_n, n_triads))
    other_idx = np.arange(min(top_n, n_triads), n_triads)

    conf_norm_for_color = mcolors.Normalize(
        vmin=data['conf'][top_idx[-1]], vmax=data['conf'][top_idx[0]]
    )
    cmap = cm.plasma

    fig, ax = plt.subplots(figsize=(5.5, 3.8), facecolor='white')
    ax.set_xlim(-0.05, n_axes - 0.95)
    ax.set_ylim(-0.05, 1.05)

    x_pos = np.arange(n_axes, dtype=float)

    # 全 triad（グレー、薄く）
    for i in other_idx:
        ax.plot(x_pos, norm_vals[i], color='#cccccc', lw=0.3, alpha=0.4,
                rasterized=True)

    # 上位 top_n（plasma 色、太め）
    for i in reversed(top_idx):  # 上位ほど上に描く
        color = cmap(conf_norm_for_color(data['conf'][i]))
        ax.plot(x_pos, norm_vals[i], color=color, lw=0.9, alpha=0.85,
                rasterized=True)

    # 軸線と目盛り
    for j, (label, vn, vx) in enumerate(zip(axes_labels, vmin, vmax)):
        ax.axvline(j, color='#444444', lw=0.8)
        for tick in np.linspace(0, 1, 5):
            raw = vn + tick * (vx - vn)
            ax.text(j - 0.04, tick, f'{raw:.2f}',
                    ha='right', va='center', fontsize=5.5)
        ax.text(j, 1.07, label, ha='center', va='bottom',
                fontsize=LABEL_FS, fontweight='bold')

    # カラーバー（右側）
    sm = cm.ScalarMappable(cmap=cmap, norm=conf_norm_for_color)
    sm.set_array([])
    cb = fig.colorbar(sm, ax=ax, pad=0.02, shrink=0.8)
    cb.set_label(f'Confidence\n(top-{top_n} colored)', fontsize=LABEL_FS)
    cb.ax.tick_params(labelsize=TICK_FS)

    ax.set_xticks([])
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(
        f'D18 parallel coordinates  (n={n_triads},  top-{top_n} highlighted)',
        fontsize=TITLE_FS,
    )

    fig.tight_layout()
    out = out_dir / 'parallel_coordinates.png'
    fig.savefig(out, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out.name}')

# ==============================================================================
# Fig 3: 閾値 vs 残存 triad 数（生存曲線）
# ==============================================================================

def plot_threshold_survival(data: dict, out_dir: Path) -> None:
    """各スコア単独＋S1&S3 複合条件の生存曲線を 4 パネルで描画する。"""
    thresholds = np.linspace(0.0, 1.0, 201)
    s1, s2, s3 = data['s1'], data['s2'], data['s3']
    n = len(s1)

    count_s1    = np.array([(s1 >= t).sum() for t in thresholds])
    count_s2    = np.array([(s2 >= t).sum() for t in thresholds])
    count_s3    = np.array([(s3 >= t).sum() for t in thresholds])

    # 複合条件: S1 ≥ T と S3 ≥ T を同時に変化させる
    count_s1s3  = np.array([((s1 >= t) & (s3 >= t)).sum() for t in thresholds])

    configs = [
        (count_s1,   'S1 (weakest-link)',          '#4477aa'),
        (count_s2,   'S2 (angular tightness)',      '#228833'),
        (count_s3,   'S3 (Schubert compliance)',    '#ee6677'),
        (count_s1s3, 'S1 & S3 (both ≥ threshold)', '#ccbb44'),
    ]

    fig, axes = plt.subplots(1, 4, figsize=(11, 3.0),
                             sharey=False, facecolor='white')

    for ax, (counts, label, color) in zip(axes, configs):
        ax.plot(thresholds, counts, color=color, lw=1.4)
        ax.fill_between(thresholds, counts, alpha=0.15, color=color)

        # 参考閾値の縦線と件数注記
        ref_ths = [0.80, 0.85, 0.90, 0.95]
        for th in ref_ths:
            idx = np.searchsorted(thresholds, th)
            cnt = int(counts[min(idx, len(counts)-1)])
            ax.axvline(th, color='#888888', lw=0.6, ls='--', alpha=0.7)
            ax.text(th, cnt + n * 0.02, f'{cnt}',
                    ha='center', va='bottom', fontsize=5.5, color='#444444')

        ax.set_xlabel('Threshold T', fontsize=LABEL_FS)
        ax.set_ylabel('# triads ≥ T', fontsize=LABEL_FS)
        ax.set_title(label, fontsize=TITLE_FS - 1)
        ax.set_xlim(0.4, 1.0)
        ax.set_ylim(0, n * 1.08)
        _style_ax(ax)

    fig.suptitle(
        f'D18 — threshold survival curves  (total n={n})',
        fontsize=TITLE_FS + 1, y=1.02,
    )
    fig.tight_layout()
    out = out_dir / 'threshold_survival.png'
    fig.savefig(out, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out.name}')

# ==============================================================================
# Fig 4: S1 × S3 閾値グリッド（ヒートマップ）
# ==============================================================================

_GRID_THS = np.round(np.arange(0.75, 1.001, 0.05), 2)


def plot_threshold_grid(data: dict, out_dir: Path) -> None:
    """S1_th × S3_th の格子点で「両方 ≥ 閾値の triad 数」をヒートマップ描画。"""
    s1, s3 = data['s1'], data['s3']
    ths = _GRID_THS
    grid = np.zeros((len(ths), len(ths)), dtype=int)

    for i, t1 in enumerate(ths):
        for j, t3 in enumerate(ths):
            grid[i, j] = int(((s1 >= t1) & (s3 >= t3)).sum())

    # PNG
    fig, ax = plt.subplots(figsize=(4.5, 3.8), facecolor='white')
    im = ax.imshow(grid, origin='upper', aspect='auto',
                   cmap='YlOrRd_r', vmin=0, vmax=grid.max())

    ax.set_xticks(range(len(ths)))
    ax.set_xticklabels([f'{t:.2f}' for t in ths], fontsize=TICK_FS, rotation=45)
    ax.set_yticks(range(len(ths)))
    ax.set_yticklabels([f'{t:.2f}' for t in ths], fontsize=TICK_FS)
    ax.set_xlabel('S3 threshold', fontsize=LABEL_FS)
    ax.set_ylabel('S1 threshold', fontsize=LABEL_FS)
    ax.set_title(
        'D18 — # triads with S1 ≥ T1 and S3 ≥ T3',
        fontsize=TITLE_FS,
    )

    # セル内の数値
    for i in range(len(ths)):
        for j in range(len(ths)):
            val = grid[i, j]
            txt_color = 'white' if val < grid.max() * 0.5 else '#222222'
            ax.text(j, i, str(val), ha='center', va='center',
                    fontsize=6, color=txt_color)

    cb = fig.colorbar(im, ax=ax, pad=0.02)
    cb.set_label('# triads', fontsize=LABEL_FS)
    cb.ax.tick_params(labelsize=TICK_FS)

    _style_ax(ax)
    fig.tight_layout()
    out_png = out_dir / 'threshold_grid.png'
    fig.savefig(out_png, dpi=200, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'  {out_png.name}')

    # CSV
    out_csv = out_dir / 'threshold_grid.csv'
    with open(out_csv, 'w', newline='') as f:
        writer = csv.writer(f)
        header = ['s1_th \\ s3_th'] + [f'{t:.2f}' for t in ths]
        writer.writerow(header)
        for i, t1 in enumerate(ths):
            writer.writerow([f'{t1:.2f}'] + list(grid[i]))
    print(f'  {out_csv.name}')

# ==============================================================================
# メイン
# ==============================================================================

def main() -> None:
    print(f'Loading {SCORED_JSONL} ...')
    data = load_scored(SCORED_JSONL)
    n = len(data['s1'])
    print(f'  Loaded {n} triads')

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print('\n[Fig 1] 2D scatter plots ...')
    plot_scatter(data, OUTPUT_DIR)

    print('\n[Fig 2] Parallel coordinates ...')
    plot_parallel_coordinates(data, OUTPUT_DIR, top_n=50)

    print('\n[Fig 3] Threshold survival curves ...')
    plot_threshold_survival(data, OUTPUT_DIR)

    print('\n[Fig 4] S1×S3 threshold grid ...')
    plot_threshold_grid(data, OUTPUT_DIR)

    print(f'\nDone. Output → {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
