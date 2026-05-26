"""
triad_plotter — 共通 triad 可視化ライブラリ。

各分析スクリプトからインポートして使用する。

    from triad_plotter import load_jsonl, build_image_map, build_judgment_map
    from triad_plotter import plot_triad, run_analysis

公開 API:
  load_jsonl(path)              → list[dict]
  build_image_map(records)      → dict[str, str]
  build_judgment_map(records)   → dict[frozenset, dict]
  plot_triad(triad, seq, img_map, judg_map, out_path, *, suptitle, extra_meta,
             border_colors)
  run_analysis(name, triads, img_map, judg_map, out_base, *, suptitle_fn,
               extra_meta_fn, border_colors_fn)

レイアウト:
  ┌──────┬──────┬──────┬────────┐
  │  A   │  B   │  C   │  Meta  │  ← 画像 + スコア
  ├──────┴──────┴──────┴────────┤
  │ A→B  reason: ...            │  ← 有向グラフ + reason
  │ A→C  reason: ...            │
  │ B↔C  reason: ...            │
  └─────────────────────────────┘

矢印ルール:
  source→target は all.jsonl の方向をそのまま使用。
  「ハブ」(2辺の source) から出る辺 → directed arrow (→)
  三角形を完成させる残り1辺      → bidirectional arrow (↔)
"""

import json
import sys
import textwrap
from pathlib import Path
from typing import Callable

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from scipy.ndimage import binary_dilation

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_processor import ImageProcessor

# ==============================================================================
# スタイル定数
# ==============================================================================

_DILATE_STRUCT = np.ones((3, 3), dtype=bool)

_TITLE_FS   = 9
_CAPTION_FS = 7.5
_META_FS    = 7.5
_REASON_FS  = 7.5

# ==============================================================================
# データ読み込み
# ==============================================================================

def load_jsonl(path: Path) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f]


def build_image_map(records: list[dict]) -> dict[str, str]:
    """source/target → image_path のマップ。"""
    m: dict[str, str] = {}
    for r in records:
        if r.get('source_image'):
            m[r['source']] = r['source_image']
        if r.get('target_image'):
            m[r['target']] = r['target_image']
    return m


def build_judgment_map(records: list[dict]) -> dict[frozenset, dict]:
    """frozenset({source, target}) → edge record のマップ。perspective 優先。"""
    m: dict[frozenset, dict] = {}
    for r in records:
        key = frozenset({r['source'], r['target']})
        if key not in m or r.get('type') == 'perspective':
            m[key] = r
    return m

# ==============================================================================
# 有向エッジ情報の構築
# ==============================================================================

def _build_edge_arrows(
    A: str, B: str, C: str,
    judg_map: dict[frozenset, dict],
) -> list[dict]:
    """3辺の方向ラベル・reason・判定を返す。

    ハブ（2辺の source）の辺は directed (→)、
    三角形を完成させる残り1辺は bidirectional (↔) とする。

    戻り値: [
        {'arrow': 'A→B', 'is_completing': False, 'rec': {...}},
        {'arrow': 'A→C', 'is_completing': False, 'rec': {...}},
        {'arrow': 'B↔C', 'is_completing': True,  'rec': {...}},
    ]
    ハブ辺2本を先に並べ、completing edge を最後にする。
    """
    pairs: list[tuple[frozenset, tuple[str, str]]] = [
        (frozenset({A, B}), (A, B)),
        (frozenset({B, C}), (B, C)),
        (frozenset({A, C}), (A, C)),
    ]

    # ハブ検出: source として 2 回以上現れるノードを探す
    source_count: dict[str, int] = {}
    for key, _ in pairs:
        rec = judg_map.get(key)
        if rec:
            src = rec['source']
            source_count[src] = source_count.get(src, 0) + 1

    hub: str | None = None
    if source_count:
        top = max(source_count, key=source_count.get)
        if source_count[top] >= 2:
            hub = top

    items = []
    for key, (n1, n2) in pairs:
        rec = judg_map.get(key)
        is_completing = bool(hub and (rec is None or rec['source'] != hub))

        if rec:
            src, tgt = rec['source'], rec['target']
            sep = '↔' if is_completing else '→'
            arrow = f'{src}{sep}{tgt}'
        else:
            sep = '↔' if is_completing else '—'
            arrow = f'{n1}{sep}{n2}'

        items.append({'arrow': arrow, 'is_completing': is_completing, 'rec': rec})

    # ハブ辺 → completing の順にソート
    items.sort(key=lambda x: x['is_completing'])
    return items

# ==============================================================================
# 画像読み込み（discord_analysis.py と同一）
# ==============================================================================

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

# ==============================================================================
# 内部: 単一パネル描画（discord_analysis.py の _panel と同一）
# ==============================================================================

