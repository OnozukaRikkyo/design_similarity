# 多クラス意匠特許の被引用行動分析 (`analysis/fig_interdisciplinarity.py`)

USPTO 意匠特許共引用ネットワークにおける **学際性（Interdisciplinarity）** の効果を定量化するスクリプト。
複数の Locarno 意匠分類（D-class）を持つ特許（多クラス特許）が、単一クラス特許と比べて
前方引用数（`citations_found`）において有意差があるかを NB2 回帰と Mann-Whitney U 検定で検証する。

---

## スクリプト

```
/home/sonozuka/design_similarity/analysis/fig_interdisciplinarity.py
```

---

## 入出力

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/data/{year}.csv` | CSV（特許属性: `id`, `class`, `date`）|
| 入力 | `/mnt/eightthdd/uspto/json/{year}.json` | JSON（`citations_found` フィールド）|
| 出力 | `analysis/output/fig_interdisciplinarity.png` | 200 DPI PNG（4 パネル図）|
| 出力 | `analysis/output/nb2_estimates.csv` | NB2 係数推定値 CSV |
| 出力 | `analysis/output/nb2_dispersion.csv` | NB2 分散パラメータ α の推定値 CSV |

利用可能な年：
- CSV: 2007–2022（`data/{year}.csv`）
- JSON: 2007–2018（`json/{year}.json`）
- 結合後のサンプル: 2007–2018（inner join）

---

## データ前処理

### patent_key の正規化

`data/{year}.csv` の `id` 列と `json/{year}.json` のキーはフォーマットが異なる。

| ソース | フォーマット例 | 変換 |
|--------|--------------|------|
| CSV `id` | `D0543613` | `str.replace(r'^D0+', 'D', regex=True)` |
| JSON key | `D543613` | そのまま使用 |

正規化後の共通キー: `patent_key = "D543613"`

### D-class パーサ `_extract_all_classes()`

`build_ergm_input.py` の `_extract_all_classes()` と**完全に同一のロジック**を使用する。

| 入力形式 | 例 | 出力 |
|----------|-----|------|
| カンマ区切り複数クラス | `"D14422,D6100"` | `{"D14", "D6"}` |
| スペース入り1桁 | `"D 9"` | `{"D9"}` |
| 2桁クラス (D10-D34, D99) | `"D23366"` | `{"D23"}` |
| 1桁クラス (D1-D9) | `"D6100"` | `{"D6"}` |

優先ルール: 先頭2桁が D10–D34 または D99 の範囲なら2桁クラス、それ以外は先頭1桁クラス。

### 変数定義

| 変数名 | 型 | 定義 |
|--------|-----|------|
| `citations_found` | int ≥ 0 | 当該特許を前方引用したアプリケーション数（JSON から取得）|
| `n_classes` | int ≥ 0 | `_extract_all_classes()` が返すセットの要素数 |
| `is_multi` | bool | `n_classes >= 2`（多クラス特許フラグ）|
| `filing_year` | int | `date` 列先頭 4 桁（YYYYMMDD → YYYY）|
| `year_cs` | float | `(filing_year − mean) / std`（標準化出願年）|

`n_classes == 0`（クラス情報なし）の特許は分析から除外する。

---

## 実績データ規模（2007–2018 全年）

| 量 | 値 |
|----|---|
| 結合前 CSV レコード数 | 434,498 |
| 結合前 JSON レコード数 | 137,406 |
| 結合後（n_classes ≥ 1）| **137,398** |
| 単一クラス（n_classes = 1）| 128,847（93.8%）|
| 多クラス（n_classes ≥ 2）| 8,551（6.2%）|
| 出願年範囲 | 2007–2018 |

---

## 統計手法

### Mann-Whitney U 検定

正規性を仮定しないノンパラメトリック検定。単一クラス vs 多クラスの `citations_found` 分布を比較する。

```python
scipy.stats.mannwhitneyu(s_single, s_multi, alternative="two-sided")
```

**実測結果**: p = 0.029（5% 水準で有意）

### NB2 回帰（負の二項回帰）

カウントデータ（`citations_found`）の過分散に対応するため、Poisson ではなく NB2 を使用する。

**モデル式**:

```
citations_found_i ~ NB2(μ_i, α)

