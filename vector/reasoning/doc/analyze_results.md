# 統計分析・仮説検定 (`analyze_results.py`)

`merge_results.py`（Step 5）が生成した `unified_results.csv` を読み込み、
5 つの事前登録仮説（H_NLP1–H_NLP5）を統計検定し、5 枚の図を生成する。

処理順序の全体像は [pipeline.md](pipeline.md) を参照。

---

## スクリプト

```
vector/reasoning/analyze_results.py
```

---

## 出力ファイル

```
vector/output/{CLASS}/{sim_func}/reasoning/analysis/
  analysis_summary.txt        — 仮説検定結果テーブル + 記述統計
  fig_pms_vs_similarity.png   — Figure 1: PMS vs コサイン類似度散布図
  fig_pms_distribution.png    — Figure 2: 判定グループ別 PMS 分布
  fig_m5_vs_pms.png           — Figure 3: M5 score vs PMS 散布図
  fig_baseline_vs_judgment.png — Figure 4: LLM 判定 vs Baseline B 棒グラフ
  fig_exact_vs_nonexact_pms.png — Figure 5: Exact / Non-exact 別 PMS バイオリン図
```

---

## 事前登録仮説

### H_NLP1: PMS と cos 類似度の正相関

**仮説**: PMS とコサイン類似度の間に正の Spearman 相関がある（ρ > 0）。

**検定**: Spearman ρ（双側）

| 出力列 | 意味 |
|--------|------|
| `rho` | Spearman ρ |
| `p_value` | p 値 |
| `result` | `SUPPORT` (ρ > 0 かつ p < 0.05) / `NOT_SUPPORT` |

**解釈**: 支持されれば、ラショナルベース推定量（PMS）と画像ベース推定量（cos）が
同じ方向の情報を捉えていることを示す。

---

### H_NLP2: Exact match 群の PMS > Non-exact 群

**仮説**: `reason` に完全一致キーワード（identical / exact / same）を含む群の PMS は、
含まない群より高い（片側検定）。

**検定**: 独立 t 検定（`alternative="greater"`）

| 出力列 | 意味 |
|--------|------|
| `mean_exact` | Exact match 群の PMS 平均 |
| `mean_nonexact` | Non-exact 群の PMS 平均 |
| `t_stat` | t 統計量 |
| `p_value` | p 値 |

**解釈**: 支持されれば、M1/M2/M3 が exact/non-exact の語義的差異を
数値的に区別できていることを示す。

---

### H_NLP3: M5 score と PMS の正相関

**仮説**: M5 score（視覚的忠実性）と PMS の間に正の Spearman 相関がある（ρ > 0）。

**検定**: Spearman ρ（双側）

**解釈**: 支持されれば、ラショナルが視覚的に正確なほど PMS も高い傾向があり、
ラショナルの品質と推定スコアの整合性を示す。M5 データが存在しない場合は SKIP。

---

### H_NLP4: Baseline B の判定一致率 > 0.7

**仮説**: VLM-direct baseline B の判定が LLM 元判定（`judgment`）と 70% 以上一致する。

**検定**: 片側 z 検定（帰無仮説: 一致率 = 0.7）

| 出力列 | 意味 |
|--------|------|
| `agreement_rate` | 実測一致率 |
| `z_stat` | z 統計量 |
| `p_value` | p 値 |

**解釈**: 支持されれば、ラショナルなしの画像判定も LLM 判定と高く一致し、
ラショナルの追加が大きな逆転をもたらさないことを示す。
Baseline B データが存在しない場合は SKIP。

---

### H_NLP5: PMS の AUC > cos 類似度の AUC

**仮説**: LLM 元判定（Yes/No）の 2 値予測において、
PMS の ROC-AUC がコサイン類似度の ROC-AUC より高い。

**検定**: Steiger (1980) の Z 検定（2 つの依存相関係数を比較）

```
ρ1 = Spearman(PMS, judgment)
ρ2 = Spearman(similarity, judgment)
ρ12 = Spearman(PMS, similarity)

Steiger Z = (Fisher(ρ1) - Fisher(ρ2)) / SE
```

| 出力列 | 意味 |
|--------|------|
| `auc_pms` | PMS の ROC-AUC |
| `auc_similarity` | cos 類似度の ROC-AUC |
| `steiger_z` | Steiger Z 統計量 |
| `p_value` | p 値（片側）|

**解釈**: 支持されれば、ラショナルベース PMS はコサイン類似度より
人間の Yes/No 判定を良く予測することを示す。

---

## 図の詳細

### Figure 1: PMS vs コサイン類似度

**横軸**: コサイン類似度  
**縦軸**: PMS  
**色分け**: Yes（青）/ No（赤）/ Unknown（グレー）

Exact match 群が左上（高類似度・高 PMS）に集中するか、
判定グループで分離が起きているかを視覚的に確認する。

### Figure 2: 判定グループ別 PMS 分布

**横軸**: PMS  
**縦軸**: 確率密度（density=True）  
**系列**: Yes（青）/ No（赤）

H_NLP1/2 の効果量を直感的に把握する。

### Figure 3: M5 score vs PMS

**横軸**: M5 score（視覚的忠実性）  
**縦軸**: PMS  

M5 データが存在しない場合はスキップ（メッセージをログ出力）。

### Figure 4: LLM 判定 vs Baseline B

**横軸**: LLM 元判定（Yes / No）  
**縦軸**: 件数  
**色分け**: Baseline B 判定（Yes / No）

H_NLP4 の一致・不一致パターンを確認する。

### Figure 5: Exact / Non-exact 別 PMS（バイオリン図）

**横軸**: Exact match / Non-exact similar  
**縦軸**: PMS  

H_NLP2 の群間差の分布形状を確認する。

---

## 図のスタイル

PRL（Physical Review Letters）シングルカラム準拠:

| 設定 | 値 |
|------|-----|
| フォント | Times New Roman / serif |
| フォントサイズ | 9pt（ラベル 10pt）|
| 列幅 | 3.37 inch |
| DPI | 300 |
| 目盛り方向 | 内向き（全 4 辺）|

---

## 前処理ロジック

`preprocess()` が `unified_results.csv` に以下の列を追加する:

| 追加列 | 計算方法 |
|--------|---------|
| `judgment_bin` | "Yes" → 1 / "No" → 0 / その他 → None |
| `is_exact` | reason テキストに `identical` / `exact` / `same` が含まれるか（bool）|

---

## 固定パス

| 種別 | パス |
|------|------|
| 入力 CSV | `vector/output/D18/cosine_numpy/reasoning/unified_results.csv` |
| 出力ディレクトリ | `vector/output/D18/cosine_numpy/reasoning/analysis/` |

## 実行方法

```bash
cd vector/reasoning
python3 analyze_results.py
```

引数は不要。`unified_results.csv` が存在しない場合はエラーメッセージを出力して終了する。
先に `merge_results.py` を実行すること。

matplotlib がインストールされていない場合は図のみスキップし、
統計検定と `analysis_summary.txt` は生成される。

tabulate がインストールされていない場合は Markdown 表を
パイプ区切りの plain text で代替出力する。

---

## 前後の処理との関係

```
unified_results.csv  →  analyze_results.py  →  analysis_summary.txt
                                             →  fig_*.png（5 枚）
```

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `merge_results.py`（Step 5）| `analyze_results.py`（Step 6）| 論文図・仮説検定 |