def _panel(ax: plt.Axes, img_path: str | None, patent_id: str,
           caption: str, border_color: str | None = None) -> None:
    """特許 1 件分の画像パネル。border_color を指定するとスパイン色付け。"""
    arr = load_image(img_path)
    ax.set_xticks([])
    ax.set_yticks([])
    if arr is not None:
        ax.imshow(arr, aspect='equal', interpolation='nearest',
                  cmap='gray', vmin=0, vmax=255)
    else:
        ax.set_facecolor('#e8e8e8')
        ax.text(0.5, 0.5, 'N/A', ha='center', va='center',
                transform=ax.transAxes, fontsize=_CAPTION_FS)

    ax.set_title(patent_id, fontsize=_TITLE_FS, pad=3, fontweight='bold')
    ax.set_xlabel(caption, fontsize=_CAPTION_FS, labelpad=4)
    lw    = 2.5 if border_color else 0.6
    color = border_color or '#888888'
    for sp in ax.spines.values():
        sp.set_linewidth(lw)
        sp.set_color(color)

# ==============================================================================
# 内部: reason パネル描画
# ==============================================================================

_REASON_WRAP = 100   # 1行あたりの最大文字数

def _reason_panel(ax: plt.Axes, edge_arrows: list[dict]) -> None:
    """有向グラフ矢印 + reason を 1 パネルに表示する。

    フォーマット:
      A→B  [Yes]  sim=X.XXXX  rank=N
        reason: Lorem ipsum...

      A→C  [Yes]  sim=X.XXXX  rank=N
        ...
    """
    ax.axis('off')

    lines: list[tuple[str, dict]] = []  # (text, style_kwargs)
    for item in edge_arrows:
        rec = item['rec']
        arrow = item['arrow']
        tag = '  ← completing' if item['is_completing'] else ''

        if rec:
            jdg  = rec.get('judgment', '?')
            sim  = rec.get('similarity', float('nan'))
            rank = rec.get('rank', '?')
            conf = rec.get('confidence', '?')
            header = (f'{arrow}  [{jdg}]  sim={sim:.4f}  '
                      f'rank={rank}  conf={conf}{tag}')
        else:
            header = f'{arrow}  [?]{tag}'

        lines.append((header, {'fontweight': 'bold', 'color': '#111111'}))

        reason_text = rec.get('reason', '') if rec else ''
        if reason_text:
            for wrapped_line in textwrap.wrap(reason_text, width=_REASON_WRAP):
                lines.append(('  ' + wrapped_line, {'fontweight': 'normal', 'color': '#333333'}))
        else:
            lines.append(('  (no reason)', {'fontweight': 'normal', 'color': '#888888'}))

        lines.append(('', {}))  # 空行でエントリを区切る

    # テキストを上から詰めて表示
    y = 0.97
    line_h = 1.0 / max(len(lines) + 1, 1)
    for text, style in lines:
        ax.text(
            0.01, y, text,
            va='top', ha='left',
            transform=ax.transAxes,
            fontsize=_REASON_FS, family='monospace',
            **style,
        )
        y -= line_h

# ==============================================================================
# 公開: 単一 triad 画像描画
# ==============================================================================

