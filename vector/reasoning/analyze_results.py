"""
analyze_results.py
==================

unified_results.csv を読み込み、5 つの事前登録仮説（H_NLP1–H_NLP5）を検定し、
5 枚の図を生成する。

仮説:
  H_NLP1: PMS と cos 類似度に正の相関（Spearman ρ > 0）
  H_NLP2: Exact match group の PMS > Non-exact group（片側 t 検定）
  H_NLP3: M5 score と PMS に正の相関（Spearman ρ > 0）
  H_NLP4: Baseline B と LLM judgment の一致率 > 0.7
  H_NLP5: PMS は cos 類似度より human judgment を予測する（AUC 比較 / Steiger の Z 検定）

出力:
  --out-dir/ 以下に analysis_summary.txt, fig_*.png を生成

使い方:
  python analyze_results.py unified_results.csv --out-dir analysis/
"""

from __future__ import annotations

import argparse
import logging
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger("analyze_results")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Optional: matplotlib for figures
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
    _HAS_MPL = True
except ImportError:
    _HAS_MPL = False
    log.warning("matplotlib not installed; figures will be skipped")

# Optional: sklearn for AUC
try:
    from sklearn.metrics import roc_auc_score
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

# Optional: tabulate for markdown tables
try:
    from tabulate import tabulate
    _HAS_TABULATE = True
except ImportError:
    _HAS_TABULATE = False


# ============================================================================
# Figure style (PRL single-column)
# ============================================================================

PRL_STYLE = {
    "font.family":      "serif",
    "font.serif":       ["Times New Roman", "DejaVu Serif"],
    "font.size":        9,
    "axes.labelsize":   10,
    "axes.titlesize":   9,
    "xtick.direction":  "in",
    "ytick.direction":  "in",
    "xtick.top":        True,
    "ytick.right":      True,
    "figure.dpi":       300,
    "figure.figsize":   (3.37, 2.8),
}


def _apply_style():
    if _HAS_MPL:
        plt.rcParams.update(PRL_STYLE)


# ============================================================================
# Helper: markdown table (tabulate fallback)
# ============================================================================

def _df_to_markdown(df: pd.DataFrame) -> str:
    if _HAS_TABULATE:
        return tabulate(df, headers="keys", tablefmt="pipe", showindex=False)
    lines = ["| " + " | ".join(str(c) for c in df.columns) + " |"]
    lines.append("| " + " | ".join("---" for _ in df.columns) + " |")
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.values) + " |")
    return "\n".join(lines)


# ============================================================================
# Pre-processing
# ============================================================================

def _binary_judgment(val: str | float) -> int | None:
    """Convert judgment string to 1 (Yes) / 0 (No) / None (Unknown)."""
    if pd.isna(val):
        return None
    s = str(val).strip().lower()
    if s == "yes":
        return 1
    if s == "no":
        return 0
    return None


def _is_exact(reason: str) -> bool:
    """True if reason text contains an exact-match keyword."""
    EXACT_KW = ["identical", "exact", "same"]
    text = str(reason).lower()
    return any(f" {kw} " in f" {text} " or text.startswith(kw) or text.endswith(kw)
               for kw in EXACT_KW)


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "judgment" in df.columns:
        df["judgment_bin"] = df["judgment"].apply(_binary_judgment)

    if "reason" in df.columns:
        df["is_exact"] = df["reason"].apply(_is_exact)

    return df


# ============================================================================
# H_NLP1: PMS vs cosine similarity (Spearman ρ)
# ============================================================================

def test_h_nlp1(df: pd.DataFrame) -> dict:
    """H_NLP1: PMS と cos 類似度に正の相関"""
    needed = {"pms", "similarity"}
    sub = df[list(needed)].dropna()
    if len(sub) < 3:
        return {"hypothesis": "H_NLP1", "result": "SKIP", "note": "insufficient data"}

    rho, pval = stats.spearmanr(sub["similarity"], sub["pms"])
    return {
        "hypothesis": "H_NLP1",
        "n": len(sub),
        "rho": round(rho, 4),
        "p_value": round(pval, 6),
        "result": "SUPPORT" if rho > 0 and pval < 0.05 else "NOT_SUPPORT",
        "note": "Spearman ρ(similarity, pms)",
    }


# ============================================================================
# H_NLP2: Exact vs Non-exact PMS (one-sided t-test)
# ============================================================================

