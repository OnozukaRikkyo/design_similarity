# ネットワーク可視化スクリプト (`visualize_ergm_network.py`)

Chakraborty et al. (2020) の全方程式を実装し、`build_ergm_input.py` の出力から論文品質の PNG を生成する。

> Chakraborty, Byshkin & Crestani (2020)  
> "Patent citation network analysis: A perspective from descriptive statistics and ERGMs"  
> *PLoS ONE* 15(12): e0241797.

---

## スクリプト

```
/home/sonozuka/design_similarity/visualize_ergm_network.py
```

---

## 実装した方程式

| 方程式 | 内容 |
|--------|------|
| Eq.(1) | ERGM 確率: `π(x) = exp(Σ θ_s g_s(x)) / Z` |
| Eq.(2) | Arc 統計: `g_L(x) = Σ x_{i,j}` |
| Eq.(4) | Sender 効果: `g_send(x) = Σ a_i x_{i,j}` |
| Eq.(5) | Receiver 効果: `g_rec(x) = Σ a_j x_{i,j}` |
| Eq.(6) | Homophily: `g_homo(x) = Σ δ(a_i,a_j) x_{i,j}` |
| Eq.(7) | Date guard: `g_date(x) = Σ H(d_j - d_i) x_{i,j}` |
| Eq.(8) | 単位ステップ関数: `H(y) = 0 if y≤0, else 1` |
| Eq.(9) | Transitivity: `T = 3×triangles / connected-triples` |
| Eq.(10) | Density: `D = |E| / (|V|(|V|-1))` |
| Eq.(11) | Betweenness: `g(v) = Σ σ_st(v) / σ_st` |
| Snijders | GWIDegree (AltInStar) / GWODegree / GWESP / GWDSP |

---

## 入出力

| 項目 | パス | 形式 |
|------|------|------|
| 入力 | `ergm_input/arc_list.txt` | テキスト |
| 入力 | `ergm_input/attributes.txt` | タブ区切り CSV |
| 出力 | `output/fig1_network_topology.png` | 300 DPI PNG |
| 出力 | `output/fig2_ergm_statistics.png` | 300 DPI PNG |
| 出力 | `output/fig3_degree_distribution.png` | 300 DPI PNG |
| 出力 | `output/fig4_homophily_heatmap.png` | 300 DPI PNG |
| 出力 | `output/fig5_sender_receiver.png` | 300 DPI PNG |
| 出力 | `output/fig6_gw_statistics.png` | 300 DPI PNG |
| 出力 | `output/fig7_date_guard.png` | 300 DPI PNG |
| 出力 | `output/ergm_statistics.csv` | 全統計量 CSV |

---

## 出力図の詳細

### fig1_network_topology.png — Eq.(9)(10) ネットワーク構造概観

| 視覚要素 | データ特徴 |
|---------|-----------|
| ノード色 | primary D-class（35 色パレット、凡例付き） |
| ノードサイズ | degree（`s = 20 + 120 * (k/k_max)^0.6`） |
| サイズ凡例 | 参照 degree 4 値（右下） |
| クラス凡例 | 全 D-class（左下、3 列） |
| 注釈ボックス | T (Eq.9)・D (Eq.10)・N・E |

### fig2_ergm_statistics.png — Eq.(1-8) ERGM 統計量

| パネル | 内容 |
|--------|------|
| (A) | ERGM 式 + 全 g_s(x) 数値（数式テキスト） |
| (B) | Sender 効果 g_send(x; a) の D-class 別棒グラフ（Eq.4） |
| (C) | Receiver 効果 g_rec(x; a) の D-class 別棒グラフ（Eq.5） |
| (D) | Sender vs. Receiver 散布図（対角線: Send=Receive） |
| (E) | T・D・multi-class %・homophily 比の要約棒グラフ |
| (F) | Date guard ヒストグラム（前進 / 後退アーク、Eqs. 7-8） |

### fig3_degree_distribution.png — Eq.(10)(11) 分布

| パネル | 内容 |
|--------|------|
| (A) | 次数 CCDF（log-log）+ べき乗則フィット（Eq.10） |
| (B) | Betweenness CCDF（log-log）+ べき乗則フィット（Eq.11） |
| (C) | Degree vs. Betweenness 散布図（log 相関係数付き） |

