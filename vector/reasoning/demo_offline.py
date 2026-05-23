"""
demo_offline.py
===============

API を呼ばずにスキーマ・ロジック・サンプルデータだけで動作を確認するデモ。

確認内容:
  1. Pydantic スキーマの import と構築
  2. RationaleGraph / PerfectMatchScore の手動インスタンス化
  3. compute_pms() の計算ロジック（モック M2/M3/M1 入力）
  4. extract_pilot.py の sample_pilot()（入力 CSV があれば）
  5. merge_results.py / analyze_results.py の preprocess()

使い方:
  python3 demo_offline.py

入力 CSV は固定:
  /home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


# ============================================================================
# 1. Import verification
# ============================================================================

def check_imports() -> bool:
    ok = True

    print("=== Import check ===")

    # Core
    try:
        from patent_rationale_pms import (
            Facet, FacetState, FacetEvaluation, RationaleGraph,
            PerfectMatchScore, LLMConfig, DEFAULT_CONFIGS,
            compute_pms, _THINKING_BUDGET_MAP, MIN_INTERVAL_SEC,
        )
        print("[OK] patent_rationale_pms — core schemas imported")
    except ImportError as e:
        print(f"[FAIL] patent_rationale_pms: {e}")
        ok = False
        return ok

    # Visual probes
    try:
        from patent_visual_probes import (
            PerceptualClaim, ClaimExtractionResult,
            ClaimVerdict, ImageVerificationResult,
            VisualFaithfulnessScore, BaselineResult,
        )
        print("[OK] patent_visual_probes — M5/B schemas imported")
    except ImportError as e:
        print(f"[WARN] patent_visual_probes: {e}")

    # Extract pilot
    try:
        from extract_pilot import sample_pilot, STRATA
        print(f"[OK] extract_pilot — {len(STRATA)} strata defined")
    except ImportError as e:
        print(f"[WARN] extract_pilot: {e}")

    # Merge / analyze
    try:
        from merge_results import merge_all
        print("[OK] merge_results — merge_all imported")
    except ImportError as e:
        print(f"[WARN] merge_results: {e}")

    try:
        from analyze_results import preprocess, test_h_nlp1
        print("[OK] analyze_results — preprocess / test_h_nlp1 imported")
    except ImportError as e:
        print(f"[WARN] analyze_results: {e}")

    return ok


# ============================================================================
# 2. Schema construction
# ============================================================================

def demo_schemas() -> None:
    print("\n=== Schema construction ===")
    from patent_rationale_pms import (
        Facet, FacetState, FacetEvaluation, RationaleGraph,
        PerfectMatchScore,
    )

    # FacetEvaluation
    fe = FacetEvaluation(
        facet_reasoning="The rationale states 'both designs share the same rectangular silhouette', "
                        "suggesting identical global shape.",
        facet=Facet.GLOBAL_SHAPE,
        state=FacetState.IDENTICAL,
        evidence_span="both designs share the same rectangular silhouette",
        confidence=0.9,
    )
    print(f"[OK] FacetEvaluation: {fe.facet.value} → {fe.state.value} (conf={fe.confidence})")

    # RationaleGraph
    rg = RationaleGraph(
        overall_reasoning=(
            "The rationale consistently describes identical shapes and proportions. "
            "No contradictions detected. All aspects point toward similarity."
        ),
        consistency_flag="consistent",
        aspects=[fe],
    )
    print(f"[OK] RationaleGraph: {len(rg.aspects)} aspect(s), flag={rg.consistency_flag}")

    # PerfectMatchScore
    pms_schema = PerfectMatchScore(
        nli_reasoning=(
            "The hypothesis 'design A and B are visually equivalent' is strongly entailed "
            "by the rationale which uses phrases like 'identical overall appearance'."
        ),
        nli_label="strong_entailment",
        match_probability=0.93,
    )
    print(f"[OK] PerfectMatchScore: label={pms_schema.nli_label}, prob={pms_schema.match_probability}")


# ============================================================================
# 3. compute_pms logic
# ============================================================================

def demo_compute_pms() -> None:
    print("\n=== compute_pms logic ===")
    from patent_rationale_pms import compute_pms, RationaleGraph, FacetEvaluation, Facet, FacetState, PerfectMatchScore

    fe = FacetEvaluation(
        facet_reasoning="Clearly identical shape described.",
        facet=Facet.GLOBAL_SHAPE,
        state=FacetState.IDENTICAL,
        evidence_span="identical shape",
        confidence=0.95,
    )
    m1 = RationaleGraph(
        overall_reasoning="All aspects identical; consistent rationale. No internal contradictions found.",
        consistency_flag="consistent",
        aspects=[fe],
    )
    m2 = PerfectMatchScore(
        nli_reasoning="Hypothesis is strongly entailed by rationale evidence.",
        nli_label="strong_entailment",
        match_probability=0.92,
    )
    m3 = {"mean": 0.91, "std": 0.04, "scores": [0.89, 0.91, 0.93, 0.91, 0.90]}

    pms, conf, flags = compute_pms(m2, m3, m1)
    print(f"[OK] PMS={pms:.4f}, confidence={conf:.4f}, flags={flags}")

    # Test with contradiction
    m1_bad = RationaleGraph(
        overall_reasoning="Contradictory: says identical but then different. Ambiguous overall.",
        consistency_flag="internally_contradictory",
        aspects=[fe],
    )
    pms_bad, conf_bad, flags_bad = compute_pms(m2, m3, m1_bad)
    print(f"[OK] PMS(contradictory)={pms_bad:.4f}, flags={flags_bad}")


# ============================================================================
# 4. Pilot sampling (requires CSV)
# ============================================================================

def demo_pilot(input_csv: str) -> None:
    print(f"\n=== Pilot sampling ({input_csv}) ===")
    try:
        import pandas as pd
        from extract_pilot import sample_pilot, STRATA
    except ImportError as e:
        print(f"[SKIP] {e}")
        return

    p = Path(input_csv)
    if not p.exists():
        print(f"[SKIP] File not found: {p}")
        return

    df = pd.read_csv(p)
    print(f"Input: {len(df)} rows")
    pilot_df, strata_df = sample_pilot(df, seed=42)
    print(f"Pilot: {len(pilot_df)} rows")
    print(strata_df.to_string(index=False))


# ============================================================================
# 5. Preprocess check
# ============================================================================

def demo_preprocess() -> None:
    print("\n=== analyze_results.preprocess ===")
    try:
        import pandas as pd
        from analyze_results import preprocess
    except ImportError as e:
        print(f"[SKIP] {e}")
        return

    dummy = pd.DataFrame({
        "source": ["A", "B", "C"],
        "target": ["X", "Y", "Z"],
        "similarity": [0.97, 0.96, 0.95],
        "judgment": ["Yes", "No", "Yes"],
        "reason": [
            "Both designs are identical in shape and proportions.",
            "The designs differ in the handle configuration.",
            "Same overall silhouette with minor variation.",
        ],
        "pms": [0.91, 0.12, 0.55],
    })
    out = preprocess(dummy)
    print("[OK] judgment_bin:", out["judgment_bin"].tolist())
    print("[OK] is_exact:     ", out["is_exact"].tolist())


# ============================================================================
# 6. _THINKING_BUDGET_MAP check
# ============================================================================

def demo_thinking_map() -> None:
    print("\n=== _THINKING_BUDGET_MAP ===")
    from patent_rationale_pms import _THINKING_BUDGET_MAP, MIN_INTERVAL_SEC
    for level, budget in _THINKING_BUDGET_MAP.items():
        print(f"  {level:10s} → {budget:5d} tokens")
    print(f"  MIN_INTERVAL_SEC = {MIN_INTERVAL_SEC}")


# ============================================================================
# Main
# ============================================================================

_DEFAULT_INPUT = "/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv"


def main() -> None:
    ok = check_imports()
    if not ok:
        print("\n[ERROR] Core import failed. Install requirements and try again.")
        sys.exit(1)

    demo_schemas()
    demo_compute_pms()
    demo_thinking_map()
    demo_preprocess()
    demo_pilot(_DEFAULT_INPUT)

    print("\n=== All offline checks passed ===")


if __name__ == "__main__":
    main()