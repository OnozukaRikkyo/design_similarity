#!/usr/bin/env python3
"""
analysis/fig_interdisciplinarity.py
=====================================
USPTO 意匠特許における多クラス特許の被引用行動分析
(NB2 Negative Binomial Regression + Mann-Whitney U 検定)

入力:
    /mnt/eightthdd/uspto/data/{year}.csv   特許属性 (id, class, date)
    /mnt/eightthdd/uspto/json/{year}.json  引用データ (citations_found)

Panel (a): NB2 係数フォレストプロット (is_multi, year_cs)
Panel (b): 発生率比 (IRR = exp(β)) の棒グラフ
Panel (c): NB2 理論 PMF（single vs multi-class）
Panel (d): サンプル構成（特許数 + 統計サマリ）

Usage:
    python analysis/fig_interdisciplinarity.py
    python analysis/fig_interdisciplinarity.py \\
        --data-dir /mnt/eightthdd/uspto/data \\
        --json-dir /mnt/eightthdd/uspto/json \\
        --out-dir  analysis/output
"""

import argparse
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd
from scipy import special, optimize, stats
from scipy.stats import nbinom

# ─────────────────────────────────────────────────────────────────────
# デフォルトパス
# ─────────────────────────────────────────────────────────────────────
DATA_DIR = Path("/mnt/eightthdd/uspto/data")
JSON_DIR = Path("/mnt/eightthdd/uspto/json")
OUT_DIR  = Path("analysis/output")



# ─────────────────────────────────────────────────────────────────────
# D-class パーサ（build_ergm_input.py の _extract_all_classes と同一ロジック）
# ─────────────────────────────────────────────────────────────────────
def _extract_all_classes(class_str: str) -> set[str]:
    """class フィールドから全 D-class コードを抽出する。

    build_ergm_input.py の _extract_all_classes() と完全に同一のロジック。
    - カンマ区切りで複数クラスを分割
    - "D 9" 形式（スペース入り1桁）を処理
    - 2桁クラス (D10-D34, D99) を優先、次いで1桁 (D1-D9)
    """
    if not class_str or class_str.strip() == "":
        return set()
    result: set[str] = set()
    for part in class_str.split(","):
        part = part.strip()
        m = re.match(r"D (\d)", part)
        if m:
            result.add(f"D{m.group(1)}")
            continue
        m = re.match(r"D(\d+)", part)
        if not m:
            continue
        digits = m.group(1)
        if len(digits) >= 2:
            two = int(digits[:2])
            if (10 <= two <= 34) or two == 99:
                result.add(f"D{two}")
                continue
        one = int(digits[:1])
        if 1 <= one <= 9:
            result.add(f"D{one}")
    return result


# ─────────────────────────────────────────────────────────────────────
# データ読み込み
# ─────────────────────────────────────────────────────────────────────
def _load_csv_data(data_dir: Path) -> pd.DataFrame:
    """data/{year}.csv から id + class + date を全年分ロードする。"""
    dfs = []
    for p in sorted(data_dir.glob("*.csv")):
        try:
            dfs.append(pd.read_csv(
                p, usecols=["id", "class", "date"],
                dtype=str, on_bad_lines="skip"))
        except Exception as e:
            print(f"  [warn] CSV {p.name}: {e}")
    if not dfs:
        return pd.DataFrame(columns=["id", "class", "date"])
    return pd.concat(dfs, ignore_index=True).dropna(subset=["id"])


