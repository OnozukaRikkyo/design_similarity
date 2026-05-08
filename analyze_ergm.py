#!/usr/bin/env python3
"""
USPTO 意匠特許共引用 ERGM 分析スクリプト
build_ergm_input.py の出力 (ergm_input/) を対象に、
優先度1→4 の順で全分析を実施する。

優先度1: クラス分布・ヒートマップ    (attributes.txt, arc_list.txt)
優先度2: 記述統計 density/degree    (attributes.txt, arc_list.txt)
優先度3: ERGM 推定係数可視化        (EstimNetDirected 出力 *.csv)
優先度4: Gemini Yes ペアとの突合     (similarity_results/*.jsonl, attributes.txt)

出力:
  output/priority1_class_dist.png       D-class 別ノード数棒グラフ
  output/priority1_n_classes_hist.png   n_classes 分布ヒストグラム
  output/priority1_date_timeline.png    年代別ノード数折れ線
  output/priority1_cocite_heatmap.png   クラス間共引用ヒートマップ (35×35)
  output/priority2_degree_dist.png      次数分布 (PDF + CCDF)
  output/priority2_descriptive.csv      記述統計サマリ
  output/priority3_ergm_coefs.png       ERGM 係数プロット (EstimNetDirected 出力があれば)
  output/priority4_gemini_vs_class.png  Gemini Yes/No のクラス分布比較
  output/priority4_jaccard_vs_sim.png   Jaccard 類似度 vs Gemini 判定
  output/analysis_summary.csv          全分析の数値サマリ
"""

import argparse
import json
import pickle
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
ALL_CLASSES: list[str] = [f"D{i}" for i in range(1, 35)] + ["D99"]

CLASS_NAMES: dict[str, str] = {
    "D1":  "Edible Products",        "D2":  "Apparel",
    "D3":  "Travel Goods",           "D4":  "Brushware",
    "D5":  "Textile",                "D6":  "Furnishings",
    "D7":  "Food Equipment",         "D8":  "Tools & Hardware",
    "D9":  "Tools (misc)",           "D10": "Measuring Devices",
    "D11": "Jewelry",                "D12": "Transportation",
    "D13": "Production Equipment",   "D14": "Recording/Comm/Info",
    "D15": "Machines",               "D16": "Photography/Optics",
    "D17": "Musical Instruments",    "D18": "Printing/Office Mach.",
    "D19": "Office Supplies",        "D20": "Sales/Advertising",
    "D21": "Amusement Devices",      "D22": "Arms/Pyrotechnics",
    "D23": "Heating/Cooling",        "D24": "Medical/Lab Equipment",
    "D25": "Building/Construction",  "D26": "Lighting",
    "D27": "Tobacco/Smoking",        "D28": "Pharma/Cosmetics",
    "D29": "Animal Husbandry",       "D30": "Outdoor/Garden",
    "D31": "Articles of Mfg",        "D32": "Washing/Cleaning",
    "D33": "Food/Bev Service",       "D34": "Material Handling",
    "D99": "Miscellaneous",
}

# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def save_meta(path: Path, caption: str, description: str = "") -> None:
    with open(str(path) + ".meta.json", "w") as f:
        json.dump({"caption": caption, "description": description}, f)


def load_arc_list(arc_path: Path) -> list[tuple[int, int]]:
    arcs = []
    with open(arc_path) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                arcs.append((int(parts[0]), int(parts[1])))
    return arcs


def arc_list_to_undirected_degree(
    arcs: list[tuple[int, int]], n_nodes: int
) -> tuple[np.ndarray, int]:
    """双方向アーク → 無向次数（重複を除く）"""
    edges_set: set[tuple[int, int]] = set()
    for u, v in arcs:
        if u != v:
            edges_set.add((min(u, v), max(u, v)))
    deg = np.zeros(n_nodes, dtype=np.int32)
    for u, v in edges_set:
        deg[u] += 1
        deg[v] += 1
    return deg, len(edges_set)


