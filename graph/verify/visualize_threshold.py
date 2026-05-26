"""
T1 × T2 閾値フィルタ triad の可視化。

フィルタ条件:
  S1 (weakest-link)  >= T1_THRESH
  S_WCC              >= T2_THRESH

出力:
  graph/output/D18/visualize/wcc_s1_{T1}_wcc_{T2}/triad_{i:03d}.png

実行:
  cd /home/sonozuka/design_similarity
  python graph/verify/visualize_threshold.py
"""

from pathlib import Path
from triad_plotter import (
    load_jsonl, build_image_map, build_judgment_map, run_analysis,
)

# ==============================================================================
# 設定
# ==============================================================================

T1_THRESH  = 0.90
T2_THRESH  = 0.90

WCC_SCORED = Path('graph/output/D18/verify/wcc_scored.jsonl')
ALL_JSONL  = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
OUT_BASE   = Path('graph/output/D18/visualize')

# ==============================================================================
# メイン
# ==============================================================================

def main() -> None:
    # サブディレクトリ名: 閾値を数値で表現（0.975 → 0975, 0.95 → 0950）
    t1_tag = f'{int(T1_THRESH * 1000):04d}'
    t2_tag = f'{int(T2_THRESH * 1000):04d}'
    name   = f'wcc_s1_{t1_tag}_wcc_{t2_tag}'

    print(f'Loading {WCC_SCORED} ...')
    all_triads = load_jsonl(WCC_SCORED)

    triads = [
        r for r in all_triads
        if r.get('score_weakest_link', 0.0) >= T1_THRESH
        and r['score_wcc'] >= T2_THRESH
    ]
    triads.sort(key=lambda r: -r['score_weakest_link'])
    print(f'  {len(triads)} triads pass T1≥{T1_THRESH}, T2≥{T2_THRESH}')

    print(f'Loading {ALL_JSONL} ...')
    all_records = load_jsonl(ALL_JSONL)
    img_map  = build_image_map(all_records)
    judg_map = build_judgment_map(all_records)
    print(f'  {len(img_map)} image paths  |  {len(judg_map)} edge judgments')

    run_analysis(
        name, triads, img_map, judg_map, OUT_BASE,
        suptitle_fn=lambda t, seq: (
            f'D18  seq={seq}  '
            f'S1={t["score_weakest_link"]:.4f}  '
            f'S2={t["score_wcc"]:.4f}  '
            f'(T1≥{T1_THRESH}, T2≥{T2_THRESH})'
        ),
    )


if __name__ == '__main__':
    main()