def _load_json_data(json_dir: Path) -> pd.DataFrame:
    """json/{year}.json から patent_key + citations_found を全年分ロードする。

    JSON キー形式: "D543613" (先頭ゼロなし)
    citations_found: int (forward citation count)
    """
    rows = []
    for p in sorted(json_dir.glob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            for key, val in data.items():
                if isinstance(val, dict) and "citations_found" in val:
                    rows.append({
                        "patent_key":    key,
                        "citations_found": int(val["citations_found"]),
                    })
        except Exception as e:
            print(f"  [warn] JSON {p.name}: {e}")
    if not rows:
        return pd.DataFrame(columns=["patent_key", "citations_found"])
    return pd.DataFrame(rows)


def build_analysis_df(data_dir: Path, json_dir: Path) -> pd.DataFrame:
    """CSV と JSON を patent_key で内部結合して分析 DataFrame を返す。

    正規化: CSV の id "D0543613" → patent_key "D543613"
            （先頭の D に続くゼロを除去）
    """
    print("Loading CSV data ...")
    df_csv = _load_csv_data(data_dir)
    print(f"  {len(df_csv):,} records from {data_dir}")

    # patent_key 正規化: D0543613 → D543613
    df_csv["patent_key"] = (
        df_csv["id"].str.strip()
        .str.replace(r"^D0+", "D", regex=True))

    # n_classes: _extract_all_classes() でクラスセットを取得して個数を数える
    df_csv["n_classes"] = (
        df_csv["class"].fillna("").apply(
            lambda s: len(_extract_all_classes(s))))

    # 出願年: date 列は YYYYMMDD 形式
    df_csv["filing_year"] = (
        df_csv["date"].str.strip().str[:4]
        .where(df_csv["date"].str.strip().str[:4].str.isdigit())
        .astype("Int64"))

    print("Loading JSON data ...")
    df_json = _load_json_data(json_dir)
    print(f"  {len(df_json):,} records from {json_dir}")

    # 内部結合
    df = df_csv.merge(df_json, on="patent_key", how="inner")
    df = df.dropna(subset=["filing_year"]).copy()
    df["filing_year"] = df["filing_year"].astype(int)

    print(f"  {len(df):,} matched patents  "
          f"(year range {df['filing_year'].min()}--{df['filing_year'].max()})")
    return df


# ─────────────────────────────────────────────────────────────────────
# NB2 回帰（scipy のみ使用）
# ─────────────────────────────────────────────────────────────────────
def _nb2_negloglik(params: np.ndarray, y: np.ndarray, X: np.ndarray) -> float:
    """NB2 負対数尤度。

    params = [β_0, β_1, ..., β_{k-1}, log_α]
    μ_i = exp(X_i @ β),  r = 1/α = exp(-log_α)
    log p(y_i) = lgamma(y_i + r) - lgamma(r) - lgamma(y_i+1)
                 + r*log(r/(r+μ_i)) + y_i*log(μ_i/(r+μ_i))
    """
    k = X.shape[1]
    beta     = params[:k]
    log_alpha = params[k]
    alpha    = np.exp(np.clip(log_alpha, -10, 5))

    mu = np.exp(np.clip(X @ beta, -30, 30))
    r  = 1.0 / (alpha + 1e-12)

    ll = (special.gammaln(y + r)
          - special.gammaln(r)
          - special.gammaln(y + 1)
          + r * np.log(r / (r + mu + 1e-12))
          + y * np.log(mu / (r + mu + 1e-12)))
    return -float(ll.sum())


def _numerical_hessian(f, x: np.ndarray, eps: float = 1e-4) -> np.ndarray:
    """中央差分による数値ヘッセ行列（4 変数で 40 回の関数評価）。"""
    n = len(x)
    H = np.zeros((n, n))
    for i in range(n):
        for j in range(i, n):
            xpp = x.copy(); xpp[i] += eps; xpp[j] += eps
            xpm = x.copy(); xpm[i] += eps; xpm[j] -= eps
            xmp = x.copy(); xmp[i] -= eps; xmp[j] += eps
            xmm = x.copy(); xmm[i] -= eps; xmm[j] -= eps
            H[i, j] = (f(xpp) - f(xpm) - f(xmp) + f(xmm)) / (4 * eps ** 2)
            H[j, i] = H[i, j]
    return H


def fit_nb2(y: np.ndarray, X: np.ndarray):
    """NB2 回帰の MLE。

    Parameters
    ----------
    y : (n,) 非負整数（citations_found）
    X : (n, k) 計画行列（切片列を含む）

    Returns
    -------
    beta     : (k,) 係数推定値
    se_beta  : (k,) 標準誤差
    log_alpha : float  log(分散膨張パラメータ)
    se_log_alpha : float
    converged    : bool
    """
    k = X.shape[1]
    beta0 = np.zeros(k)
    beta0[0] = np.log(max(y.mean(), 1e-6))
    params0 = np.append(beta0, 0.0)   # log_alpha = 0 → α=1

    result = optimize.minimize(
        _nb2_negloglik, params0, args=(y, X),
        method="L-BFGS-B",
        options={"maxiter": 2000, "ftol": 1e-12, "gtol": 1e-8})

    params_hat = result.x

    # 数値ヘッセ行列から標準誤差を計算
    try:
        H = _numerical_hessian(
            lambda p: _nb2_negloglik(p, y, X), params_hat, eps=1e-4)
        cov = np.linalg.inv(H)
        diag = np.diag(cov)
        se = np.where(diag > 0, np.sqrt(diag), np.nan)
    except np.linalg.LinAlgError:
        se = np.full(len(params_hat), np.nan)

    beta      = params_hat[:k]
    se_beta   = se[:k]
    log_alpha = params_hat[k]
    se_log_alpha = se[k]

    return beta, se_beta, log_alpha, se_log_alpha, result.success


# ─────────────────────────────────────────────────────────────────────
# 4 パネル図（NB2 結果の可視化）
# ─────────────────────────────────────────────────────────────────────
def _sig_stars(z: float) -> str:
    if z > 2.576:  return "***"
    if z > 1.960:  return "**"
    if z > 1.645:  return "*"
    return "n.s."


def _draw_panel_a(ax: plt.Axes,
                  beta: np.ndarray, se: np.ndarray,
                  C_red: str, C_blue: str) -> None:
    """(a) NB2 係数フォレストプロット（is_multi, year_cs）。"""
    betas  = [beta[1], beta[2]]
    ses    = [se[1],   se[2]]
    colors = [C_red,   C_blue]
    labels = ["Multi-class\n(is_multi)", "Year (std)\n(year_cs)"]

    for yi, (b, s, col) in enumerate(zip(betas, ses, colors)):
        ax.errorbar(b, yi, xerr=1.96 * s, fmt="s", color=col,
                    markersize=8, capsize=5, lw=2)
        stars = _sig_stars(abs(b) / max(s, 1e-12))
        ax.text(b, yi + 0.28, f"β={b:+.3f} {stars}",
                color=col, fontsize=9.5, ha="center")

    ax.axvline(0, color="#333", lw=1.5, ls="--")
    ax.set_yticks([0, 1])
    ax.set_yticklabels(labels, fontsize=11)
    ax.set_ylim(-0.6, 1.7)
    ax.set_xlabel("Coefficient β", fontsize=11)
    ax.set_title("(a) NB2 Coefficients", fontweight="bold")
    ax.grid(axis="x", color="#E0E0E0")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)


