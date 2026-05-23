"""
高信頼 triadic ペアの画像確認図を生成する。

全 3-clique を confidence 降順にソートし、上位 N 個を抽出して
各 triad の 3 枚の特許画像を横並びに描画する。

フィルタ（デフォルト）:
  --min-s1 0.90  : 三辺すべてが cosine sim ≥ 0.90 (weakest-link)
  --min-s3 0.70  : Schubert 境界適合度 ≥ 0.70
  -N       30    : フィルタ後の上位 N 件

出力:
  graph/output/D18/high_sim_triads/
    overview.png          — 全 N 件を縦に並べた概観図
    triad_001.png         — rank-1 の個別図（3枚横並び）
    triad_002.png         — rank-2 の個別図
    ...

実行:
  cd /home/sonozuka/design_similarity
  python graph/extract_high_sim_triads.py
  python graph/extract_high_sim_triads.py --min-s1 0.95 -N 20
  python graph/extract_high_sim_triads.py --no-filter -N 50
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy.ndimage import binary_dilation, binary_closing, gaussian_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from image_processor import ImageProcessor

# ==============================================================================
# パス
# ==============================================================================

SCORED_JSONL = Path('/home/sonozuka/design_similarity/graph/output/D18/triadic_scored.jsonl')
ALL_JSONL    = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
DATA_CSV_GLOB = '/mnt/eightthdd/uspto/data/*.csv'
OUTPUT_DIR   = Path('/home/sonozuka/design_similarity/graph/output/D18/high_sim_triads')


# ==============================================================================
# データ読み込み
# ==============================================================================

def load_scored(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def build_image_map(path: Path) -> dict[str, str]:
    """patent_id -> image_path のマップを構築する。"""
    m: dict[str, str] = {}
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            m[r['source']] = r['source_image']
            m[r['target']] = r['target_image']
    return m


def build_title_map(patent_ids: set[str]) -> dict[str, str]:
    """data/{year}.csv から patent_id -> title のマップを構築する。"""
    title_map: dict[str, str] = {}
    for csv_path in sorted(glob.glob(DATA_CSV_GLOB)):
        df = pd.read_csv(csv_path, usecols=['id', 'title'])
        df['id'] = df['id'].astype(str)
        matches = df[df['id'].isin(patent_ids)]
        for _, row in matches.iterrows():
            title_map[row['id']] = str(row['title'])
        if len(title_map) == len(patent_ids):
            break
    return title_map


# ==============================================================================
# 画像読み込み・線強調
# ==============================================================================

# structuring element: 3×3 正方形（膨張用）
_DILATE_STRUCT = np.ones((3, 3), dtype=bool)


def _enhance_lines(arr_l: np.ndarray, method: str) -> np.ndarray:
    """
    グレースケール配列（paper≈255, lines≈0）を受け取り、線を強調した
    2値配列（lines=0 black, background=255 white）を返す。

    method:
        'dilation'  — 膨張（3×3, 1回）で線を1px太くする
        'closing'   — Closing（膨張→侵食）で線の切れ目を補完しつつ太くする
        'gaussian'  — ガウスぼかし後に再2値化（アンチエイリアス的に滑らかにする）
        'none'      — 2値化のみ
    """
    # 線マスク: lines=True, background=False
    line_mask = arr_l < 128

    if method == 'dilation':
        line_mask = binary_dilation(line_mask, structure=_DILATE_STRUCT, iterations=1)
    elif method == 'closing':
        # closing = dilation → erosion: 線の隙間を埋め、ノイズも除去
        line_mask = binary_closing(line_mask, structure=_DILATE_STRUCT, iterations=1)
    elif method == 'gaussian':
        # ガウスぼかし（sigma=0.8）→ 再2値化: 細線を均す
        blurred = gaussian_filter(arr_l.astype(float), sigma=0.8)
        line_mask = blurred < 128

    # 表示用: lines=0(black), background=255(white)
    return np.where(line_mask, 0, 255).astype(np.uint8)


# グローバル設定（main() で上書き）
_LINE_ENHANCE = 'dilation'


def load_image(path: str | None) -> np.ndarray | None:
    if not path:
        return None
    try:
        img = ImageProcessor.process_file(path).convert('L')
        arr = np.array(img)
        return _enhance_lines(arr, _LINE_ENHANCE)
    except Exception as e:
        print(f'  [warn] {path}: {e}', file=sys.stderr)
        return None


# ==============================================================================
# 個別 triad 図（3 枚横並び）
# ==============================================================================

TITLE_FS   = 9
CAPTION_FS = 8
META_FS    = 8


def _panel(ax, img_path: str | None, patent_id: str, patent_title: str, caption: str) -> None:
    arr = load_image(img_path)
    ax.set_xticks([])
    ax.set_yticks([])
    if arr is not None:
        # cmap='gray': 0=黒(lines), 255=白(background)
        ax.imshow(arr, aspect='equal', interpolation='nearest',
                  cmap='gray', vmin=0, vmax=255)
    else:
        ax.set_facecolor('#e8e8e8')
        ax.text(0.5, 0.5, 'N/A', ha='center', va='center',
                transform=ax.transAxes, fontsize=CAPTION_FS)
    ax.set_title(patent_id, fontsize=TITLE_FS, pad=3, fontweight='bold')
    # title は改行して読みやすくする（長い場合は折り返し）
    ax.set_xlabel(f'{patent_title}\n{caption}', fontsize=CAPTION_FS, labelpad=4)
    for sp in ax.spines.values():
        sp.set_linewidth(0.6)


def plot_triad(triad: dict, img_map: dict[str, str], title_map: dict[str, str],
               out_path: Path) -> None:
    """1 triad = 3 枚横並び + メタ情報パネルの図を生成する。"""
    A, B, C = triad['A'], triad['B'], triad['C']
    s_AB, s_BC, s_AC = triad['s_AB'], triad['s_BC'], triad['s_AC']

    CELL_W, CELL_H = 2.0, 3.2
    fig = plt.figure(figsize=(CELL_W * 4, CELL_H), facecolor='white')
    gs = gridspec.GridSpec(
        1, 4, figure=fig,
        wspace=0.25, left=0.01, right=0.99, top=0.88, bottom=0.18,
    )

    ax_A    = fig.add_subplot(gs[0, 0])
    ax_B    = fig.add_subplot(gs[0, 1])
    ax_C    = fig.add_subplot(gs[0, 2])
    ax_meta = fig.add_subplot(gs[0, 3])

    _panel(ax_A, img_map.get(A), A, title_map.get(A, ''),
           f'$s_{{AB}}$={s_AB:.4f}  $s_{{AC}}$={s_AC:.4f}')

    _panel(ax_B, img_map.get(B), B, title_map.get(B, ''),
           f'$s_{{AB}}$={s_AB:.4f}  $s_{{BC}}$={s_BC:.4f}')

    _panel(ax_C, img_map.get(C), C, title_map.get(C, ''),
           f'$s_{{BC}}$={s_BC:.4f}  $s_{{AC}}$={s_AC:.4f}')

    ax_meta.axis('off')
    meta = (
        f"rank    : {triad['rank']}\n"
        f"conf    : {triad['confidence']:.4f}\n"
        f"─────────────\n"
        f"S1 (min): {triad['score_weakest_link']:.4f}\n"
        f"S2 (ang): {triad['score_angular_tightness']:.4f}\n"
        f"S3 (sch): {triad['score_bound_compliance']:.4f}\n"
        f"S4 (snn): {triad['score_snn']:.4f}\n"
        f"─────────────\n"
        f"s_AB    : {s_AB:.4f}\n"
        f"s_BC    : {s_BC:.4f}\n"
        f"s_AC    : {s_AC:.4f}"
    )
    ax_meta.text(0.05, 0.95, meta, va='top', ha='left',
                 transform=ax_meta.transAxes,
                 fontsize=META_FS, family='monospace',
                 bbox=dict(boxstyle='round,pad=0.5',
                           fc='white', ec='#999', alpha=0.9))

    fig.suptitle(
        f'D18 High-confidence triad  (rank={triad["rank"]},  '
        f'conf={triad["confidence"]:.4f})',
        fontsize=10, y=0.97,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)


# ==============================================================================
# 概観図（全 N 件を縦方向に並べた 1 枚の図）
# ==============================================================================

def plot_overview(triads: list[dict], img_map: dict[str, str],
                  title_map: dict[str, str], out_path: Path) -> None:
    """全 N 件の triad を縦に並べた概観図を生成する。"""
    N = len(triads)
    CELL_W, CELL_H = 1.8, 3.0
    N_COLS = 3   # A, B, C

    fig = plt.figure(figsize=(CELL_W * N_COLS, CELL_H * N), facecolor='white')
    gs = gridspec.GridSpec(
        N, N_COLS, figure=fig,
        hspace=0.85, wspace=0.15,
        left=0.01, right=0.99, top=0.98, bottom=0.01,
    )

    for row, triad in enumerate(triads):
        A, B, C = triad['A'], triad['B'], triad['C']
        s_AB, s_BC, s_AC = triad['s_AB'], triad['s_BC'], triad['s_AC']
        conf = triad['confidence']
        rank = triad['rank']

        for col, (pid, cap) in enumerate([
            (A, f'$s_{{AB}}$={s_AB:.3f}  $s_{{AC}}$={s_AC:.3f}'),
            (B, f'$s_{{AB}}$={s_AB:.3f}  $s_{{BC}}$={s_BC:.3f}'),
            (C, f'$s_{{BC}}$={s_BC:.3f}  $s_{{AC}}$={s_AC:.3f}'),
        ]):
            ax = fig.add_subplot(gs[row, col])
            arr = load_image(img_map.get(pid))
            ax.set_xticks([]); ax.set_yticks([])
            if arr is not None:
                ax.imshow(arr, aspect='equal', interpolation='nearest',
                          cmap='gray', vmin=0, vmax=255)
            else:
                ax.set_facecolor('#e8e8e8')
                ax.text(0.5, 0.5, 'N/A', ha='center', va='center',
                        transform=ax.transAxes, fontsize=6)
            label = 'ABC'[col]
            pat_title = title_map.get(pid, '')
            ax.set_title(f'[rank {rank}]  {label}: {pid}',
                         fontsize=6.5, pad=2, fontweight='bold')
            ax.set_xlabel(f'{pat_title}\n{cap}  conf={conf:.4f}',
                          fontsize=5.5, labelpad=2)
            for sp in ax.spines.values():
                sp.set_linewidth(0.4)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'Overview figure ({N} triads) → {out_path}')


# ==============================================================================
# メイン
# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-N', type=int, default=30,
                        help='抽出する上位件数（デフォルト: 30）')
    parser.add_argument('--min-s1', type=float, default=0.90,
                        help='weakest-link sim の下限（デフォルト: 0.90）')
    parser.add_argument('--min-s3', type=float, default=0.70,
                        help='Schubert compliance の下限（デフォルト: 0.70）')
    parser.add_argument('--no-filter', action='store_true',
                        help='フィルタなしで confidence 上位 N 件を取る')
    parser.add_argument('--no-individual', action='store_true',
                        help='個別図を生成しない（overview のみ）')
    parser.add_argument('--bottom', action='store_true',
                        help='confidence 最下位 N 件を抽出する（フィルタ無効）')
    parser.add_argument(
        '--line-enhance',
        default='dilation',
        choices=['dilation', 'closing', 'gaussian', 'none'],
        help=(
            '線強調手法（デフォルト: dilation）\n'
            '  dilation : 膨張 3×3×1回（線を1px太くする）\n'
            '  closing  : Closing（膨張→侵食、隙間補完）\n'
            '  gaussian : ガウスぼかし後2値化（滑らかな細線）\n'
            '  none     : 2値化のみ'
        ),
    )
    args = parser.parse_args()

    global _LINE_ENHANCE
    _LINE_ENHANCE = args.line_enhance
    print(f'Line enhancement: {_LINE_ENHANCE}')

    print(f'Loading {SCORED_JSONL} ...')
    scored = load_scored(SCORED_JSONL)
    print(f'  Total triads: {len(scored)}')

    print(f'Loading image map from {ALL_JSONL} ...')
    img_map = build_image_map(ALL_JSONL)
    print(f'  Patent count: {len(img_map)}')

    print(f'Loading title map from {DATA_CSV_GLOB} ...')
    title_map = build_title_map(set(img_map.keys()))
    print(f'  Titles found: {len(title_map)} / {len(img_map)}')

    # 抽出
    if args.bottom:
        # 最下位 N 件（confidence 昇順で先頭 N 件）
        top = list(reversed(scored))[:args.N]
        print(f'  Bottom-{args.N}: confidence {top[-1]["confidence"]:.4f} 〜 {top[0]["confidence"]:.4f}')
    else:
        if args.no_filter:
            filtered = scored
            print(f'  Filter: none')
        else:
            filtered = [r for r in scored
                        if r['score_weakest_link']    >= args.min_s1
                        and r['score_bound_compliance'] >= args.min_s3]
            print(f'  Filter: S1 ≥ {args.min_s1}, S3 ≥ {args.min_s3}'
                  f'  → {len(filtered)} triads')
        top = filtered[:args.N]
        print(f'  Top-{args.N}: {len(top)} triads selected')

    if not top:
        print('対象 triad がありません。フィルタ条件を緩めてください。')
        return

    prefix = 'bottom' if args.bottom else 'triad'
    overview_name = 'overview_bottom.png' if args.bottom else 'overview.png'

    # 個別図
    if not args.no_individual:
        print(f'\nGenerating individual figures ...')
        for i, triad in enumerate(top, 1):
            out = OUTPUT_DIR / f'{prefix}_{i:03d}.png'
            plot_triad(triad, img_map, title_map, out)
            print(f'  [{i:3d}/{len(top)}] rank={triad["rank"]}  conf={triad["confidence"]:.4f}  → {out.name}')

    # 概観図
    print(f'\nGenerating overview figure ...')
    plot_overview(top, img_map, title_map, OUTPUT_DIR / overview_name)

    print(f'\nDone. Output → {OUTPUT_DIR}')


if __name__ == '__main__':
    main()
