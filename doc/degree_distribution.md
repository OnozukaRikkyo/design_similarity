# 次数分布の可視化 (`plot_indegree.py`)

USPTO 意匠特許引用グラフの次数分布を log-log スケールで描画するスクリプト。
各ノードを 1 点ずつプロットし、べき乗則フィットを重ねて表示する。

---

## 出力ファイル

| ファイル | 内容 |
|----------|------|
| `indegree_pdf.png` | 確率密度関数 P(k) の log-log 散布図 |
| `indegree_ccdf.png` | 補累積分布関数 P(K ≥ k) の log-log 散布図 |

---

## グラフモデル

### 現在の設定：無向グラフ

エッジリスト CSV の各行について、`source` ノードと `target` ノードの両方に +1 する。
自己ループ（source = target）は +2 とカウントする（無向グラフの標準的な定義）。

```
degree[node] = (sourceとして登場した回数) + (targetとして登場した回数)
```

### 有向グラフとして集計する場合

| 関数 | 集計対象 |
|------|----------|
| `compute_indegrees()` | `target` 列のみ → 入次数 |
| `compute_outdegrees()` | `source` 列のみ → 出次数 |
| `compute_degrees_undirected()` | `source` + `target` → 無向次数（現在使用中） |

`plot_pdf` / `plot_ccdf` は `degrees_out` 引数に出次数を渡すと、入次数（黒○）と
出次数（赤×）を同一図に重ねて表示できる。

---

## プロット方式

### (a) PDF — `indegree_pdf.png`

- **縦軸**: P(k) = (次数が k のノード数) / N
- **横軸**: 次数 k
- 同じ次数 k を持つノード群には log 空間で微小ジッター（σ = 0.07 in log₁₀）を付与し、全 N 点を分離して表示する

### (b) CCDF — `indegree_ccdf.png`

- **縦軸**: P(K ≥ k) = (次数が k 以上のノードの割合)
- **横軸**: 次数 k
- 次数を昇順ソートし、ランク i のノードに y = (N − i) / N を割り当てることで
  全 N 点が自然に異なる座標を持つ

---

## 軸スケール設計

- 横軸・縦軸とも **同一デケード幅**（`set_aspect('equal', adjustable='box')`）
- 横軸は **10⁰ = 1 から開始**し、縦軸スパインとの間にわずかな余白（0.08 デケード）を設ける
- 縦軸は全データが収まるよう自動設定し、横軸が縦軸より短い場合は右へ延長して揃える

---

## べき乗則フィット

log-log 空間での OLS（最小二乗）線形回帰により P(k) ∝ k^{−γ} を推定する。

| 図 | フィット対象 | 推定値の読み方 |
|----|-------------|---------------|
| PDF | 固有次数ごとの P(k) | γ がそのまま指数 |
| CCDF | 固有次数ごとの P(K ≥ k) | γ − 1 がフィット値（表示も γ−1） |

フィット線は赤破線（有向グラフの out-degree オーバーレイ時）または黒破線（単一分布時）で描画される。
フィット線はデータ点より前面に描画する（zorder=4）。

---

## 実行方法

```bash
# 全年（2007–2010）、デフォルト出力
python plot_indegree.py

# 特定年のみ
python plot_indegree.py 2007 2008

# 出力パスを指定
python plot_indegree.py --out-pdf fig_pdf.png --out-ccdf fig_ccdf.png

# フィットなし
python plot_indegree.py --no-fit

# LaTeX レンダリング（要 texlive）
python plot_indegree.py --usetex
```

---

## 図スタイル

Physical Review Letters (PRL) シングルカラム幅（3.375 inch）準拠。

| 設定項目 | 値 |
|----------|----|
| フォント | Times New Roman / STIX Math |
| 目盛り方向 | 内向き（4 辺すべて） |
| 補助目盛り | 対数軸の各デケード内に表示 |
| 解像度 | 300 DPI |
| フォント埋め込み | TrueType (pdf/ps fonttype=42) |

---

## データソース

エッジリスト CSV については [citation_graph.md](citation_graph.md) を参照。

| パス | 内容 |
|------|------|
| `/mnt/eightthdd/uspto/edge_list/2007.csv` | 2007 年分エッジリスト |
| `/mnt/eightthdd/uspto/edge_list/2008.csv` | 2008 年分エッジリスト |
| `/mnt/eightthdd/uspto/edge_list/2009.csv` | 2009 年分エッジリスト |
| `/mnt/eightthdd/uspto/edge_list/2010.csv` | 2010 年分エッジリスト |

### 実測値（無向グラフ、2007–2010 合計）

| 統計量 | 値 |
|--------|----|
| ノード数 N | 21,984 |
| エッジ数 | 44,533 |
| 最小次数 | 1 |
| 最大次数 | 184 |
| 平均次数 | 4.05 |
| べき乗則指数 γ（PDF）| 未計測 |
| べき乗則指数 γ−1（CCDF）| 未計測 |

> エッジリストを共引用ネットワークに修正したため旧統計値（N=33,848, E=92,714）は無効。`plot_indegree.py` を再実行して γ を更新すること。