def _draw_panel_b(ax: plt.Axes,
                  beta: np.ndarray, se: np.ndarray,
                  C_red: str, C_blue: str, C_gray: str) -> None:
    """(b) 発生率比 (IRR = exp(β)) の棒グラフ。"""
    irr_vals   = [1.0, np.exp(beta[1]), np.exp(beta[2])]
    irr_ep     = [0.0, (np.exp(beta[1] + 1.96 * se[1]) - irr_vals[1]),
                       (np.exp(beta[2] + 1.96 * se[2]) - irr_vals[2])]
    irr_em     = [0.0, (irr_vals[1] - np.exp(beta[1] - 1.96 * se[1])),
                       (irr_vals[2] - np.exp(beta[2] - 1.96 * se[2]))]
    x_labels   = ["Single\n(ref.)", "Multi-class", "Year +1σ"]
    bar_colors = [C_gray, C_red, C_blue]

    bars = ax.bar(x_labels, irr_vals,
                  color=bar_colors, alpha=0.82, width=0.5)
    ax.errorbar(x_labels, irr_vals,
                yerr=[irr_em, irr_ep],
                fmt="none", color="#333", capsize=5, lw=1.8)
    for bar, v in zip(bars, irr_vals):
        ax.text(bar.get_x() + bar.get_width() / 2, v + 0.002,
                f"{v:.3f}", ha="center", va="bottom",
                fontsize=11, fontweight="bold")

    ax.axhline(1.0, color="#333", lw=1.5, ls="--")
    ax.set_ylabel("IRR", fontsize=11)
    ax.set_ylim(min(0.96, min(irr_vals) * 0.98),
                max(irr_vals) * 1.10)
    ax.set_title("(b) Incidence Rate Ratios", fontweight="bold")
    ax.grid(axis="y", color="#E0E0E0")
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)


