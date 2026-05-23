"""
extract_pilot.py
----------------
事前登録済みシード（seed=42）による層別パイロットサンプリング。
220 行の CSV から 23 行を 6 層に分けて選択する。

使い方:
    python extract_pilot.py

入力・出力パスは固定:
    INPUT_CSV  : vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv
    PILOT_CSV  : vector/output/D18/cosine_numpy/reasoning/pilot_24.csv
    STRATA_CSV : vector/output/D18/cosine_numpy/reasoning/pilot_strata.csv
"""

import re
from pathlib import Path

import pandas as pd


# ─── 層定義 ───────────────────────────────────────────────────────────────────

EXACT_KEYWORDS = ["identical", "exact", "same"]

STRATA = [
    # (層ID, 説明, 件数)
    ("L1", "self-inconsistent (conf=5 & No & 'identical' in reason)", 2),
    ("L2", "high-sim paradox (sim>=0.99 & No)",                       4),
    ("L3", "high-sim match (sim>=0.99 & Yes)",                        5),
    ("L4", "low-sim match (lowest sim & Yes)",                        5),
    ("L5", "calibration boundary (sim in [0.965, 0.975])",            5),
    ("L6", "design-family cluster (largest component)",               2),
]


def _has_exact_keyword(reason: str) -> bool:
    for kw in EXACT_KEYWORDS:
        if re.search(rf"\b{kw}\b", str(reason), re.IGNORECASE):
            return True
    return False


def _find_largest_component(df: pd.DataFrame) -> set[str]:
    """source/target で構築した無向グラフの最大連結成分のノードセットを返す。"""
    try:
        import networkx as nx
        G = nx.Graph()
        for _, row in df.iterrows():
            G.add_edge(str(row["source"]), str(row["target"]))
        if len(G.nodes) == 0:
            return set()
        largest = max(nx.connected_components(G), key=len)
        return largest
    except ImportError:
        # networkx がなければ source の最頻値グループで代替
        freq = df["source"].value_counts()
        if freq.empty:
            return set()
        top = freq.index[0]
        return set(df[df["source"] == top]["target"].tolist() + [top])


def sample_pilot(df: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    層別サンプリングを実行する。

    Returns:
        (pilot_df, strata_df)  ← pilot_df: 23 行, strata_df: 監査テーブル
    """
    df = df.copy()
    df["_has_exact"] = df["reason"].apply(_has_exact_keyword)

    sampled: dict[str, pd.DataFrame] = {}
    used_idx: set = set()

    # ── L1: 自己矛盾（conf=5 & No & reason に identical 系キーワード） ──────
    l1_mask = (
        (df["confidence"] == 5)
        & (df["judgment"].str.strip().str.lower() == "no")
        & df["_has_exact"]
    )
    pool = df[l1_mask & ~df.index.isin(used_idx)]
    n    = min(STRATA[0][2], len(pool))
    sel  = pool.sample(n=n, random_state=seed)
    sampled["L1"] = sel.assign(_stratum="L1")
    used_idx.update(sel.index)

    # ── L2: 高類似度パラドックス（sim>=0.99 & No） ──────────────────────────
    l2_mask = (df["similarity"] >= 0.99) & (df["judgment"].str.strip().str.lower() == "no")
    pool = df[l2_mask & ~df.index.isin(used_idx)]
    n    = min(STRATA[1][2], len(pool))
    sel  = pool.sample(n=n, random_state=seed)
    sampled["L2"] = sel.assign(_stratum="L2")
    used_idx.update(sel.index)

    # ── L3: 高類似度マッチ（sim>=0.99 & Yes） ──────────────────────────────
    l3_mask = (df["similarity"] >= 0.99) & (df["judgment"].str.strip().str.lower() == "yes")
    pool = df[l3_mask & ~df.index.isin(used_idx)]
    n    = min(STRATA[2][2], len(pool))
    sel  = pool.sample(n=n, random_state=seed)
    sampled["L3"] = sel.assign(_stratum="L3")
    used_idx.update(sel.index)

    # ── L4: 低類似度マッチ（similarity 最小 & Yes） ─────────────────────────
    l4_mask = df["judgment"].str.strip().str.lower() == "yes"
    pool = df[l4_mask & ~df.index.isin(used_idx)].sort_values("similarity")
    n    = min(STRATA[3][2], len(pool))
    sel  = pool.head(n)
    sampled["L4"] = sel.assign(_stratum="L4")
    used_idx.update(sel.index)

    # ── L5: キャリブレーション境界（sim in [0.965, 0.975]） ─────────────────
    l5_mask = (df["similarity"] >= 0.965) & (df["similarity"] <= 0.975)
    pool = df[l5_mask & ~df.index.isin(used_idx)]
    n    = min(STRATA[4][2], len(pool))
    sel  = pool.sample(n=n, random_state=seed)
    sampled["L5"] = sel.assign(_stratum="L5")
    used_idx.update(sel.index)

    # ── L6: デザインファミリークラスター（最大連結成分） ─────────────────────
    remaining = df[~df.index.isin(used_idx)]
    component = _find_largest_component(remaining)
    l6_mask   = (
        remaining["source"].isin(component) | remaining["target"].isin(component)
    )
    pool = remaining[l6_mask]
    n    = min(STRATA[5][2], len(pool))
    sel  = pool.sample(n=n, random_state=seed) if n > 0 else pool.head(0)
    sampled["L6"] = sel.assign(_stratum="L6")
    used_idx.update(sel.index)

    # ── 結合 ─────────────────────────────────────────────────────────────────
    pilot_df = pd.concat(sampled.values(), ignore_index=True)
    pilot_df = pilot_df.drop(columns=["_has_exact", "_stratum"], errors="ignore").reset_index(drop=True)

    # ── 監査テーブル ─────────────────────────────────────────────────────────
    records = []
    for stratum_id, desc, target_n in STRATA:
        actual_n = len(sampled.get(stratum_id, pd.DataFrame()))
        records.append({
            "stratum":   stratum_id,
            "n_target":  target_n,
            "n_actual":  actual_n,
            "description": desc,
        })
    strata_df = pd.DataFrame(records)

    return pilot_df, strata_df


INPUT_CSV  = Path("/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv")
OUTPUT_DIR = INPUT_CSV.parent / "reasoning"
PILOT_CSV  = OUTPUT_DIR / "pilot_24.csv"
STRATA_CSV = OUTPUT_DIR / "pilot_strata.csv"
SEED       = 42


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(INPUT_CSV)
    print(f"入力: {len(df)} 行  ({INPUT_CSV})")

    pilot_df, strata_df = sample_pilot(df, seed=SEED)

    pilot_df.to_csv(PILOT_CSV, index=False)
    strata_df.to_csv(STRATA_CSV, index=False)

    print(f"\nパイロット: {len(pilot_df)} 行 → {PILOT_CSV}")
    print(f"監査テーブル → {STRATA_CSV}\n")
    print(strata_df.to_string(index=False))


if __name__ == "__main__":
    main()