def _load_patent_cache(ergm_dir: Path) -> dict | None:
    """_patent_attr_cache.pkl をロードして返す。存在しない場合は None。"""
    cache_path = ergm_dir / "_patent_attr_cache.pkl"
    if not cache_path.exists():
        return None
    with open(cache_path, "rb") as f:
        return pickle.load(f)


# ===========================================================================
# 優先度 1: クラス分布・ヒートマップ
# ===========================================================================

def priority1_class_distribution(attrs: pd.DataFrame, out_dir: Path) -> None:
    """D-class 別ノード数棒グラフ"""
    counts = (
        attrs["primary_class"]
        .value_counts()
        .reindex(ALL_CLASSES, fill_value=0)
        .reset_index()
    )
    counts.columns = ["class", "count"]

    fig = px.bar(
        counts, x="class", y="count",
        title="D-class Distribution of Design Patents<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Primary class per node (ergm_input/attributes.txt)</span>",
        color="count",
        color_continuous_scale="Blues",
        text="count",
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside", cliponaxis=False)
    fig.update_xaxes(title_text="D-class")
    fig.update_yaxes(title_text="Node count")
    fig.update_layout(coloraxis_showscale=False, xaxis_tickangle=0)
    out_path = out_dir / "priority1_class_dist.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "D-class Distribution of Design Patents",
              "Bar chart showing node counts per USPTO design class (D1–D99).")
    print("  [P1] class_dist done")


def priority1_nclasses_hist(attrs: pd.DataFrame, out_dir: Path) -> None:
    """n_classes 分布ヒストグラム"""
    vc = attrs["n_classes"].value_counts().sort_index().reset_index()
    vc.columns = ["n_classes", "count"]

    fig = px.bar(
        vc, x="n_classes", y="count",
        title="Multi-class Patent Distribution<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Share of patents assigned to multiple D-classes</span>",
        text="count",
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside", cliponaxis=False)
    fig.update_xaxes(title_text="# classes")
    fig.update_yaxes(title_text="Node count")
    out_path = out_dir / "priority1_n_classes_hist.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Distribution of # D-classes per Patent",
              "Histogram showing how many D-classes each patent belongs to.")
    print("  [P1] n_classes_hist done")


def priority1_date_timeline(attrs: pd.DataFrame, out_dir: Path) -> None:
    """年代別ノード数折れ線グラフ"""
    df = attrs.copy()
    df["year"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce").dt.year
    yearly = df["year"].value_counts().sort_index().reset_index()
    yearly.columns = ["year", "count"]
    yearly = yearly.dropna().query("year >= 1970 and year <= 2030")

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=yearly["year"], y=yearly["count"],
        mode="lines+markers",
        fill="tozeroy",
        line=dict(width=2),
        name="Nodes",
    ))
    fig.update_layout(
        title="Network Growth by Year<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Number of patents (nodes) per filing year</span>",
        showlegend=False,
    )
    fig.update_xaxes(title_text="Year")
    fig.update_yaxes(title_text="Node count")
    out_path = out_dir / "priority1_date_timeline.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Patent Network Growth Over Time",
              "Line chart showing node count growth by year.")
    print("  [P1] date_timeline done")