log(μ_i) = β_0 + β_1 · is_multi_i + β_2 · year_cs_i
```

**NB2 の PMF**:

```
P(Y = y | μ, α) = Γ(y + r) / (Γ(r) · Γ(y+1)) · (r/(r+μ))^r · (μ/(r+μ))^y
                  ただし r = 1/α
```

- α > 0: 過分散パラメータ（α = 0 で Poisson に退化）
- E[Y] = μ,  Var[Y] = μ + α·μ²

**推定方法**:

| 工程 | 実装 |
|------|------|
| 最大尤度推定 | `scipy.optimize.minimize` (L-BFGS-B) |
| 初期値 | β_0 = log(ȳ),  その他 0,  log_α = 0 |
| 標準誤差 | 数値ヘッセ行列（中央差分 4次精度）の逆行列の対角 |
| 最適化パラメータ | `[β_0, β_1, β_2, log_α]`（計 4 変数）|

数値ヘッセ行列の実装 (`_numerical_hessian`):

```python
H[i,j] = (f(x+ε_i+ε_j) - f(x+ε_i-ε_j) - f(x-ε_i+ε_j) + f(x-ε_i-ε_j)) / (4ε²)
```

4 変数 × 対称性活用 → 40 回の関数評価で完結。外部ライブラリ（statsmodels, numdifftools）不要。

---

## NB2 推定結果（実測値）

| パラメータ | β̂ | SE | 95% CI | IRR = exp(β̂) | z 統計量 | 有意性 |
|-----------|-----|-----|--------|--------------|---------|--------|
| Intercept (β₀) | +1.198 | 0.0023 | [1.193, 1.203] | 3.314 | 512.8 | *** |
| `is_multi` (β₁) | +0.019 | 0.0093 | [0.001, 0.037] | 1.019 | 2.02 | * |
| `year_cs` (β₂) | +0.148 | 0.0023 | [0.144, 0.153] | 1.160 | 65.1 | *** |
| α（分散）| 0.398 | — | — | — | — | — |

有意水準: `***` p < 0.001、`**` p < 0.01、`*` p < 0.05

**解釈**:
- `is_multi`（β₁ = +0.019）: 多クラス特許は単一クラスより前方引用数が約 **1.9% 多い**（IRR = 1.019）。効果量は小さいが統計的に有意（p ≈ 0.04）。
- `year_cs`（β₂ = +0.148）: 出願年が 1 標準偏差（≈ 3.2 年）新しいほど引用数が約 **16% 多い**（IRR = 1.160）。Receiver Recency 効果と整合。
- α = 0.398: Poisson に比べ過分散あり（NB2 の採用を正当化）。

---

## 出力図の詳細（4 パネル構成）

### (a) NB2 係数フォレストプロット

| 視覚要素 | 内容 |
|---------|------|
| 横軸 | 係数 β（log-rate ratio）|
| エラーバー | 95% CI（1.96 × SE）|
| 点 | 正方形マーカー（`fmt="s"`）|
| 縦破線 | β = 0 の基準線 |
| 上部テキスト | `β=+0.019 *`（多クラス）、`β=+0.148 ***`（出願年）|

### (b) Incidence Rate Ratios（IRR）棒グラフ

| 要素 | 内容 |
|------|------|
| Single（ref.）| IRR = 1.000（基準）|
| Multi-class | IRR = exp(β₁) = 1.019 |
| Year +1σ | IRR = exp(β₂) = 1.160 |
| エラーバー | 95% CI の非対称区間（`exp(β ± 1.96·SE)`）|
| 横破線 | IRR = 1.0 の基準線 |

### (c) NB2 理論 PMF

| 要素 | 内容 |
|------|------|
| 横軸 | 前方引用数 k（1–17）|
| 縦軸 | P(K = k)（確率質量）|
| 単一クラス | μ_s = exp(β₀) |
| 多クラス | μ_m = exp(β₀ + β₁) |
| 実装 | `scipy.stats.nbinom.pmf(k, r, r/(r+μ))`（r = 1/α）|

2 本の曲線の差は β₁ = +0.019 の微小効果を可視化する。

### (d) サンプル構成

| 要素 | 内容 |
|------|------|
| 棒グラフ | Single-class: 128,847件（93.8%）/ Multi-class: 8,551件（6.2%）|
| テキストボックス | N・α・IRR・Mann-Whitney p 値のサマリ |

---

## 実行方法

```bash
# デフォルト実行
python analysis/fig_interdisciplinarity.py