def _draw_panel_c(ax: plt.Axes,
                  beta: np.ndarray, alpha: float,
                  C_blue: str, C_red: str) -> None:
    """(c) NB2 理論 PMF（single vs multi-class）。"""
    r    = 1.0 / alpha
    mu_s = np.exp(beta[0])
    mu_m = np.exp(beta[0] + beta[1])
    k    = np.arange(1, 18)

    pmf_s = nbinom.pmf(k, r, r / (r + mu_s))
    pmf_m = nbinom.pmf(k, r, r / (r + mu_m))

    ax.plot(k, pmf_s, "o-",  color=C_blue, lw=2.2, ms=5,
            label="Single-class")
    ax.plot(k, pmf_m, "s--", color=C_red,  lw=2.2, ms=5,
            label="Multi-class")
    ax.set_xlabel("Forward Citations k", fontsize=11)
    ax.set_ylabel("P(K = k)", fontsize=11)
    ax.set_title("(c) Theoretical Distribution (NB2)", fontweight="bold")
    ax.legend(fontsize=10)
    ax.grid(color="#E0E0E0")
    ax.text(k[-4], pmf_s[2] * 1.12, f"μ={mu_s:.2f}",
            color=C_blue, fontsize=9)
    ax.text(k[-4], pmf_m[2] * 0.60, f"μ={mu_m:.2f}",
            color=C_red,  fontsize=9)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)


def _draw_panel_d(ax: plt.Axes,
                  n_total: int, n_single: int, n_multi: int,
                  alpha: float, mann_p: float,
                  beta: np.ndarray, se: np.ndarray,
                  C_blue: str, C_red: str) -> None:
    """(d) サンプル構成 + 統計サマリ。"""
    bars = ax.bar(["Single-class", "Multi-class"],
                  [n_single, n_multi],
                  color=[C_blue, C_red], alpha=0.82, width=0.5)
    for bar, cnt in zip(bars, [n_single, n_multi]):
        ax.text(bar.get_x() + bar.get_width() / 2,
                cnt + n_total * 0.006,
                f"{cnt:,}\n({cnt / n_total * 100:.1f}%)",
                ha="center", va="bottom", fontsize=11, fontweight="bold")

    ax.set_ylabel("Number of Patents", fontsize=11)
    ax.set_ylim(0, n_single * 1.22)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax.set_title("(d) Sample Composition", fontweight="bold")
    ax.grid(axis="y", color="#E0E0E0")

    irr_multi  = np.exp(beta[1])
    z_multi    = abs(beta[1]) / max(se[1], 1e-12)
    stars      = _sig_stars(z_multi)
    mann_stars = _sig_stars(abs(stats.norm.ppf(mann_p / 2)))
    ax.text(0.97, 0.05,
            f"N={n_total:,} | α={alpha:.3f}\n"
            f"IRR={irr_multi:.3f}, p={mann_p:.3f} {stars}\n"
            f"Mann–Whitney p={mann_p:.3f} {mann_stars}",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#CCC"))
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)