def priority1_cocite_heatmap(
    attrs: pd.DataFrame,
    arcs: list[tuple[int, int]],
    out_dir: Path,
) -> None:
    """クラス間共引用ヒートマップ (35×35)"""
    present = set(attrs["primary_class"].values)
    cls_list = [c for c in ALL_CLASSES if c in present]
    cls_idx = {c: i for i, c in enumerate(cls_list)}
    node_cls = attrs["primary_class"].values

    mat = np.zeros((len(cls_list), len(cls_list)), dtype=np.int64)
    seen: set[tuple[int, int]] = set()
    for u, v in arcs:
        if u == v:
            continue
        key = (min(u, v), max(u, v))
        if key in seen:
            continue
        seen.add(key)
        cu = node_cls[u] if u < len(node_cls) else "Unknown"
        cv = node_cls[v] if v < len(node_cls) else "Unknown"
        if cu in cls_idx and cv in cls_idx:
            mat[cls_idx[cu], cls_idx[cv]] += 1
            if cu != cv:
                mat[cls_idx[cv], cls_idx[cu]] += 1

    log_mat = np.log1p(mat).astype(np.float32)

    fig = go.Figure(go.Heatmap(
        z=log_mat,
        x=cls_list,
        y=cls_list,
        colorscale="Blues",
        colorbar=dict(title="log(1+count)"),
        hovertemplate="From %{y} → To %{x}<br>Edges: %{customdata:,}<extra></extra>",
        customdata=mat,
    ))
    fig.update_layout(
        title="Co-citation Heatmap by D-class (35×35)<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "log(1+edge count) between primary classes</span>",
    )
    fig.update_xaxes(title_text="D-class (target)")
    fig.update_yaxes(title_text="D-class (source)")
    out_path = out_dir / "priority1_cocite_heatmap.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Co-citation Heatmap Between D-classes (35×35)",
              "Heatmap showing co-citation frequencies between USPTO design classes.")
    print("  [P1] cocite_heatmap done")


# ===========================================================================
# 優先度 2: 記述統計 density/degree
# ===========================================================================

def priority2_descriptive(
    attrs: pd.DataFrame,
    arcs: list[tuple[int, int]],
    out_dir: Path,
) -> dict:
    """記述統計サマリを計算して CSV 保存"""
    N = len(attrs)
    deg, M = arc_list_to_undirected_degree(arcs, N)

    max_possible = N * (N - 1) / 2
    density = M / max_possible if max_possible > 0 else 0.0

    summary = {
        "n_nodes": N,
        "n_edges": M,
        "n_arcs": len(arcs),
        "density": density,
        "mean_degree": float(deg.mean()),
        "median_degree": float(np.median(deg)),
        "max_degree": int(deg.max()),
        "min_degree": int(deg.min()),
        "std_degree": float(deg.std()),
        "n_isolates": int((deg == 0).sum()),
        "pct_multi_class": float((attrs["n_classes"] > 1).mean() * 100),
        "unique_primary_classes": int(attrs["primary_class"].nunique()),
    }

    pd.DataFrame([summary]).to_csv(out_dir / "priority2_descriptive.csv", index=False)
    print(
        f"  [P2] descriptive: N={N:,} M={M:,} "
        f"density={density:.2e} mean_deg={summary['mean_degree']:.2f}"
    )
    return {"deg": deg, "M": M, "summary": summary}


def priority2_degree_dist(deg: np.ndarray, out_dir: Path) -> None:
    """次数分布 PDF + CCDF (対数軸)"""
    deg_pos = deg[deg > 0]
    counts = np.bincount(deg_pos)
    d_vals = np.arange(len(counts))

    ccdf_x, ccdf_y = [], []
    cumsum = 0
    for d in range(len(counts) - 1, -1, -1):
        if counts[d] > 0:
            cumsum += counts[d]
            ccdf_x.append(d)
            ccdf_y.append(cumsum / len(deg_pos))
    ccdf_x = ccdf_x[::-1]
    ccdf_y = ccdf_y[::-1]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=d_vals[d_vals > 0],
        y=counts[d_vals > 0] / len(deg_pos),
        name="PDF",
        opacity=0.6,
    ))
    fig.add_trace(go.Scatter(
        x=ccdf_x, y=ccdf_y,
        mode="lines",
        name="CCDF",
        line=dict(width=2),
    ))
    fig.update_layout(
        title="Degree Distribution (PDF & CCDF)<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Log-log scale; undirected co-citation network</span>",
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
    )
    fig.update_xaxes(title_text="Degree", type="log")
    fig.update_yaxes(title_text="Probability", type="log")
    out_path = out_dir / "priority2_degree_dist.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Degree Distribution (PDF & CCDF)",
              "Log-log degree distribution and CCDF of the co-citation network.")
    print("  [P2] degree_dist done")