def test_h_nlp2(df: pd.DataFrame) -> dict:
    """H_NLP2: Exact match group の PMS > Non-exact group"""
    needed = {"pms", "is_exact"}
    sub = df[list(needed)].dropna()
    exact     = sub[sub["is_exact"] == True]["pms"].values
    non_exact = sub[sub["is_exact"] == False]["pms"].values

    if len(exact) < 2 or len(non_exact) < 2:
        return {"hypothesis": "H_NLP2", "result": "SKIP", "note": "insufficient data"}

    tstat, pval_two = stats.ttest_ind(exact, non_exact, alternative="greater")
    return {
        "hypothesis": "H_NLP2",
        "n_exact": len(exact),
        "n_nonexact": len(non_exact),
        "mean_exact": round(float(exact.mean()), 4),
        "mean_nonexact": round(float(non_exact.mean()), 4),
        "t_stat": round(tstat, 4),
        "p_value": round(pval_two, 6),
        "result": "SUPPORT" if tstat > 0 and pval_two < 0.05 else "NOT_SUPPORT",
        "note": "one-sided t-test: exact > non-exact",
    }


# ============================================================================
# H_NLP3: M5 score vs PMS (Spearman ρ)
# ============================================================================

def test_h_nlp3(df: pd.DataFrame) -> dict:
    """H_NLP3: M5 score と PMS に正の相関"""
    needed = {"m5_score", "pms"}
    sub = df[list(needed)].dropna()
    if len(sub) < 3:
        return {"hypothesis": "H_NLP3", "result": "SKIP", "note": "insufficient data"}

    rho, pval = stats.spearmanr(sub["m5_score"], sub["pms"])
    return {
        "hypothesis": "H_NLP3",
        "n": len(sub),
        "rho": round(rho, 4),
        "p_value": round(pval, 6),
        "result": "SUPPORT" if rho > 0 and pval < 0.05 else "NOT_SUPPORT",
        "note": "Spearman ρ(m5_score, pms)",
    }


# ============================================================================
# H_NLP4: Baseline B agreement with LLM judgment (rate > 0.7)
# ============================================================================

def test_h_nlp4(df: pd.DataFrame) -> dict:
    """H_NLP4: Baseline B と LLM judgment の一致率 > 0.7"""
    needed = {"b_baseline_judgment", "judgment_bin"}
    sub = df[list(needed)].dropna()
    if len(sub) < 3:
        return {"hypothesis": "H_NLP4", "result": "SKIP", "note": "insufficient data"}

    b_bin = sub["b_baseline_judgment"].apply(
        lambda x: 1 if str(x).strip().lower() == "yes" else 0
    )
    agreement = (b_bin == sub["judgment_bin"]).mean()
    # One-sample z-test against 0.7
    n = len(sub)
    z = (agreement - 0.7) / ((0.7 * 0.3 / n) ** 0.5)
    pval = 1 - stats.norm.cdf(z)
    return {
        "hypothesis": "H_NLP4",
        "n": n,
        "agreement_rate": round(agreement, 4),
        "z_stat": round(z, 4),
        "p_value": round(pval, 6),
        "result": "SUPPORT" if agreement > 0.7 and pval < 0.05 else "NOT_SUPPORT",
        "note": "one-sided z-test: agreement > 0.7",
    }


# ============================================================================
# H_NLP5: PMS AUC > cosine AUC (Steiger's Z)
# ============================================================================

def _auc_or_nan(y_true, scores) -> float:
    if not _HAS_SKLEARN or len(set(y_true)) < 2:
        return float("nan")
    try:
        return roc_auc_score(y_true, scores)
    except Exception:
        return float("nan")


def _steiger_z(r1: float, r2: float, r12: float, n: int) -> tuple[float, float]:
    """Steiger (1980) Z-test for comparing two dependent correlations."""
    if n < 5:
        return float("nan"), float("nan")
    f1 = 0.5 * np.log((1 + r1) / (1 - r1))
    f2 = 0.5 * np.log((1 + r2) / (1 - r2))
    r_bar = (r1 + r2) / 2
    h = ((1 - r12) * (1 - r12)) / (2 * (1 - r_bar**2)**2)
    se = np.sqrt(1 / (n - 3) + h / (n - 1))
    z = (f1 - f2) / se
    pval = 1 - stats.norm.cdf(z)
    return float(z), float(pval)


