# 三角形確信度スコアリング

D18 共引用グラフの全 3-clique に対して、cosine 類似度とグラフ幾何のみに基づく 4 種の独立スコアを付与し、その加重和を確信度とする。

LLM の Yes/No 判定は Ground Truth ではなく「検証対象のノイズラベル」である。閾値・Tier 分類は設けず、全三角形のスコアをそのまま出力する。

依拠文献:
- Schubert 2021 — SISAP. arXiv:2107.04071
- Jarvis & Patrick 1973 — IEEE Trans. Computers C-22(11)

---

## 入力データ

`/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl`

| フィールド | 説明 |
|---|---|
| `source`, `target` | 特許 ID（D0XXXXXX 形式） |
| `similarity` | cosine 類似度（画像埋め込み間） |
| `judgment`, `confidence`, `reason` | LLM 出力（スコアリングでは参照しない） |

---

## グラフ構築

エッジ = 同一 USPTO オフィスアクションで共に引用されたペア（共引用、無向）。  
エッジ重み = cosine 類似度のみ。

D18 の規模: **1030 ノード、1530 エッジ、1593 三角形（3-clique）**

---

## Score 1 — Weakest-link similarity

$$S_1 = \min(s_{AB},\ s_{BC},\ s_{AC})$$

三角形 A–B–C の 3 辺の cosine 類似度のうち最小値。鎖の最弱リンクを三角形全体の下限とみなす。

| D18 統計 | 値 |
|---|---|
| min | 0.4265 |
| median | 0.8475 |
| max | 0.9910 |

---

## Score 2 — Angular tightness（Schubert 2021）

$$\theta_{ij} = \arccos(s_{ij})$$

$$S_2 = \max\!\left(0,\ 1 - \frac{\max(\theta_{AB},\, \theta_{BC},\, \theta_{AC})}{\pi/2}\right)$$

3 辺の角距離（arccos）のうち最大のものを $\pi/2$（90°）で割って正規化し 1 から引く。3 点が単位球上で密集しているほど高スコア。$S_2 = 1$ は全辺が完全一致、$S_2 = 0$ は最大角距離が 90° 以上。

| D18 統計 | 値 |
|---|---|
| min | 0.2805 |
| median | 0.6437 |
| max | 0.9146 |

---

## Score 3 — Schubert bound compliance（Schubert 2021）

> **注意**: `wcc_scoring.py` が出力する `score_ext_degree`（外部次数の最小値）とは別のスコアです。
> `triadic_scoring.md` の S3 はフィールド名 `score_bound_compliance`（`triadic_scored.jsonl`）です。

$s_{AB}$ と $s_{BC}$ から cosine 類似度の三角不等式で $s_{AC}$ の理論的下界・上界を計算する。

$$\mathrm{lb} = s_{AB} s_{BC} - \sqrt{(1-s_{AB}^2)(1-s_{BC}^2)}$$

$$\mathrm{ub} = s_{AB} s_{BC} + \sqrt{(1-s_{AB}^2)(1-s_{BC}^2)}$$

$$S_3 = \frac{s_{AC} - \mathrm{lb}}{\mathrm{ub} - \mathrm{lb}}$$

$S_3 = 1$ は $s_{AC}$ が上界ちょうど（3 点が同一平面上で最も近い配置）、$S_3 = 0$ は下界ちょうど。

| D18 統計 | 値 |
|---|---|
| min | 0.2259 |
| median | 0.6890 |
| max | 0.9941 |

---

## Score 4 — SNN similarity（Jarvis & Patrick 1973）

3 点それぞれの近傍集合（A, B, C 自身を除く）の 3 者共通集合のサイズを最小近傍数で正規化する。

$$k_{\mathrm{norm}} = \max\!\left(1,\ \min(|N(A)|, |N(B)|, |N(C)|)\right)$$

$$S_4 = \frac{|N(A) \cap N(B) \cap N(C)|}{k_{\mathrm{norm}}}$$

3 点が多くの共通隣接特許を持つほど高スコア。共通隣接が存在しない場合は $S_4 = 0$。

| D18 統計 | 値 |
|---|---|
| min | 0.0000 |
| median | 1.0000 |
| max | 1.0000 |

---

## Confidence — 統合確信度（加重和）

$$\mathrm{Confidence} = 0.30 \cdot S_1 + 0.30 \cdot S_2 + 0.25 \cdot S_3 + 0.15 \cdot S_4$$