# ===========================================================================
# 優先度 3: ERGM 推定係数可視化
# ===========================================================================

def priority3_ergm_coefs(ergm_dir: Path, out_dir: Path) -> bool:
    """
    EstimNetDirected の出力 CSV (*theta*.csv 等) を読み込んで係数プロットを生成。
    ファイルが存在しない場合は False を返してスキップ。
    """
    candidates = list(ergm_dir.glob("*theta*.csv")) + list(ergm_dir.glob("*coef*.csv"))
    if not candidates:
        print("  [P3] EstimNetDirected 出力が見つかりません。スキップします。")
        print(f"       探索パス: {ergm_dir}")
        return False

    coef_path = sorted(candidates)[-1]
    print(f"  [P3] 係数ファイル: {coef_path}")
    df = pd.read_csv(coef_path)

    col_map = {}
    for col in df.columns:
        lc = col.lower().strip()
        if lc in ("param", "parameter", "term", "name", "statistic"):
            col_map[col] = "param"
        elif lc in ("theta", "estimate", "coef", "coefficient"):
            col_map[col] = "theta"
        elif lc in ("stderr", "se", "std_error", "std.error"):
            col_map[col] = "se"
    df = df.rename(columns=col_map)

    if "param" not in df.columns or "theta" not in df.columns:
        print(f"  [P3] 列 'param'/'theta' が見つかりません。列: {df.columns.tolist()}")
        return False

    df["theta"] = pd.to_numeric(df["theta"], errors="coerce")
    df = df.dropna(subset=["theta"])

    if "se" in df.columns:
        df["se"] = pd.to_numeric(df["se"], errors="coerce").fillna(0)
        df["ci_low"]  = df["theta"] - 1.96 * df["se"]
        df["ci_high"] = df["theta"] + 1.96 * df["se"]
    else:
        df["ci_low"]  = df["theta"]
        df["ci_high"] = df["theta"]

    df = df[~df["param"].str.contains("date", case=False, na=False)]
    df = df.sort_values("theta")
    colors = ["#d62728" if t > 0 else "#1f77b4" for t in df["theta"]]

    fig = go.Figure()
    for _, row in df.iterrows():
        fig.add_shape(
            type="line",
            x0=row["ci_low"], x1=row["ci_high"],
            y0=row["param"], y1=row["param"],
            line=dict(color="gray", width=1),
        )
    fig.add_trace(go.Scatter(
        x=df["theta"], y=df["param"],
        mode="markers",
        marker=dict(color=colors, size=8),
        name="θ",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="black", line_width=1)
    fig.update_layout(
        title="ERGM Coefficients (EstimNetDirected)<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "Red=positive, Blue=negative; bars=95% CI</span>",
        showlegend=False,
    )
    fig.update_xaxes(title_text="θ estimate")
    fig.update_yaxes(title_text="Parameter", automargin=True)
    out_path = out_dir / "priority3_ergm_coefs.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "ERGM Coefficients (EstimNetDirected)",
              "Forest plot of ERGM parameter estimates with 95% CIs.")
    print("  [P3] ergm_coefs done")
    return True


# ===========================================================================
# 優先度 4: Gemini Yes ペアとの突合
# ===========================================================================

def _load_similarity_results(sim_dir: Path) -> pd.DataFrame | None:
    """similarity_results/ 以下の .jsonl を統合して DataFrame を返す。"""
    records = []
    for p in sorted(sim_dir.glob("*.jsonl")):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    if not records:
        return None
    return pd.DataFrame(records)


def _normalize_sim_cols(df: pd.DataFrame) -> pd.DataFrame:
    """JSONL の列名を統一する（source/target → id_a/id_b、similarity 正規化）。"""
    col_map = {}
    for col in df.columns:
        lc = col.lower()
        if lc in ("source", "patent_a", "id_a", "src", "patent1"):
            col_map[col] = "id_a"
        elif lc in ("target", "patent_b", "id_b", "tgt", "patent2"):
            col_map[col] = "id_b"
        elif lc in ("similarity", "label", "result", "similar"):
            col_map[col] = "similarity"
    return df.rename(columns=col_map)


