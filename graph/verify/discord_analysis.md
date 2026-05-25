# 閾値設計支援可視化 + Discord Triad 分析

`graph/verify/discord_analysis.py` の 1 本で以下をすべて実行する。

---

## 入力

| ファイル | 内容 |
|---|---|
| `graph/output/D18/triadic_scored.jsonl` | 全 1,593 三角形の A, B, C, s_AB, s_BC, s_AC, S1〜S4, confidence |
| `/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl` | 辺ごとの rank / similarity / judgment / reason |
| `/mnt/eightthdd/uspto/data/{year}.csv` | patent_id → 意匠タイトル |

---

## 処理フロー

```
triadic_scored.jsonl（1593 triads）
  ├── [Fig 1] scatter_s1_s3.png       — S1×S2 散布図（全 triad、S3 色付け）
  ├── [Fig 2] parallel_coordinates.png — 平行座標（S1/S2/S3）
  ├── [Fig 3] threshold_survival.png  — 生存曲線（S1 / S2 / S1&S2）
  └── [Fig 4] threshold_grid.png      — S1×S2 閾値グリッド（GT 候補根拠図）
              threshold_grid.csv

all.jsonl
  └── build_judgment_map()            → edge_judg_map
        ↓  Discord 辺（FP / FN）を抽出
  ├── [Fig 5] discord_scatter.png     — S1×S2 散布図（全 triad + FP/FN 強調）
  ├── [Fig 6] fp_grid.png             — S1×S2 グリッド（FP triads）
  ├── [Fig 7] fn_grid.png             — S1×S2 グリッド（FN triads）
  ├── [CSV]   fp.csv / fn.csv
  └── [IMG]   fp_001.png 〜 / fn_001.png 〜
```

---

## 出力

`graph/output/D18/verify/`

| ファイル | 内容 |
|---|---|
| `scatter_s1_s3.png` | S1×S2 散布図（全 triad）。GT 閾値候補の格子線付き |
| `parallel_coordinates.png` | 平行座標（S1/S2/S3 軸）。min(S1,S2) 上位 50 件を強調 |
| `threshold_survival.png` | 閾値 vs 残存 triad 数の生存曲線（S1 / S2 / S1&S2） |
| `threshold_grid.png` | S1×S2 閾値グリッド（**GT 候補根拠図**）。20〜50 件を太字 |
| `threshold_grid.csv` | 同上 CSV |
| `discord_scatter.png` | S1×S2 散布図。FP（オレンジ★）/ FN（緑★）を全 triad に重ね描き |
| `fp_grid.png` | `threshold_grid.png` と同軸・同スタイルで FP triad のみの件数を表示 |
| `fn_grid.png` | 同上、FN triad |
| `fp.csv` | FP triad 一覧（triad スコア + FP 辺の rank/sim/reason） |
| `fn.csv` | FN triad 一覧 |
| `fp_001.png` 〜 | FP triad の 3 枚画像 |
| `fn_001.png` 〜 | FN triad の 3 枚画像 |

---

## スコア定義

| 変数 | フィールド | 意味 |
|---|---|---|
| S1 | `score_weakest_link` | min(s_AB, s_BC, s_AC)。GT 条件の第 1 軸 |
| S2 | `score_bound_compliance` | Schubert 三角不等式に基づく幾何的整合性。GT 条件の第 2 軸 |
| S3 | `score_angular_tightness` | 角度的一致度（可視化参考値。GT 条件に含まない）|

**GT 設計方針**: `S1 ≥ T₁ AND S2 ≥ T₂` の 2 条件 AND でグリッド探索し、目視確認可能な 20〜50 件を選択。

| T₁ | T₂ | GT 候補 triad 数 |
|---|---|:---:|
| 0.90 | 0.90 | 46 |
| 0.95 | 0.85 | 34 |
| 0.95 | 0.90 | 13 |

---

## Discord 辺の定義

D18 共引用グラフの辺のうち、ベクトル類似度ランクと MLLM 判定が食い違う辺を **Discord 辺** と呼ぶ。

| 種別 | ベクトル条件 | MLLM 判定 | 解釈 |
|---|---|---|---|
| **FP** (False Positive) | rank ≤ rank_fp AND sim ≥ sim_fp | No | ベクトルは類似と言うが MLLM は非類似 |
| **FN** (False Negative) | rank ≥ rank_fn AND sim < sim_fn | Yes | ベクトルは非類似と言うが MLLM は類似 |

### 辺ごとの CM ラベル

| CM | Vector Positive | GT Positive（MLLM） | 辺の性質 |
|---|---|---|---|
| **TP** | Yes | Yes | ベクトルも MLLM も類似と判定 |
| **FP◀** | Yes | No | ベクトルの誤検出（triad 選出トリガー） |
| **FN◀** | No | Yes | ベクトルの見逃し（triad 選出トリガー） |
| **TN** | No | No | ベクトルも MLLM も非類似と判定 |

Vector Positive の定義: `rank ≤ --rank-fp AND sim ≥ --sim-fp`
`◀` は当該 triad の選出トリガーとなった辺を示す。

---

## 個別三角形画像レイアウト