def plot_triad(
    triad: dict,
    seq: int,
    img_map: dict[str, str],
    judg_map: dict[frozenset, dict],
    out_path: Path,
    *,
    suptitle: str = '',
    extra_meta: list[str] | None = None,
    border_colors: tuple[str | None, str | None, str | None] = (None, None, None),
) -> None:
    """triad を画像パネル + メタ情報 + 有向グラフ reason 付きで保存する。

    レイアウト:
      上段: [Image A] [Image B] [Image C] [Meta]
      下段: [A→B / A→C / B↔C の矢印 + reason テキスト (全幅)]

    Args:
        extra_meta: メタパネルに追加するテキスト行。
        border_colors: (A, B, C) 各パネルのスパイン色。None = デフォルト灰色。
    """
    A, B, C = triad['A'], triad['B'], triad['C']
    s_AB = triad['s_AB']
    s_BC = triad['s_BC']
    s_AC = triad['s_AC']

    key_AB = frozenset({A, B})
    key_BC = frozenset({B, C})
    key_AC = frozenset({A, C})

    def _jdg(key: frozenset) -> str:
        r = judg_map.get(key)
        return r['judgment'] if r else '?'

    jdg_AB = _jdg(key_AB)
    jdg_BC = _jdg(key_BC)
    jdg_AC = _jdg(key_AC)

    def _cap(sim: float, jdg: str, label: str) -> str:
        return f'{label}: {sim:.4f} [{jdg}]'

    cap_A = f'{_cap(s_AB, jdg_AB, "AB")}  {_cap(s_AC, jdg_AC, "AC")}'
    cap_B = f'{_cap(s_AB, jdg_AB, "AB")}  {_cap(s_BC, jdg_BC, "BC")}'
    cap_C = f'{_cap(s_BC, jdg_BC, "BC")}  {_cap(s_AC, jdg_AC, "AC")}'

    # --- メタ情報 ---
    meta_lines: list[str] = [
        f'seq   : {seq}',
        f'rank  : {triad.get("rank", "?")}',
        '─' * 26,
    ]
    for key, label in [
        ('score_weakest_link',      'S1(wl)'),
        ('score_wcc',               'S2(cc)'),
        ('score_angular_tightness', 'S3(at)'),
        ('score_snn',               'S4(snn)'),
        ('confidence',              'conf  '),
    ]:
        if key in triad:
            meta_lines.append(f'{label}: {triad[key]:.4f}')

    meta_lines += [
        '─' * 26,
        'edge  sim    jdg',
        '─' * 26,
        f'AB   {s_AB:.4f}  {jdg_AB}',
        f'BC   {s_BC:.4f}  {jdg_BC}',
        f'AC   {s_AC:.4f}  {jdg_AC}',
    ]
    if extra_meta:
        meta_lines += ['─' * 26] + extra_meta

    # --- 有向エッジ情報 ---
    edge_arrows = _build_edge_arrows(A, B, C, judg_map)

    # --- レイアウト ---
    CELL_W  = 2.1
    CELL_H  = 3.4
    REASON_H = 2.2   # 下段 reason パネルの高さ

    fig = plt.figure(figsize=(CELL_W * 4, CELL_H + REASON_H), facecolor='white')
    gs = gridspec.GridSpec(
        2, 4, figure=fig,
        height_ratios=[CELL_H, REASON_H],
        width_ratios=[1, 1, 1, 1.15],
        hspace=0.05,
        wspace=0.28,
        left=0.01, right=0.99,
        top=0.93, bottom=0.02,
    )

    ax_A      = fig.add_subplot(gs[0, 0])
    ax_B      = fig.add_subplot(gs[0, 1])
    ax_C      = fig.add_subplot(gs[0, 2])
    ax_meta   = fig.add_subplot(gs[0, 3])
    ax_reason = fig.add_subplot(gs[1, :])   # 下段全幅

    _panel(ax_A, img_map.get(A), A, cap_A, border_colors[0])
    _panel(ax_B, img_map.get(B), B, cap_B, border_colors[1])
    _panel(ax_C, img_map.get(C), C, cap_C, border_colors[2])

    ax_meta.axis('off')
    ax_meta.text(
        0.04, 0.97, '\n'.join(meta_lines),
        va='top', ha='left',
        transform=ax_meta.transAxes,
        fontsize=_META_FS, family='monospace',
        bbox=dict(boxstyle='round,pad=0.5', fc='#fafafa', ec='#999', alpha=0.95),
    )

    _reason_panel(ax_reason, edge_arrows)

    # reason パネルに薄い枠
    for sp in ax_reason.spines.values():
        sp.set_linewidth(0.4)
        sp.set_color('#cccccc')

    if suptitle:
        fig.suptitle(suptitle, fontsize=9, y=0.99)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)

# ==============================================================================
# 公開: 分析ランナー
# ==============================================================================

def run_analysis(
    name: str,
    triads: list[dict],
    img_map: dict[str, str],
    judg_map: dict[frozenset, dict],
    out_base: Path,
    *,
    suptitle_fn: Callable[[dict, int], str] | None = None,
    extra_meta_fn: Callable[[dict, int], list[str]] | None = None,
    border_colors_fn: Callable[[dict, int], tuple] | None = None,
) -> Path:
    """triads を out_base/name/triad_{i:03d}.png として一括出力する。

    Args:
        name: サブディレクトリ名（分析の識別子）。
        suptitle_fn: (triad, seq) → タイトル文字列。
        extra_meta_fn: (triad, seq) → 追加メタ行リスト。
        border_colors_fn: (triad, seq) → (color_A, color_B, color_C)。

    Returns:
        出力ディレクトリのパス。
    """
    out_dir = out_base / name
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f'[{name}] {len(triads)} triads → {out_dir}/')

    for seq, triad in enumerate(triads, 1):
        plot_triad(
            triad, seq, img_map, judg_map,
            out_dir / f'triad_{seq:03d}.png',
            suptitle=suptitle_fn(triad, seq) if suptitle_fn else '',
            extra_meta=extra_meta_fn(triad, seq) if extra_meta_fn else None,
            border_colors=border_colors_fn(triad, seq) if border_colors_fn else (None, None, None),
        )
        print(f'  → triad_{seq:03d}.png  '
              f'({triad["A"]}, {triad["B"]}, {triad["C"]})')

    print(f'[{name}] Done.')
    return out_dir
