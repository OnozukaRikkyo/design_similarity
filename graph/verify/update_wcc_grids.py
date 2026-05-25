#!/usr/bin/env python3
"""
wcc グリッド図の更新パイプライン

discord_analysis.py (fp.csv / fn.csv を再生成)
  → wcc_scoring.py  (wcc_fp_grid.png / wcc_fn_grid.png / wcc_threshold_grid.png を再生成)

使い方:
  python graph/verify/update_wcc_grids.py
  python graph/verify/update_wcc_grids.py --class D18
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

HERE        = Path(__file__).resolve().parent   # graph/verify/
PROJECT_ROOT = HERE.parents[1]                  # design_similarity/


def run(cmd: list[str]) -> None:
    print(f"\n  $ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    if result.returncode != 0:
        print(f"\n[ERROR] 終了コード {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="wcc グリッド図を最新データで再生成する")
    parser.add_argument("--class", dest="target_class", default="D18",
                        help="対象クラスコード（デフォルト: D18）")
    args = parser.parse_args()
    cls = args.target_class

    print("=" * 56)
    print("wcc グリッド図 更新パイプライン")
    print(f"クラス: {cls}")
    print("=" * 56)

    t0 = time.time()

    print(f"\n[Step 1/2] discord_analysis.py → fp.csv / fn.csv")
    run([sys.executable, "graph/verify/discord_analysis.py", "--class", cls])

    print(f"\n[Step 2/2] wcc_scoring.py → wcc_*_grid.png")
    run([sys.executable, "graph/verify/wcc_scoring.py"])

    print(f"\n{'=' * 56}")
    print(f"完了: {time.time() - t0:.1f}s")
    print(f"出力: graph/output/{cls}/verify/")
    print(f"  wcc_fp_grid.png")
    print(f"  wcc_fn_grid.png")
    print(f"  wcc_threshold_grid.png")
    print("=" * 56)


if __name__ == "__main__":
    main()
