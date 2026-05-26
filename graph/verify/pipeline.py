"""
graph/verify パイプライン — WCC スコアの再計算と全グリッド画像の一括出力。

このスクリプトは「データが更新されたときに毎回実行する」ステップのみを含む。
triad 個別画像の生成は visualize_threshold.py を別途実行すること。

ステップ:
  Step 1  wcc_scoring.py
            - WCC スコア計算（全 1593 triads）
            - wcc_scored.jsonl, wcc_no_consec.jsonl の更新
            - グリッド画像（全体・FP・FN、各 original / no_consec）の再出力

出力先:
  graph/output/D18/verify/    グリッド画像・分布図・FP/FN CSV・wcc_scored.jsonl
  graph/output/D18/triads/    wcc_no_consec.jsonl

実行:
  cd /home/sonozuka/design_similarity
  python graph/verify/pipeline.py

triad 個別画像の生成:
  python graph/verify/visualize_threshold.py [--t1 X] [--t2 X] [--no-consec]
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _banner(title: str) -> None:
    print(f'\n{"=" * 60}')
    print(f'  {title}')
    print('=' * 60)


def main() -> None:
    t0 = time.time()

    _banner('Step 1: WCC Scoring')
    import wcc_scoring
    wcc_scoring.main()

    elapsed = time.time() - t0
    _banner(f'Done  ({elapsed:.1f}s)')


if __name__ == '__main__':
    main()