def priority4_gemini_vs_class(
    patent_cache: dict | None,
    sim_dir: Path,
    out_dir: Path,
) -> bool:
    """
    Gemini Yes/No のクラス分布比較。
    patent_cache (_patent_attr_cache.pkl) から直接クラス情報を引く。
    """
    sim_df = _load_similarity_results(sim_dir)
    if sim_df is None:
        print("  [P4] similarity_results が見つかりません。スキップします。")
        return False

    sim_df = _normalize_sim_cols(sim_df)

    if "similarity" not in sim_df.columns:
        print(f"  [P4] 'similarity' 列が見つかりません。列: {sim_df.columns.tolist()}")
        return False

    is_yes = sim_df["similarity"].astype(str).str.lower().isin(["yes", "true", "1", "similar"])
    df_yes = sim_df[is_yes]
    df_no  = sim_df[~is_yes]

    if patent_cache is not None and "id_a" in sim_df.columns:
        def _get_primary(pid: str) -> str:
            entry = patent_cache.get(str(pid), {})
            return entry.get("primary_class", "Unknown")

        sim_df["cls_a"] = sim_df["id_a"].map(_get_primary)
        sim_df["same_class"] = sim_df["cls_a"] == sim_df["id_b"].map(_get_primary)

        yes_cls = sim_df[is_yes]["cls_a"].value_counts().reindex(ALL_CLASSES, fill_value=0)
        no_cls  = sim_df[~is_yes]["cls_a"].value_counts().reindex(ALL_CLASSES, fill_value=0)

        fig = go.Figure()
        fig.add_trace(go.Bar(name="Gemini: Yes", x=ALL_CLASSES, y=yes_cls.values))
        fig.add_trace(go.Bar(name="Gemini: No",  x=ALL_CLASSES, y=no_cls.values))
        fig.update_layout(
            barmode="group",
            title="Gemini Similarity by D-class<br>"
                  "<span style='font-size:14px;font-weight:normal;'>"
                  "Yes/No distribution across USPTO design classes</span>",
            legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="center", x=0.5),
        )
        fig.update_xaxes(title_text="D-class")
        fig.update_yaxes(title_text="Pair count")
        out_path = out_dir / "priority4_gemini_vs_class.png"
        fig.write_image(str(out_path))
        save_meta(out_path, "Gemini Similarity Judgment by D-class",
                  "Grouped bar chart comparing Yes/No Gemini judgments across D-classes.")

        same_yes = sim_df[sim_df["same_class"]]["similarity"].astype(str).str.lower().isin(
            ["yes", "true", "1", "similar"]).mean()
        diff_yes = sim_df[~sim_df["same_class"]]["similarity"].astype(str).str.lower().isin(
            ["yes", "true", "1", "similar"]).mean()
        print(
            f"  [P4] same_class Yes率: {same_yes*100:.1f}%  "
            f"diff_class Yes率: {diff_yes*100:.1f}%"
        )
    else:
        print("  [P4] patent_cache が利用できないため、クラス別集計をスキップします。")

    print(f"  [P4] gemini_vs_class done  total_pairs={len(sim_df):,} yes={len(df_yes):,}")
    return True


