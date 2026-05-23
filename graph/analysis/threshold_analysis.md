# 閾値設計支援可視化

`graph/analysis/threshold_analysis.py` により、S1・S2・S3 を多角的に可視化し、「どこに閾値を置くか」「その閾値で triad が何個残るか」を定量的に把握する。

---

## 入力

| ファイル | 内容 |
|---|---|
| `graph/output/D18/triadic_scored.jsonl` | 全 1593 三角形のスコア（confidence 降順） |

---

## 出力

`graph/output/D18/analysis/`

| ファイル | 内容 |
|---|---|
| `scatter_s1_s3_s2.png` | 2D 散布: x=S1, y=S3, color=S2 |
| `scatter_s1_s2_s3.png` | 2D 散布: x=S1, y=S2, color=S3 |
| `scatter_s2_s3_s1.png` | 2D 散布: x=S2, y=S3, color=S1 |
| `parallel_coordinates.png` | 平行座標: S1 / S2 / S3 / confidence |
| `threshold_survival.png` | 閾値 vs 残存 triad 数（生存曲線）|
| `threshold_grid.png` | S1 × S3 閾値グリッドのヒートマップ |
| `threshold_grid.csv` | 同上を CSV 形式で出力 |

---

## 各図の説明

### Fig 1: 2D 散布図（3 組み合わせ）

S1・S2・S3 のうち 2 つを x/y 軸、残り 1 つを点の色とする。

| 図 | x 軸 | y 軸 | 色 |
|---|---|---|---|
| `scatter_s1_s3_s2.png` | S1 weakest-link | S3 Schubert compliance | S2 angular tightness |
| `scatter_s1_s2_s3.png` | S1 weakest-link | S2 angular tightness | S3 Schubert compliance |
| `scatter_s2_s3_s1.png` | S2 angular tightness | S3 Schubert compliance | S1 weakest-link |

- 破線は参考閾値候補（S1: 0.85/0.90/0.95、S2: 0.70/0.80/0.85、S3: 0.70/0.80/0.90）
- 破線の右上・上側の領域に存在する点の数が、その閾値条件での残存 triad 数に対応する

### Fig 2: 平行座標プロット

S1・S2・S3・confidence の 4 軸を並べ、各 triad を折れ線として描く。

- 全 1593 triad を薄いグレーで描画
- confidence 上位 50 件を plasma カラーマップで重ね描き
- 「高信頼 triad のスコアプロファイル」と「全体の分布」を同時に比較できる

**読み方**: 上位 triad の折れ線が 4 軸すべてで高い位置を通っているほど、各スコアがバランスよく高い。

### Fig 3: 閾値 vs 残存 triad 数（生存曲線）

横軸に閾値 T（0.4〜1.0）、縦軸に「スコア ≥ T の triad 数」をプロット。

| パネル | 条件 |
|---|---|
| S1 単独 | S1 ≥ T |
| S2 単独 | S2 ≥ T |
| S3 単独 | S3 ≥ T |
| S1 & S3 複合 | S1 ≥ T かつ S3 ≥ T |

- 破線（T=0.80/0.85/0.90/0.95）における件数を数値で注記
- どのスコアがボトルネックになるかが一目でわかる

### Fig 4: S1 × S3 閾値グリッド

S1 閾値（行）× S3 閾値（列）の格子点で、「S1 ≥ T1 かつ S3 ≥ T3 を満たす triad 数」をヒートマップ表示。

閾値範囲: 0.75〜1.00（0.05 刻み）

**読み方**: セルの数値が目標件数（例: 20〜50 件）に近い行・列の組み合わせが、閾値設計の候補になる。

`threshold_grid.csv` に同一内容を表形式で出力。

```
s1_th \ s3_th, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00
0.75,          ...,  ...,  ...,  ...,  ...,  ...
0.80,          ...,  ...,  ...,  ...,  ...,  ...
...
```

---

## 実行

```bash
cd /home/sonozuka/design_similarity
python graph/analysis/threshold_analysis.py
```

---

## D18 での参考値

| 条件 | 残存 triad 数 |
|---|---|
| S1 ≥ 0.90 | 526 |
| S1 ≥ 0.95 | 206 |
| S3 ≥ 0.70 | 764 |
| S3 ≥ 0.90 | 162 |
| S1 ≥ 0.90 かつ S3 ≥ 0.70 | 274 |
| S1 ≥ 0.90 かつ S3 ≥ 0.90 | 46 |
| S1 ≥ 0.95 かつ S3 ≥ 0.90 | 13 |