def test_h_nlp5(df: pd.DataFrame) -> dict:
    """H_NLP5: PMS は cos 類似度より human judgment を予測する（AUC 比較）"""
    needed = {"pms", "similarity", "judgment_bin"}
    sub = df[list(needed)].dropna()
    if len(sub) < 5:
        return {"hypothesis": "H_NLP5", "result": "SKIP", "note": "insufficient data"}

    y    = sub["judgment_bin"].values.astype(int)
    auc_pms = _auc_or_nan(y, sub["pms"].values)
    auc_sim = _auc_or_nan(y, sub["similarity"].values)

    if np.isnan(auc_pms) or np.isnan(auc_sim):
        return {
            "hypothesis": "H_NLP5",
            "result": "SKIP",
            "note": "AUC computation failed (sklearn not available or single class)",
        }

    # Spearman correlations for Steiger test
    rho_pms, _ = stats.spearmanr(sub["pms"], sub["judgment_bin"])
    rho_sim, _ = stats.spearmanr(sub["similarity"], sub["judgment_bin"])
    rho_cross, _ = stats.spearmanr(sub["pms"], sub["similarity"])
    z, pval = _steiger_z(rho_pms, rho_sim, rho_cross, len(sub))

    return {
        "hypothesis": "H_NLP5",
        "n": len(sub),
        "auc_pms": round(auc_pms, 4),
        "auc_similarity": round(auc_sim, 4),
        "steiger_z": round(z, 4) if not np.isnan(z) else None,
        "p_value": round(pval, 6) if not np.isnan(pval) else None,
        "result": "SUPPORT" if auc_pms > auc_sim and (not np.isnan(pval)) and pval < 0.05 else "NOT_SUPPORT",
        "note": "Steiger Z comparing Spearman ρ(PMS,judgment) vs ρ(similarity,judgment)",
    }


# ============================================================================
# Figures
# ============================================================================

def fig_pms_vs_similarity(df: pd.DataFrame, out_dir: Path) -> None:
    """Fig 1: PMS vs cosine similarity scatter."""
    if not _HAS_MPL:
        return
    sub = df[["similarity", "pms", "judgment"]].dropna(subset=["similarity", "pms"])
    if sub.empty:
        return

    _apply_style()
    fig, ax = plt.subplots()
    colors = sub["judgment"].map({"Yes": "#2166ac", "No": "#d6604d"}).fillna("#aaaaaa")
    ax.scatter(sub["similarity"], sub["pms"], c=colors, s=12, alpha=0.7, linewidths=0)
    ax.set_xlabel("Cosine similarity")
    ax.set_ylabel("PMS")
    ax.set_title("PMS vs cosine similarity")
    from matplotlib.lines import Line2D
    legend = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#2166ac", label="Yes"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#d6604d", label="No"),
    ]
    ax.legend(handles=legend, fontsize=8)
    fig.tight_layout()
    out = out_dir / "fig_pms_vs_similarity.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    log.info("Saved %s", out)


def fig_pms_distribution(df: pd.DataFrame, out_dir: Path) -> None:
    """Fig 2: PMS distribution by judgment group."""
    if not _HAS_MPL:
        return
    sub = df[["pms", "judgment"]].dropna()
    if sub.empty:
        return

    _apply_style()
    fig, ax = plt.subplots()
    for label, color in [("Yes", "#2166ac"), ("No", "#d6604d")]:
        vals = sub[sub["judgment"] == label]["pms"]
        if not vals.empty:
            ax.hist(vals, bins=20, alpha=0.6, color=color, label=label, density=True)
    ax.set_xlabel("PMS")
    ax.set_ylabel("Density")
    ax.set_title("PMS distribution by judgment")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out = out_dir / "fig_pms_distribution.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    log.info("Saved %s", out)


def fig_m5_vs_pms(df: pd.DataFrame, out_dir: Path) -> None:
    """Fig 3: M5 score vs PMS scatter."""
    if not _HAS_MPL:
        return
    sub = df[["m5_score", "pms"]].dropna()
    if sub.empty:
        log.info("Fig 3 skipped: no m5_score data")
        return

    _apply_style()
    fig, ax = plt.subplots()
    ax.scatter(sub["m5_score"], sub["pms"], s=12, alpha=0.7, color="#4dac26", linewidths=0)
    ax.set_xlabel("M5 score (visual faithfulness)")
    ax.set_ylabel("PMS")
    ax.set_title("M5 score vs PMS")
    fig.tight_layout()
    out = out_dir / "fig_m5_vs_pms.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    log.info("Saved %s", out)


