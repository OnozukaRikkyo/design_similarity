"""
T1 × T2 閾値フィルタ triad の可視化。

フィルタ条件:
  S1 (weakest-link)  >= T1_THRESH
  S_WCC              >= T2_THRESH

出力:
  graph/output/D18/visualize/wcc_s1_{T1}_wcc_{T2}/triad_{i:03d}.png
  --no-consec 指定時:
  graph/output/D18/visualize/wcc_s1_{T1}_wcc_{T2}_no_consec/triad_{i:03d}.png

実行:
  cd /home/sonozuka/design_similarity
  python graph/verify/visualize_threshold.py
  python graph/verify/visualize_threshold.py --t1 0.975 --t2 0.90 --no-consec
"""

import argparse
from pathlib import Path

from triad_plotter import (
    load_jsonl, build_image_map, build_judgment_map, run_analysis,
)

# ==============================================================================
# デフォルト設定
# ==============================================================================

_DEFAULT_T1  = 0.90
_DEFAULT_T2  = 0.90

WCC_SCORED   = Path('graph/output/D18/verify/wcc_scored.jsonl')
WCC_NO_CONSEC = Path('graph/output/D18/triads/wcc_no_consec.jsonl')
ALL_JSONL    = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
OUT_BASE     = Path('graph/output/D18/visualize')

# ==============================================================================
# メイン
# ==============================================================================

def main(t1: float = _DEFAULT_T1, t2: float = _DEFAULT_T2,
         no_consec: bool = False) -> None:
    src = WCC_NO_CONSEC if no_consec else WCC_SCORED
    t1_tag = f'{int(t1 * 1000):04d}'
    t2_tag = f'{int(t2 * 1000):04d}'
    suffix = '_no_consec' if no_consec else ''
    name   = f'wcc_s1_{t1_tag}_wcc_{t2_tag}{suffix}'

    print(f'Loading {src} ...')
    all_triads = load_jsonl(src)

    triads = [
        r for r in all_triads
        if r.get('score_weakest_link', 0.0) >= t1
        and r['score_wcc'] >= t2
    ]
    triads.sort(key=lambda r: -r['score_weakest_link'])
    print(f'  {len(triads)} triads pass T1≥{t1}, T2≥{t2}'
          f'{" (no_consec)" if no_consec else ""}')

    print(f'Loading {ALL_JSONL} ...')
    all_records = load_jsonl(ALL_JSONL)
    img_map  = build_image_map(all_records)
    judg_map = build_judgment_map(all_records)
    print(f'  {len(img_map)} image paths  |  {len(judg_map)} edge judgments')

    if no_consec:
        run_analysis(
            name, triads, img_map, judg_map, OUT_BASE,
            suptitle_fn=lambda t, seq: (
                f'D18   '
                f'S1={t["score_weakest_link"]:.3f}, S2={t["score_wcc"]:.3f}  '
                f'(T1≥{t1}, T2≥{t2}, non-consecutive)'
            ),
            caption_fn=lambda t, panel: f'Local clustering coefficient: {t.get(f"cc_{panel}", 0.0):.3f}',
            show_meta_panel=False,
            show_rank_conf=False,
        )
    else:
        run_analysis(
            name, triads, img_map, judg_map, OUT_BASE,
            suptitle_fn=lambda t, seq: (
                f'D18  seq={seq}  '
                f'S1={t["score_weakest_link"]:.4f}  '
                f'S2={t["score_wcc"]:.4f}  '
                f'(T1≥{t1}, T2≥{t2})'
            ),
        )


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='閾値フィルタ triad 可視化')
    parser.add_argument('--t1', type=float, default=_DEFAULT_T1,
                        help=f'S1 (weakest-link) 下限（デフォルト: {_DEFAULT_T1}）')
    parser.add_argument('--t2', type=float, default=_DEFAULT_T2,
                        help=f'S_WCC 下限（デフォルト: {_DEFAULT_T2}）')
    parser.add_argument('--no-consec', action='store_true',
                        help='連番D-ID除去済みデータ (wcc_no_consec.jsonl) を使用')
    args = parser.parse_args()
    main(t1=args.t1, t2=args.t2, no_consec=args.no_consec)