# パスを明示指定
python analysis/fig_interdisciplinarity.py \
    --data-dir /mnt/eightthdd/uspto/data \
    --json-dir /mnt/eightthdd/uspto/json \
    --out-dir  analysis/output \
    --filename fig_interdisciplinarity.png
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--data-dir` | `/mnt/eightthdd/uspto/data` | `{year}.csv` のディレクトリ |
| `--json-dir` | `/mnt/eightthdd/uspto/json` | `{year}.json` のディレクトリ |
| `--out-dir` | `analysis/output` | PNG / CSV の出力先 |
| `--filename` | `fig_interdisciplinarity.png` | 出力 PNG のファイル名 |

---

## 関数一覧

| 関数 | 役割 |
|------|------|
| `_extract_all_classes(class_str)` | `class` フィールドから全 D-class コードをセットで返す |
| `_load_csv_data(data_dir)` | `data/*.csv` を全年ロード（`id`, `class`, `date`）|
| `_load_json_data(json_dir)` | `json/*.json` を全年ロード（`patent_key`, `citations_found`）|
| `build_analysis_df(data_dir, json_dir)` | CSV × JSON を inner join して分析 DataFrame を返す |
| `_nb2_negloglik(params, y, X)` | NB2 負対数尤度（最適化の目的関数）|
| `_numerical_hessian(f, x, eps)` | 中央差分によるヘッセ行列（標準誤差計算用）|
| `fit_nb2(y, X)` | NB2 MLE — `(beta, se_beta, log_alpha, se_log_alpha, converged)` を返す |
| `_sig_stars(z)` | z 値から有意性星印文字列を返す |
| `_draw_panel_a` | (a) フォレストプロット描画 |
| `_draw_panel_b` | (b) IRR 棒グラフ描画 |
| `_draw_panel_c` | (c) NB2 理論 PMF 描画 |
| `_draw_panel_d` | (d) サンプル構成棒グラフ描画 |
| `make_figure(out_path, data_dir, json_dir)` | データ読み込み → 統計検定 → NB2 推定 → 4パネル図生成 |

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `build_edge_list.py`（STEP 1、間接的）| `analysis/fig_interdisciplinarity.py` | 論文・発表スライドへの組み込み |
| `/mnt/eightthdd/uspto/data/*.csv` | → `n_classes`, `filing_year` の取得 | — |
| `/mnt/eightthdd/uspto/json/*.json` | → `citations_found` の取得 | — |

`ergm_input/` や共引用エッジリストには依存せず、`data/` と `json/` のみで独立実行できる。

---

## `build_ergm_input.py` との分類コード取得の比較

| 項目 | 本スクリプト | `build_ergm_input.py` |
|------|------------|----------------------|
| 対象 | 全特許（CSV × JSON 結合）| 共引用ネットワーク上のノードのみ |
| クラス取得関数 | `_extract_all_classes()`（コピー）| `_extract_all_classes()`（本体）|
| 出力 | `is_multi`（bool）| `n_classes`（int）・`IsClass_D*`（binary flags）|
| 結合キー | `patent_key = D543613`（先頭ゼロ除去）| `id` を直接使用 |
| 追加変数 | `citations_found`（JSON）| `date`, `primary_class` 等（CSVのみ）|

両スクリプトの `n_classes` は同一のパーサを使うため一致する。ただし対象集合が異なる点に注意
（本スクリプト: N=137,398、`build_ergm_input.py`: N=69,202 ≒ 共引用ネットワーク上のノード）。
