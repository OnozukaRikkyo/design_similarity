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

## 出力

`graph/output/D18/triadic_scored.jsonl` — 全 1593 三角形（確信度降順）

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

`graph/graph_analysis.py`

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