| 重み | スコア | 意図 |
|---|---|---|
| 0.30 | $S_1$ weakest-link | 三辺全体の品質下限 |
| 0.30 | $S_2$ angular tightness | 単位球上の密集度 |
| 0.25 | $S_3$ Schubert compliance | 三角不等式への適合 |
| 0.15 | $S_4$ SNN similarity | グラフ近傍の共有 |

| D18 統計 | 値 |
|---|---|
| min | 0.3440 |
| median | 0.7589 |
| max | 0.9298 |

---

## WCC スコア群（`graph/verify/wcc_scoring.py`）

`graph_analysis.py` の S1–S4 とは独立したスコア群。無向引用グラフの局所構造を定量化する。

### S_WCC — Watts-Strogatz 局所クラスタリング係数

$$C_v = \frac{2 L_v}{k_v (k_v - 1)} \quad (k_v \geq 2)$$

$$S_{WCC} = \min(C_A,\, C_B,\, C_C)$$

3 頂点すべてが密な局所近傍に埋め込まれているときのみ高くなる。計算は**無重み無向グラフ**に対して行う（重み付きグラフでは Barrat 式になる）。

| D18 統計 | 値 |
|---|---|
| min | 0.1000 |
| median | 0.6190 |
| max | 1.0000 |

### S_WCC_adj — Triad-adjusted 局所クラスタリング係数

標準 $C_v$ の問題: triad 自身の内部エッジ（A–B, B–C, A–C）が $C_v$ の計算に含まれ、値が人工的に押し上げられる（自己参照バイアス）。

修正: 各ノード $v$ の近傍から triad メンバーを除外した外部近傍 $N'(v) = N(v) \setminus \{A, B, C\}$ のみで計算する。

$$C'_v = \frac{2 L'(v)}{k' (k' - 1)} \quad (k' = |N'(v)| \geq 2)$$