def priority4_jaccard_vs_sim(
    patent_cache: dict | None,
    sim_dir: Path,
    out_dir: Path,
    jac_path: Path,
    node_list: list[str] | None = None,
) -> bool:
    """
    Jaccard 類似度 vs Gemini 判定（箱ひげ図）。

    node_list: attributes.txt の行順に対応する特許IDのリスト。
               None の場合は patent_cache のソート済みキーを使うが、
               edge list に含まれないノードも含むため不正確になる可能性がある。
    """
    if not jac_path.exists():
        print(f"  [P4] {jac_path.name} が見つかりません。スキップします。")
        return False

    sim_df = _load_similarity_results(sim_dir)
    if sim_df is None:
        print("  [P4] similarity_results が見つかりません。スキップします。")
        return False

    sim_df = _normalize_sim_cols(sim_df)
    if "id_a" not in sim_df.columns or "id_b" not in sim_df.columns:
        print("  [P4] id_a / id_b 列が見つかりません。スキップします。")
        return False

    # ノードID → 行インデックスのマップを構築
    if node_list is not None:
        id_to_row = {pid: i for i, pid in enumerate(node_list)}
    elif patent_cache is not None:
        # patent_cache のソート済みキーを使う（build_ergm_input.py と同じ sorted() を適用）
        print("  [P4] node_list 未指定。patent_cache のソート済みキーで代用します。")
        id_to_row = {pid: i for i, pid in enumerate(sorted(patent_cache.keys()))}
    else:
        print("  [P4] ノード順が不明なため Jaccard 分析をスキップします。")
        print("       --edge-dir を指定するか node_list を渡してください。")
        return False

    print(f"  [P4] Jaccard 行列をメモリマップでロード中: {jac_path}")
    # class_sim_jaccard.npy は build_ergm_input.py が出力した float32 密行列
    N = len(id_to_row)
    jac = np.load(str(jac_path), mmap_mode="r")

    jac_vals, labels = [], []
    sample_limit = 50_000
    for _, row in sim_df.head(sample_limit).iterrows():
        i = id_to_row.get(str(row.get("id_a", "")))
        j = id_to_row.get(str(row.get("id_b", "")))
        if i is None or j is None or i >= jac.shape[0] or j >= jac.shape[1]:
            continue
        jac_vals.append(float(jac[i, j]))
        lbl = str(row.get("similarity", "")).lower()
        labels.append("Yes" if lbl in ("yes", "true", "1", "similar") else "No")

    if not jac_vals:
        print("  [P4] Jaccard マッチングでペアが見つかりません。スキップします。")
        return False

    df_plot = pd.DataFrame({"jaccard": jac_vals, "gemini": labels})

    fig = px.box(
        df_plot, x="gemini", y="jaccard",
        color="gemini",
        title="Jaccard Similarity vs Gemini Judgment<br>"
              "<span style='font-size:14px;font-weight:normal;'>"
              "D-class Jaccard score for Gemini Yes/No pairs</span>",
        points="outliers",
    )
    fig.update_xaxes(title_text="Gemini result")
    fig.update_yaxes(title_text="Jaccard score")
    fig.update_layout(showlegend=False)
    out_path = out_dir / "priority4_jaccard_vs_sim.png"
    fig.write_image(str(out_path))
    save_meta(out_path, "Jaccard Similarity vs Gemini Judgment",
              "Boxplot comparing D-class Jaccard scores between Gemini Yes and No pairs.")
    print(f"  [P4] jaccard_vs_sim done  matched_pairs={len(jac_vals):,}")
    return True


# ===========================================================================
# 分析サマリ CSV
# ===========================================================================

def save_analysis_summary(summary: dict, out_dir: Path) -> None:
    rows = [{"metric": k, "value": v} for k, v in summary.items()]
    pd.DataFrame(rows).to_csv(out_dir / "analysis_summary.csv", index=False)
    print(f"  [Summary] {out_dir / 'analysis_summary.csv'}")


