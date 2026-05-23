"""
merge_results.py
================

全モジュール出力を (source, target) キーで結合して unified_results.csv を生成する。

入力 CSV:
  --pms       patent_rationale_pms.py の出力（PMS スコア + M1/M2/M3）
  --m5        patent_visual_probes.py の M5 出力
  --baseline  patent_visual_probes.py の B baseline 出力
  --strata    extract_pilot.py の strata 監査テーブル（省略可）
  --annotations 人手アノテーション CSV（省略可）
  --input     元 CSV（similarity, judgment, confidence, reason 等を補完）

出力:
  --out       unified_results.csv

使い方:
  python merge_results.py \\
      --input  high_sim_perspective_0950_judged.csv \\
      --pms    reasoning/pms_results.csv \\
      --m5     reasoning/m5_scores.csv \\
      --baseline reasoning/baseline_b.csv \\
      --out    reasoning/unified_results.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("merge_results")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ============================================================================
# helpers
# ============================================================================

def _read_optional(path: str | None, label: str) -> pd.DataFrame | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        log.warning("%s not found: %s", label, p)
        return None
    df = pd.read_csv(p)
    log.info("%s: %d rows", label, len(df))
    return df


def _merge_on_pair(left: pd.DataFrame, right: pd.DataFrame, suffix: str) -> pd.DataFrame:
    """Left-join right onto left on (source, target), adding suffix to conflicts."""
    return left.merge(right, on=["source", "target"], how="left", suffixes=("", f"_{suffix}"))


# ============================================================================
# main merge logic
# ============================================================================

def merge_all(
    input_csv:   str,
    pms_csv:     str | None = None,
    m5_csv:      str | None = None,
    baseline_csv: str | None = None,
    strata_csv:  str | None = None,
    annotations_csv: str | None = None,
    output_csv:  str = "unified_results.csv",
) -> pd.DataFrame:

    # base: the original judged CSV (has similarity, judgment, confidence, reason, image paths)
    base = pd.read_csv(input_csv)
    log.info("Base: %d rows", len(base))

    # ensure key columns exist
    for col in ("source", "target"):
        if col not in base.columns:
            raise ValueError(f"Base CSV missing column: {col}")

    result = base.copy()

    # --- PMS ---
    pms = _read_optional(pms_csv, "PMS")
    if pms is not None:
        pms_cols = [c for c in pms.columns if c not in ("source", "target")]
        result = _merge_on_pair(result, pms[["source", "target"] + pms_cols], "pms")
        log.info("After PMS merge: %d cols", len(result.columns))

    # --- M5 ---
    m5 = _read_optional(m5_csv, "M5")
    if m5 is not None:
        # rename to avoid clash with base columns
        rename = {}
        for c in m5.columns:
            if c not in ("source", "target") and c in result.columns:
                rename[c] = f"m5_{c}"
        m5 = m5.rename(columns=rename)
        # prefix remaining m5 columns that aren't already prefixed
        for c in list(m5.columns):
            if c not in ("source", "target") and not c.startswith("m5_") and c in result.columns:
                m5 = m5.rename(columns={c: f"m5_{c}"})
        result = _merge_on_pair(result, m5, "m5dup")
        log.info("After M5 merge: %d cols", len(result.columns))

    # --- Baseline B ---
    bl = _read_optional(baseline_csv, "Baseline B")
    if bl is not None:
        bl_rename = {c: f"b_{c}" for c in bl.columns if c not in ("source", "target")}
        bl = bl.rename(columns=bl_rename)
        result = _merge_on_pair(result, bl, "bdup")
        log.info("After Baseline B merge: %d cols", len(result.columns))

    # --- Strata labels (pilot sample) ---
    st = _read_optional(strata_csv, "Strata")
    if st is not None and "stratum" in st.columns:
        # strata CSV has columns: stratum, n_target, n_actual, description
        # This is the audit table; the per-row stratum labels are in the pilot CSV
        # If the user passes the pilot CSV instead, join on source/target
        if "source" in st.columns and "target" in st.columns:
            result = _merge_on_pair(result, st[["source", "target", "_stratum"]], "stdup")
        else:
            log.warning("Strata CSV has no source/target columns; skipping row-level join")

    # --- Human annotations ---
    ann = _read_optional(annotations_csv, "Annotations")
    if ann is not None and "source" in ann.columns and "target" in ann.columns:
        ann_rename = {c: f"human_{c}" for c in ann.columns
                      if c not in ("source", "target") and not c.startswith("human_")}
        ann = ann.rename(columns=ann_rename)
        result = _merge_on_pair(result, ann, "anndup")
        log.info("After Annotations merge: %d cols", len(result.columns))

    # --- Drop duplicate suffix columns created by merge conflicts ---
    dup_cols = [c for c in result.columns if c.endswith(("_pms", "_m5dup", "_bdup", "_stdup", "_anndup"))]
    if dup_cols:
        log.debug("Dropping dup columns: %s", dup_cols)
        result = result.drop(columns=dup_cols)

    # --- Sort by similarity descending ---
    if "similarity" in result.columns:
        result = result.sort_values("similarity", ascending=False).reset_index(drop=True)

    out_path = Path(output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False)
    log.info("Saved unified_results.csv: %d rows × %d cols → %s", len(result), len(result.columns), out_path)
    return result


# ============================================================================
# CLI
# ============================================================================

_INPUT_CSV  = Path("/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv")
_WORK_DIR   = _INPUT_CSV.parent / "reasoning"
_PILOT_CSV  = _WORK_DIR / "pilot_24.csv"


def main() -> None:
    parser = argparse.ArgumentParser(description="全モジュール出力を unified_results.csv に結合")
    parser.add_argument("--annotations", default=None, help="人手アノテーション CSV（任意）")
    args = parser.parse_args()

    def _opt(p: Path) -> str | None:
        return str(p) if p.exists() else None

    merge_all(
        input_csv       = str(_INPUT_CSV),
        pms_csv         = _opt(_WORK_DIR / "pms_results.csv"),
        m5_csv          = _opt(_WORK_DIR / "m5_scores.csv"),
        baseline_csv    = _opt(_WORK_DIR / "baseline_b.csv"),
        strata_csv      = _opt(_PILOT_CSV),
        annotations_csv = args.annotations,
        output_csv      = str(_WORK_DIR / "unified_results.csv"),
    )


if __name__ == "__main__":
    main()