$$S_{WCC\_adj} = \min(C'_A,\, C'_B,\, C'_C) \quad \text{(全頂点が定義済みの場合)}$$

$k' < 2$ のノードが1つでも存在する場合は **Undefined**。

| D18 統計 | 値 |
|---|---|
| min（defined のみ） | 0.0000 |
| median（defined のみ） | 0.5833 |
| max（defined のみ） | 1.0000 |
| Undefined | 258 / 1593 三角形 |

### score_ext_degree — 外部次数

triad 内部の 2 辺を除いた各頂点の外部次数の最小値。

$$\text{score\_ext\_degree} = \min(\deg A - 2,\, \deg B - 2,\, \deg C - 2)$$

| D18 統計 | 値 |
|---|---|
| min | 0 |
| median | 4.0 |
| max | 17 |

---

## 出力

### `graph/output/D18/triadic_scored.jsonl` — 全 1593 三角形（確信度降順）

`graph_analysis.py` が生成。S1–S4 + Confidence を収録。

| フィールド | 内容 |
|---|---|
| `rank` | 確信度順位（1 が最高） |
| `A`, `B`, `C` | 特許 ID |
| `s_AB`, `s_BC`, `s_AC` | 各辺の cosine 類似度 |
| `score_weakest_link` | $S_1$ |
| `score_angular_tightness` | $S_2$ |
| `score_bound_compliance` | $S_3$ |
| `score_snn` | $S_4$ |
| `confidence` | 統合確信度 |

### `graph/output/D18/verify/wcc_scored.jsonl` — 全 1593 三角形（S_WCC 降順）

`wcc_scoring.py` が生成。WCC スコア群 + S1–S4 を統合。

| フィールド | 内容 |
|---|---|
| `rank` | S_WCC 降順順位 |
| `A`, `B`, `C` | 特許 ID |
| `s_AB`, `s_BC`, `s_AC` | 各辺の cosine 類似度 |
| `score_wcc` | $S_{WCC}$（Watts-Strogatz） |
| `score_wcc_adj` | $S_{WCC\_adj}$（Triad-adjusted、未定義時 `null`） |
| `cc_adj_A`, `cc_adj_B`, `cc_adj_C` | 各頂点の $C'_v$（未定義時 `null`） |
| `score_ext_degree` | 外部次数の最小値 |
| `score_weakest_link` | $S_1$（triadic_scored.jsonl より結合） |
| `score_angular_tightness` | $S_2$ |
| `score_snn` | $S_4$ |
| `confidence` | 統合確信度 |

### `graph/output/D18/triads/wcc_no_consec.jsonl`

consecutive-D フィルタ（連番 D 特許を含む triad を除去）後の 1307 三角形。

### `graph/output/D18/summary.csv`

`graph_analysis.py` が生成するグラフ全体の記述統計（ノード数・エッジ数・三角形数・各スコアの min/median/max）。

### 可視化出力（`graph/output/D18/verify/`）

| ファイル | 内容 |
|---|---|
| `wcc_distribution.png` | $S_{WCC}$ のヒストグラム |
| `wcc_vs_scores.png` | $S_{WCC}$ と S1/S2/S4/Confidence の相関散布図 |
| `wcc_threshold_grid.png` | S1 × $S_{WCC}$ 閾値グリッド |
| `wcc_adj_threshold_grid.png` | S1 × $S_{WCC\_adj}$ グリッド（Undefined 列付き） |
| `wcc_threshold_grid_no_consec.png` | 上記の consecutive-D フィルタ版 |
| `wcc_adj_threshold_grid_no_consec.png` | 上記の consecutive-D フィルタ版 |
| `s3_degree_threshold_grid.png` | S1（weakest-link）× T3（外部次数 $\min(k_A-2, k_B-2, k_C-2)$）閾値グリッド |
| `wcc_fp_grid.png` / `wcc_fn_grid.png` | FP/FN triad の S1 × $S_{WCC}$ グリッド |
| `wcc_fp_grid_no_consec.png` / `wcc_fn_grid_no_consec.png` | FP/FN の no_consec 版 |

---

## rank の決定アルゴリズム

`rank` は **confidence（加重和）の降順順位**である。

```python
scored.sort(key=lambda r: -r['confidence'])   # confidence 降順ソート
for rank, r in enumerate(scored, 1):          # 1 始まりで順位を付与
    ...
```

$$\text{rank} = \text{confidence 降順での順番}$$

- rank = 1 : confidence 最大（D18: 0.9298）
- rank = 1593 : confidence 最小（D18: 0.3440）

**タイブレーク**: Python の `list.sort()` は安定ソートのため、confidence が同値の場合は `enumerate_triangles()` が返す辞書順（特許 ID の A → B → C 昇順）が保持される。D18 データでは完全同値の triad は存在せず、実質的に confidence のみで順位が決まる。

---

## 実装

### `graph/graph_analysis.py` — S1–S4 + Confidence

| 関数 | 役割 |
|---|---|
| `build_similarity_graph()` | cosine sim のみでグラフ構築（LLM 判定非依存） |
| `enumerate_triangles()` | 全 3-clique を辞書順列挙 |
| `angular_distance()` | $\arccos(s)$ |
| `schubert_lower_bound()` / `schubert_upper_bound()` | Schubert 2021 境界計算 |
| `score_min_similarity()` | $S_1$ |
| `score_angular_tightness()` | $S_2$ |
| `score_bound_compliance()` | $S_3$ |
| `score_snn()` | $S_4$ |
| `triadic_confidence()` | 4 スコア + 統合確信度を返す |
| `plot_score_distribution()` | 5 分布ヒストグラム |
| `plot_top_triangles_network()` | 上位 20 三角形ネットワーク図（次数エンコーディング） |

### `graph/verify/wcc_scoring.py` — WCC スコア群

| 関数 | 役割 |
|---|---|
| `build_citation_graph()` | **無重み**無向グラフ構築（Watts-Strogatz 係数用） |
| `build_similarity_graph()` | cosine sim 付き有重みグラフ構築（閾値フィルタ用） |
| `triad_adjusted_clustering_coeff()` | Triad-adjusted $C'_v$ を 3 頂点分計算 |
| `enumerate_triangles()` | 全 3-clique を辞書順列挙 |
| `plot_wcc_distribution()` | $S_{WCC}$ ヒストグラム |
| `plot_wcc_vs_scores()` | $S_{WCC}$ vs S1/S2/S4/Confidence 散布図 |
| `_compute_threshold_grids()` | S1 × T2 閾値グリッドの集計（Undefined 列込み） |
| `_render_two_panel_grid()` | Undefined 列 + T2 グリッドの 2 パネル描画 |
| `plot_threshold_grid()` | 閾値グリッド描画の公開インターフェース |
| `plot_s3_degree_grid()` | S3 × 外部次数グリッド描画 |
| `plot_fp_fn_wcc_grids()` | FP/FN triad の WCC グリッド描画 |