def fig_baseline_vs_judgment(df: pd.DataFrame, out_dir: Path) -> None:
    """Fig 4: Baseline B agreement confusion-style bar."""
    if not _HAS_MPL:
        return
    needed = {"b_baseline_judgment", "judgment"}
    sub = df[list(needed)].dropna()
    if sub.empty:
        log.info("Fig 4 skipped: no baseline data")
        return

    _apply_style()
    combos = pd.crosstab(sub["judgment"], sub["b_baseline_judgment"])
    fig, ax = plt.subplots()
    combos.plot(kind="bar", ax=ax, colormap="Set2", edgecolor="white", linewidth=0.5)
    ax.set_xlabel("LLM judgment")
    ax.set_ylabel("Count")
    ax.set_title("LLM judgment vs Baseline B")
    ax.legend(title="Baseline B", fontsize=8)
    ax.tick_params(axis="x", rotation=0)
    fig.tight_layout()
    out = out_dir / "fig_baseline_vs_judgment.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    log.info("Saved %s", out)


def fig_exact_vs_nonexact_pms(df: pd.DataFrame, out_dir: Path) -> None:
    """Fig 5: PMS by exact / non-exact category (violin or box)."""
    if not _HAS_MPL:
        return
    needed = {"pms", "is_exact"}
    sub = df[list(needed)].dropna()
    if sub.empty:
        log.info("Fig 5 skipped: no is_exact data")
        return

    _apply_style()
    fig, ax = plt.subplots()
    groups = [
        sub[sub["is_exact"] == True]["pms"].values,
        sub[sub["is_exact"] == False]["pms"].values,
    ]
    labels = ["Exact match", "Non-exact"]
    parts = ax.violinplot(groups, positions=[1, 2], showmedians=True, showextrema=True)
    for pc, color in zip(parts["bodies"], ["#7b3294", "#008837"]):
        pc.set_facecolor(color)
        pc.set_alpha(0.7)
    ax.set_xticks([1, 2])
    ax.set_xticklabels(labels)
    ax.set_ylabel("PMS")
    ax.set_title("PMS by match type")
    fig.tight_layout()
    out = out_dir / "fig_exact_vs_nonexact_pms.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    log.info("Saved %s", out)


# ============================================================================
# Summary writer
# ============================================================================

def write_summary(
    hypothesis_results: list[dict],
    df: pd.DataFrame,
    out_dir: Path,
) -> None:
    lines = [
        "# Analysis Summary",
        f"\nN = {len(df)} rows in unified_results.csv\n",
        "## Hypothesis Tests\n",
    ]

    hr_df = pd.DataFrame(hypothesis_results)
    lines.append(_df_to_markdown(hr_df))
    lines.append("")

    lines.append("## Descriptive Statistics\n")
    numeric_cols = ["pms", "pms_confidence", "m5_score", "similarity",
                    "b_baseline_confidence", "n_claims", "upr"]
    existing = [c for c in numeric_cols if c in df.columns]
    if existing:
        desc = df[existing].describe().round(4)
        lines.append(_df_to_markdown(desc.reset_index()))

    out = out_dir / "analysis_summary.txt"
    out.write_text("\n".join(lines))
    log.info("Summary saved: %s", out)
    print("\n".join(lines))


# ============================================================================
# Main
# ============================================================================

_WORK_DIR   = Path("/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/reasoning")
_INPUT_CSV  = _WORK_DIR / "unified_results.csv"
_OUT_DIR    = _WORK_DIR / "analysis"


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    if not _INPUT_CSV.exists():
        log.error("unified_results.csv が存在しません。先に merge_results.py を実行してください: %s", _INPUT_CSV)
        return

    out_dir = _OUT_DIR
    df = pd.read_csv(_INPUT_CSV)
    log.info("Loaded: %d rows × %d cols", len(df), len(df.columns))

    df = preprocess(df)

    # Run all hypothesis tests
    results = [
        test_h_nlp1(df),
        test_h_nlp2(df),
        test_h_nlp3(df),
        test_h_nlp4(df),
        test_h_nlp5(df),
    ]

    # Generate figures
    fig_pms_vs_similarity(df, out_dir)
    fig_pms_distribution(df, out_dir)
    fig_m5_vs_pms(df, out_dir)
    fig_baseline_vs_judgment(df, out_dir)
    fig_exact_vs_nonexact_pms(df, out_dir)

    write_summary(results, df, out_dir)


if __name__ == "__main__":
    main()