```
┌──────────────┬──────────────┬──────────────┬──────────────────────────────┐
│  Image A     │  Image B     │  Image C     │  seq   : 1                   │
│              │              │              │  triad : rank=729            │
│              │              │              │  S1(min): 0.9902             │
│              │              │              │  S3(ang): 0.9110             │
│              │              │              │  S2(sch): 0.7877             │
├──────────────┼──────────────┼──────────────┤  ──────────────────────────  │
│ D0XXXXXX     │ D0XXXXXX     │ D0XXXXXX     │  edge  sim    jdg  CM        │
│ AB:[TP] 0.99 │ AB:[TP] 0.99 │ BC:[FP]◀0.99│  AB   0.9912  Yes  TP        │
│ AC:[FP]◀0.99│ BC:[FP]◀0.99│ AC:[FP]◀0.99│  BC   0.9902  No   FP◀       │
│              │              │              │  AC   0.9922  No   FP◀       │
│              │              │              │  [FP: BC]  rank=4 sim=0.9902 │
└──────────────┴──────────────┴──────────────┴──────────────────────────────┘
```

---

## D18 実測値（2026-05-24, デフォルト閾値）

| | FP (rank≤10, sim≥0.90, No) | FN (rank≥200, sim<0.90, Yes) |
|---|---:|---:|
| Discord 辺数 | 257 | 19 |
| Discord 辺を含む triad 数 | 536 | 46 |

---

## グリッド描画の共通関数

`plot_s1s3_grid()` がグリッド図のスタイルを一元管理する。
`threshold_grid.png`・`fp_grid.png`・`fn_grid.png` はすべてこの関数を使用するため、
スタイル変更は本スクリプト 1 箇所のみで済む。

---

## 入力データの更新パイプライン

`discord_analysis.py` の 2 つの入力ファイルは、以下のパイプラインで生成される。

### 依存関係

```
【生データ】
  /mnt/eightthdd/uspto/json/{year}.json       ← USPTO 引用 JSON
  /mnt/eightthdd/uspto/data/{year}.csv        ← 特許属性（ID・タイトル・分類等）
  /mnt/eightthdd/impact/images/{year}/        ← TIF 画像

  Step 1  build_edge_list.py
          → /mnt/eightthdd/uspto/edge_list/{year}.csv

  Step 2a extract_cited_image_pairs.py
          → /mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl

  Step 2c add_class_to_edge_list.py
          → /mnt/eightthdd/uspto/edge_list_with_class/{year}.csv

  Step 3  judge_cited_pairs.py              ← MLLM 類似判定（低速）
          → /mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl

  Step 4a vector/filter_pairs_by_class.py --class D18
          → /mnt/eightthdd/uspto/class/D18/cited_image_pairs/{year}.jsonl

  Step 4b vector/build_class_vectors.py --class D18 --no-gpu
          → /mnt/eightthdd/uspto/class/D18/cited_image_vectors/{type}/

  Step 4c vector/build_rank_index.py --class D18
          → /mnt/eightthdd/uspto/class/D18/rank_index/{type}/

  Step 4d vector/compute_ranks.py --class D18 --sim cosine_numpy
          → /mnt/eightthdd/uspto/class/D18/rank_results/cosine_numpy/{year}.jsonl

  Step 4e vector/join_judgments.py --class D18 --sim cosine_numpy
          → /mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl
                                                                        ↑ 入力 #2

  Step 5  graph/graph_analysis.py
          → graph/output/D18/triadic_scored.jsonl
                                ↑ 入力 #1
```

### 更新シナリオ

**MLLM 判定を追加した場合**（Step 3 の結果が増えた）

```bash
cd /home/sonozuka/design_similarity
python update_downstream.py --with-graph
```

Step G（`join_judgments.py`）→ K（`graph_analysis.py`）→ L → N（`discord_analysis.py`）→ M（`wcc_scoring.py`）の順に自動実行される。

**新しい年度データを追加した場合**（USPTO データが増えた）

```bash
cd /home/sonozuka/design_similarity
python build_edge_list.py
python extract_cited_image_pairs.py
python add_class_to_edge_list.py
python judge_cited_pairs.py               # 新規ペアのみ追加判定
python update_downstream.py --with-vector --no-gpu --with-graph
```

詳細: [`../../UPDATE.md`](../../UPDATE.md) · [`../../vector/doc/pipeline.md`](../../vector/doc/pipeline.md) · [`../triadic_scoring.md`](../triadic_scoring.md)

---

## 実行

```bash
cd /home/sonozuka/design_similarity
python graph/verify/discord_analysis.py
python graph/verify/discord_analysis.py --rank-fp 5 --sim-fp 0.95 --rank-fn 300 --sim-fn 0.85 -N 30
```

| オプション | デフォルト | 説明 |
|---|---|---|
| `--rank-fp` | `10` | FP の rank 上限（rank ≤ この値）|
| `--sim-fp`  | `0.90` | FP の sim 下限（sim ≥ この値）|
| `--rank-fn` | `200` | FN の rank 下限（rank ≥ この値）|
| `--sim-fn`  | `0.90` | FN の sim 上限（sim < この値）|
| `-N`        | `20` | 個別画像の生成数（FP, FN それぞれ）|
| `--class`   | `D18` | 対象クラスコード |