### fig4_homophily_heatmap.png — Eq.(6) 35×35 行列

| パネル | 内容 |
|--------|------|
| (A) | 生の共引用件数（log スケール、対角線を赤枠で強調） |
| (B) | 行正規化フラクション（同クラス率を紺枠で強調） |

### fig5_sender_receiver.png — Eq.(4)(5) per-class

| パネル | 内容 |
|--------|------|
| (A) | 絶対 arc 数の sender/receiver 比較（D-class 別色） |
| (B) | ノード数正規化（arcs per node）の比較 |

### fig6_gw_statistics.png — GW ネットワーク統計

| パネル | 内容 |
|--------|------|
| (A) | GWIDegree / GWODegree vs. α （α=0.5～4.0） |
| (B) | GWESP vs. α |
| (C) | Edgewise Shared Partner 分布（log スケール） |
| (D) | 統計量サマリーと論文 Table 7 の解釈テキスト |

### fig7_date_guard.png — Eq.(7)(8) 時間的バイアス

| パネル | 内容 |
|--------|------|
| (A) | d_j - d_i の分布（前進 / 後退アーク色分け） |
| (B) | 単位ステップ関数 H(y) の図示 |
| (C) | 引用年齢差の累積分布（前進 vs. 後退） |

---

## 主要関数

| 関数 | 対応方程式 | 役割 |
|------|-----------|------|
| `eq2_arc_stat(arcs)` | Eq.(2) | アーク総数 |
| `eq4_sender_effect(arcs, node_class)` | Eq.(4) | D-class 別 sender 効果 |
| `eq5_receiver_effect(arcs, node_class)` | Eq.(5) | D-class 別 receiver 効果 |
| `eq6_homophily(edges, node_class, cls_list)` | Eq.(6) | 35×35 homophily 行列 |
| `eq7_date_guard(arcs, node_date)` | Eq.(7) | 前進アーク数 |
| `eq9_transitivity(G)` | Eq.(9) | `nx.transitivity(G)` |
| `eq10_density(G)` | Eq.(10) | `M / (N(N-1))` |
| `eq11_betweenness(G, k)` | Eq.(11) | betweenness centrality（k-sample） |
| `gw_idegree(G, alpha)` | Snijders | GWIDegree (AltInStar) |
| `gw_esp(G, alpha)` | Snijders | GWESP (AltKTriangleT) |
| `gw_dsp(G, alpha)` | Snijders | GWDSP (AltTwoPathsTD) |
| `focus_subgraph(G, top_n)` | — | degree 上位 top_n + 1-hop |
| `ccdf(degs)` | — | 補累積分布関数 |

---

## 実行方法

```bash
# デフォルト（全図生成）
python visualize_ergm_network.py

# 出力先・入力先を指定
python visualize_ergm_network.py --ergm-dir ./ergm_input --out-dir ./output

# サブグラフサイズと betweenness 近似を調整
python visualize_ergm_network.py --top-n 500 --bc-k 1000

# GW 統計をスキップ（大規模グラフで低速）
python visualize_ergm_network.py --no-fig6
```

### オプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--ergm-dir` | `ergm_input` | `build_ergm_input.py` 出力ディレクトリ |
| `--out-dir` | `output` | 出力先ディレクトリ |
| `--top-n` | `300` | fig1 のサブグラフシードノード数 |
| `--bc-k` | `500` | betweenness 近似 BFS ソース数（Eq.11） |
| `--no-fig1` | — | ネットワーク構造図をスキップ |
| `--no-fig6` | — | GW 統計図をスキップ（`gw_dsp` が低速） |

---

## 注意事項

- `gw_dsp()` は O(N × degree²) で大規模グラフでは低速。`--no-fig6` で回避可能
- `attributes.txt` に `date` 列がない場合、fig2 パネル F と fig7 はスキップされる
- `eq11_betweenness` は `N > bc_k` のとき k-sample 近似を使用（`seed=42` で固定）

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [ergm_input.md](ergm_input.md) | `visualize_ergm_network.py` | 論文・プレゼン資料への組み込み |
| `ergm_input/arc_list.txt` 等 | → `output/fig*.png` / `ergm_statistics.csv` | — |