# ===========================================================================
# メイン
# ===========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="USPTO 意匠特許 ERGM 分析スクリプト（優先度 1–4）"
    )
    parser.add_argument(
        "--ergm-dir", default="ergm_input",
        help="build_ergm_input.py の出力ディレクトリ (default: ergm_input)",
    )
    parser.add_argument(
        "--sim-dir", default="/mnt/eightthdd/uspto/similarity_results",
        help="Gemini 類似判定 jsonl のディレクトリ "
             "(default: /mnt/eightthdd/uspto/similarity_results)",
    )
    parser.add_argument(
        "--out-dir", default="output",
        help="グラフ・CSV の出力先 (default: output)",
    )
    parser.add_argument(
        "--skip-p3", action="store_true",
        help="優先度3（ERGM係数可視化）をスキップ",
    )
    parser.add_argument(
        "--skip-p4", action="store_true",
        help="優先度4（Gemini突合）をスキップ",
    )
    args = parser.parse_args()

    ergm_dir = Path(args.ergm_dir)
    sim_dir  = Path(args.sim_dir)
    out_dir  = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    attr_path = ergm_dir / "attributes.txt"
    arc_path  = ergm_dir / "arc_list.txt"
    jac_path  = ergm_dir / "class_sim_jaccard.npy"

    if not attr_path.exists():
        print(f"エラー: {attr_path} が見つかりません。", file=sys.stderr)
        sys.exit(1)
    if not arc_path.exists():
        print(f"エラー: {arc_path} が見つかりません。", file=sys.stderr)
        sys.exit(1)

    print(f"ロード中: {attr_path}")
    attrs = pd.read_csv(attr_path, sep="\t", low_memory=False)
    print(f"  ノード数: {len(attrs):,}")

    print(f"ロード中: {arc_path}")
    arcs = load_arc_list(arc_path)
    print(f"  アーク数: {len(arcs):,}")

    patent_cache = _load_patent_cache(ergm_dir)
    if patent_cache:
        print(f"  patent_cache ロード済み: {len(patent_cache):,} 件")
    else:
        print("  patent_cache なし（優先度4のクラス別集計は制限されます）")

    # ---------- 優先度 1 ----------
    print("\n=== 優先度1: クラス分布・ヒートマップ ===")
    priority1_class_distribution(attrs, out_dir)
    priority1_nclasses_hist(attrs, out_dir)
    priority1_date_timeline(attrs, out_dir)
    priority1_cocite_heatmap(attrs, arcs, out_dir)

    # ---------- 優先度 2 ----------
    print("\n=== 優先度2: 記述統計 ===")
    p2 = priority2_descriptive(attrs, arcs, out_dir)
    priority2_degree_dist(p2["deg"], out_dir)

    # ---------- 優先度 3 ----------
    if not args.skip_p3:
        print("\n=== 優先度3: ERGM 係数可視化 ===")
        priority3_ergm_coefs(ergm_dir, out_dir)

    # ---------- 優先度 4 ----------
    if not args.skip_p4:
        if sim_dir.exists():
            print("\n=== 優先度4: Gemini 突合 ===")
            priority4_gemini_vs_class(patent_cache, sim_dir, out_dir)
            priority4_jaccard_vs_sim(patent_cache, sim_dir, out_dir, jac_path)
        else:
            print(f"\n=== 優先度4: {sim_dir} が存在しません。スキップします。===")

    # ---------- サマリ ----------
    summary = p2["summary"]
    save_analysis_summary(summary, out_dir)

    print(f"\n完了 → {out_dir}/")
    print(f"  ノード数:        {summary['n_nodes']:,}")
    print(f"  エッジ数:        {summary['n_edges']:,}")
    print(f"  密度:            {summary['density']:.3e}")
    print(f"  平均次数:        {summary['mean_degree']:.2f}")
    print(f"  多クラス特許率:  {summary['pct_multi_class']:.1f}%")


if __name__ == "__main__":
    # 使い方:
    #   python analyze_ergm.py                                         # デフォルト
    #   python analyze_ergm.py --ergm-dir ./ergm_input                 # 出力先を指定
    #   python analyze_ergm.py --sim-dir ./sim_results                 # Gemini 結果先を指定
    #   python analyze_ergm.py --out-dir ./my_output                   # 出力先を指定
    #   python analyze_ergm.py --skip-p3                               # ERGM 係数をスキップ
    #   python analyze_ergm.py --skip-p4                               # Gemini 突合をスキップ
    main()