# ─────────────────────────────────────────────────────────────────────
# メイン図
# ─────────────────────────────────────────────────────────────────────
def make_figure(out_path: Path, data_dir: Path, json_dir: Path) -> None:
    # ── データ構築 ─────────────────────────────────────────────────
    print("Building analysis dataset ...")
    df = build_analysis_df(data_dir, json_dir)

    df = df[df["n_classes"] >= 1].copy()
    df["is_multi"] = df["n_classes"] >= 2

    n_total  = len(df)
    n_single = int((~df["is_multi"]).sum())
    n_multi  = int( df["is_multi"].sum())
    y_range  = (df["filing_year"].min(), df["filing_year"].max())

    print(f"  N_total={n_total:,}  N_single={n_single:,}  "
          f"N_multi={n_multi:,}  years={y_range[0]}--{y_range[1]}")
    print(f"  multi ratio: {n_multi / n_total * 100:.1f}%")

    # ── Mann-Whitney U 検定 ─────────────────────────────────────────
    s_single = df.loc[~df["is_multi"], "citations_found"].values
    s_multi  = df.loc[ df["is_multi"], "citations_found"].values
    _, mann_p = stats.mannwhitneyu(s_single, s_multi, alternative="two-sided")
    print(f"  Mann-Whitney U: p={mann_p:.4f}")

    # ── NB2 回帰 ──────────────────────────────────────────────────
    print("Fitting NB2 regression ...")
    year_mean = df["filing_year"].mean()
    year_std  = df["filing_year"].std()
    df["year_cs"] = (df["filing_year"] - year_mean) / max(year_std, 1.0)

    y_arr = df["citations_found"].values.astype(np.float64)
    X_arr = np.column_stack([
        np.ones(len(df)),
        df["is_multi"].astype(float).values,
        df["year_cs"].values,
    ])

    beta, se_beta, log_alpha, se_log_alpha, converged = fit_nb2(y_arr, X_arr)
    alpha = np.exp(log_alpha)

    print(f"  β = {beta}")
    print(f"  SE= {se_beta}")
    print(f"  α = {alpha:.4f}  (NB2 dispersion)")
    print(f"  Converged: {converged}")

    # ── 4 パネル図 ────────────────────────────────────────────────
    C_blue = "#1A5276"
    C_red  = "#922B21"
    C_gray = "#626567"

    fig, axes = plt.subplots(2, 2, figsize=(12, 9))
    fig.patch.set_facecolor("white")
    plt.subplots_adjust(hspace=0.42, wspace=0.36)
    ax_a, ax_b, ax_c, ax_d = (
        axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1])

    _draw_panel_a(ax_a, beta, se_beta, C_red, C_blue)
    _draw_panel_b(ax_b, beta, se_beta, C_red, C_blue, C_gray)
    _draw_panel_c(ax_c, beta, alpha,   C_blue, C_red)
    _draw_panel_d(ax_d, n_total, n_single, n_multi,
                  alpha, mann_p, beta, se_beta, C_blue, C_red)

    json_years = sorted(p.stem for p in sorted(json_dir.glob("*.json")))
    yr_str = (f"{json_years[0]}–2018" if json_years
              else "2007–2018")
    fig.suptitle(
        "Does Interdisciplinarity Increase Patent Forward Citations?\n"
        f"NB2  ·  N={n_total:,} US Design Patents ({yr_str})  ·  "
        f"IRR(multi)={np.exp(beta[1]):.3f},  p={mann_p:.3f}",
        fontsize=13, fontweight="bold", y=1.01)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"\n  [Figure] -> {out_path}")

    # ── 推定結果を CSV 保存 ──────────────────────────────────────────
    result_df = pd.DataFrame({
        "parameter": ["intercept", "is_multi", "year_cs"],
        "beta_hat":  beta,
        "se":        se_beta,
        "ci95_lo":   beta - 1.96 * se_beta,
        "ci95_hi":   beta + 1.96 * se_beta,
        "irr":       np.exp(beta),
        "z_stat":    beta / (se_beta + 1e-12),
    })
    csv_path = out_path.parent / "nb2_estimates.csv"
    result_df.to_csv(csv_path, index=False, float_format="%.6f")
    print(f"  [CSV]    -> {csv_path}")

    alpha_df = pd.DataFrame({
        "parameter": ["log_alpha"],
        "value":     [log_alpha],
        "se":        [se_log_alpha],
        "alpha":     [alpha],
    })
    (out_path.parent / "nb2_dispersion.csv").write_text(
        alpha_df.to_csv(index=False, float_format="%.6f"))


# ─────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser(
        description="多クラス意匠特許の被引用行動分析 (NB2 回帰, PRL スタイル)")
    parser.add_argument("--data-dir", default=str(DATA_DIR),
                        help="data/{year}.csv のディレクトリ")
    parser.add_argument("--json-dir", default=str(JSON_DIR),
                        help="json/{year}.json のディレクトリ")
    parser.add_argument("--out-dir",  default=str(OUT_DIR),
                        help="出力先ディレクトリ")
    parser.add_argument("--filename", default="fig_interdisciplinarity.png",
                        help="出力ファイル名")
    args = parser.parse_args()

    out_path = Path(args.out_dir) / args.filename
    make_figure(out_path,
                data_dir=Path(args.data_dir),
                json_dir=Path(args.json_dir))

    print("\nDone.")


if __name__ == "__main__":
    main()
