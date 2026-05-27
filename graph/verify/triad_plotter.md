# triad_plotter — 共通 triad 可視化ライブラリ

`graph/verify/triad_plotter.py` は、様々な分析スクリプトで同一スタイルの triad 画像を生成するための共通ライブラリ。

---

## ファイル構成

```
graph/verify/
  triad_plotter.py          ← 共通ライブラリ（本ファイルの説明対象）
  visualize_threshold.py    ← 分析スクリプト例（T1×T2 閾値フィルタ）

graph/output/D18/visualize/
  {分析名}/
    triad_001.png
    triad_002.png
    ...
```

新しい分析を追加するときは `visualize_threshold.py` を参考に、フィルタ条件と出力ディレクトリ名だけ変えた新スクリプトを作る。画像スタイルは自動的に統一される。

---

## 画像レイアウト

```
┌──────────────┬──────────────┬──────────────┬────────────────────────────┐
│   Image A    │   Image B    │   Image C    │  seq   : 1                 │
│              │              │              │  rank  : 116               │
│  D0631088    │  D0631089    │  D0631090    │  S1(wl): 0.9910            │
│              │              │              │  S2(bc): 0.9243            │
│ AB:0.9910    │ AB:0.9910    │ BC:0.9941    │  S3(at): 0.9146            │
│ AC:0.9953    │ BC:0.9941    │ AC:0.9953    │  S4(snn):0.0000            │
│  [Yes][Yes]  │  [Yes][Yes]  │  [Yes][Yes]  │  conf  : 0.7840            │
│              │              │              │                            │
│              │              │              │  conf  : 0.7840            │
│              │              │              │  ────────────────────────  │
│              │              │              │  edge  sim    jdg          │
│              │              │              │  AB   0.9910  Yes          │
│              │              │              │  BC   0.9941  Yes          │
│              │              │              │  AC   0.9953  Yes          │
├──────────────┴──────────────┴──────────────┴────────────────────────────┤
│ D0631088→D0631089  [Yes]  sim=0.9910  rank=2  conf=5                   │
│   Both images depict identical line drawings of a toner cartridge...   │
│                                                                          │
│ D0631088→D0631090  [Yes]  sim=0.9953  rank=1  conf=5                   │
│   Both images depict the same elongated, rectangular toner cartridge... │
│                                                                          │
│ D0631089↔D0631090  [Yes]  sim=0.9941  rank=1  conf=5  ← completing     │
│   The two designs exhibit identical overall shape, form...              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 図の要素早見表（non-consecutive モード）

`--no-consec` オプション付きで出力される図の構成。連番D-ID除去済みデータ（`wcc_no_consec.jsonl`）を使用。右メタパネルなし・3列レイアウト。

### タイトル行

```
D18   S1=0.978, S2=1.000  (T1≥0.975, T2≥0.9, non-consecutive)
```

S1 = weakest-link 類似度、S2 = 局所クラスター係数 = min(C_A, C_B, C_C)。S2 の定義は[指標・略号の説明](#指標略号の説明)参照。

### 上半分：画像パネル + キャプション（メタパネルなし）

各パネルのキャプションはそのノードの局所クラスター係数 C_v を表示する。

| パネル | キャプション例 |
|---|---|
| A | `Local clustering coefficient: 1.000` ← C_A（ノード A の局所クラスター係数） |
| B | `Local clustering coefficient: 1.000` ← C_B |
| C | `Local clustering coefficient: 1.000` ← C_C |

### 下半分：有向グラフ + reason テキスト

```
D0787587→D0787590  [No]  Cosine similarity=0.9816
  The overall shape and form differ ...

D0787587→D0788844  [No]  Cosine similarity=0.9869
  The overall shape and form differ ...

D0787590↔D0788844  [No]  Cosine similarity=0.9780  ← completing
  The two designs differ significantly ...
```

ハブ（2辺の source）からの辺は `→`、三角形を完成させる辺は `↔ ← completing` で表示する。

---

## 指標・略号の説明

### タイトル行

```
D18  seq=1  S1=0.9910  S2=1.0000  (T1≥0.975, T2≥0.95)
```

| 表示 | 意味 |
|---|---|
| `D18` | USPTO 意匠特許分類クラスコード |
| `seq=N` | この分析内での連番（S1 降順） |
| `S1=X` | 三辺中の最小コサイン類似度（weakest-link）。triad の一体性を示す主指標 |
| `S2=X` | Watts-Strogatz 局所クラスタリング係数の最小値（= `score_wcc`）。引用ネットワーク局所密度の指標 |
| `T1≥X` | フィルタ条件: S1 の下限閾値 |
| `T2≥X` | フィルタ条件: S2 の下限閾値 |

---

### 右パネル（メタ情報）

#### 上部: triad スコア

| 略号 | フィールド名 | 定義 | 値域 |
|---|---|---|---|
| `seq` | — | この分析内での連番 | 1〜 |
| `rank` | `rank` | wcc_scored.jsonl での triad ランク（WCC 降順） | 1〜 |
| `S1(wl)` | `score_weakest_link` | min(s_AB, s_BC, s_AC)。三辺の最小コサイン類似度 | [0, 1] |
| `S2(cc)` | `score_wcc` | Watts-Strogatz 局所クラスタリング係数の最小値。引用ネットワーク内の局所密度指標。タイトルの S2 と同値 | [0, 1] |
| `S3(at)` | `score_angular_tightness` | 角距離タイトネス。三辺の角度的一致度 | [0, 1] |
| `S4(snn)` | `score_snn` | 3-way Shared Nearest Neighbor 類似度（Jarvis-Patrick 1973） | [0, 1] |
| `conf` | `confidence` | S1(wl)・S2(cc)・S3(at)・S4(snn) の加重平均による総合確信度 | [0, 1] |

**Watts-Strogatz 局所クラスタリング係数（Barabási 2016）**

```
C_v = 2 * L_v / (k_v * (k_v - 1))    （k_v < 2 のとき C_v = 0）

S2(cc) = min(C_A, C_B, C_C)
```

k_v はノード v の次数、L_v は v の近傍ノード間に存在する辺数。
C_v は v の引用近傍がどれだけ密に接続しているかを示す（C_v ∈ [0, 1]）。
S2(cc) はすべての頂点が局所的に密な引用近傍に埋め込まれているときのみ高くなる。
**計算は無重み無向グラフで行う**（networkx.clustering を使用）。重み付きグラフを渡すと
Barrat 加重式（結果が異なる）になるため注意。

#### 下部: 辺テーブル

| 列 | 意味 |
|---|---|
| `edge` | 辺の識別子。AB = A と B を結ぶ辺、BC = B と C、AC = A と C |
| `sim` | コサイン類似度（= s_AB, s_BC, s_AC）。[下段テキスト](#下段テキスト有向グラフ--reason) で詳細定義 |
| `jdg` | MLLM 類似判定。同上 |

---

### 画像パネル下のキャプション

```
AB: 0.9910 [Yes]  AC: 0.9953 [Yes]
```

各画像パネルには、その特許が端点になっている2辺の情報を表示する。
A パネル → AB・AC 辺、B パネル → AB・BC 辺、C パネル → BC・AC 辺。
各要素の定義は [下段テキスト](#下段テキスト有向グラフ--reason) を参照。

---

### 下段テキスト（有向グラフ + reason）

```
D0631088→D0631089  [Yes]  sim=0.9910  rank=2  conf=5
  Both images depict identical line drawings...

D0631089↔D0631090  [Yes]  sim=0.9941  rank=1  conf=5  ← completing
  The two designs exhibit identical overall shape...
```

| 要素 | 意味 |
|---|---|
| `A→B` | A の kNN（k 近傍）に B が含まれており、A から B への方向を持つ辺 |
| `B↔C` | 双方向辺。三角形を完成させる completing edge（後述） |
| `[Yes]` / `[No]` | MLLM 類似判定 |
| `sim=X` | コサイン類似度（0〜1、高いほど類似） |
| `rank=N` | B が A の kNN 内で何位か（1 = 最近傍、大きいほど遠い） |
| `conf=N` | MLLM の判定確信度（1〜5、5 = 最高確信） |
| `← completing` | この辺が completing edge であることを示すタグ（後述） |
| reason テキスト | MLLM が判定した理由文（英語） |

---

## 有向矢印の表示ルール

### データの方向性

`all.jsonl` の各レコードには `source` と `target` がある。`source` は比較クエリを実行した特許、`target` はその kNN 検索で返された特許。

```
source → target  =  source の kNN に target が含まれていた
```

### ハブ（hub）の検出

triad（A, B, C）内の 3 辺を `all.jsonl` で引くと、1 つのノードが 2 辺の `source` になっていることが多い。このノードを **ハブ** と呼ぶ。

```
例: D0631088 が A（ハブ）の場合
  A → B  (A の kNN に B が含まれていた)
  A → C  (A の kNN に C が含まれていた)
  B → C  (B の kNN に C が含まれていた)  ← completing edge
```

### 矢印の種類

| 辺の種類 | 矢印 | 条件 |
|---|---|---|
| **directed** | `A→B` | ハブが source の辺（kNN 由来の直接類似） |
| **bidirectional** | `B↔C` | ハブが source でない辺（三角形を閉じるために存在） |

### ← completing タグ

`↔` が付いた辺には `← completing` タグを表示する。

- A→B と A→C はハブ A の kNN 検索から得られた "A 視点での類似" を表す
- B↔C は A とは独立して B の kNN に C が含まれており、三角形を偶発的または構造的に閉じている辺
- この辺が存在することでグラフ上の三角形（3-clique）が成立する

---

## 公開 API

### データ読み込み

```python
from triad_plotter import load_jsonl, build_image_map, build_judgment_map

all_records = load_jsonl(Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl'))
img_map     = build_image_map(all_records)    # patent_id → 画像パス
judg_map    = build_judgment_map(all_records) # frozenset({src, tgt}) → edge record
```

### 単体描画

```python
from triad_plotter import plot_triad

plot_triad(
    triad,          # dict: A, B, C, s_AB, s_BC, s_AC, スコア群
    seq=1,
    img_map=img_map,
    judg_map=judg_map,
    out_path=Path('output/triad_001.png'),
    suptitle='D18  S1=0.9910  S2=1.0000',
    extra_meta=['mykey: value'],           # メタパネルへの追加行（省略可）
    border_colors=('#ff7f00', None, None), # 各画像パネルの枠色（省略可）
)
```

### 一括出力（分析ランナー）

```python
from triad_plotter import run_analysis

run_analysis(
    name='my_analysis',         # → graph/output/D18/visualize/my_analysis/
    triads=filtered_triads,
    img_map=img_map,
    judg_map=judg_map,
    out_base=Path('graph/output/D18/visualize'),
    suptitle_fn=lambda t, seq: f'D18  seq={seq}  S1={t["score_weakest_link"]:.4f}',
    extra_meta_fn=None,         # 省略可
    border_colors_fn=None,      # 省略可
)
```

---

## 新しい分析スクリプトの書き方

```python
"""my_analysis.py — （分析の説明）"""

from pathlib import Path
from triad_plotter import load_jsonl, build_image_map, build_judgment_map, run_analysis

WCC_SCORED = Path('graph/output/D18/verify/wcc_scored.jsonl')
ALL_JSONL  = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
OUT_BASE   = Path('graph/output/D18/visualize')

# 1. データ読み込み
all_triads  = load_jsonl(WCC_SCORED)
all_records = load_jsonl(ALL_JSONL)
img_map     = build_image_map(all_records)
judg_map    = build_judgment_map(all_records)

# 2. フィルタ（分析ごとに変える）
triads = [r for r in all_triads if r['score_weakest_link'] >= 0.95]
triads.sort(key=lambda r: -r['score_weakest_link'])

# 3. 出力
run_analysis('my_analysis', triads, img_map, judg_map, OUT_BASE,
             suptitle_fn=lambda t, seq: f'D18  seq={seq}')
```

---

## スクリプト構成

### pipeline.py — データ再計算（毎回実行）

WCC スコア・JSONL・グリッド画像をすべて再生成する。データが更新されたら実行する。

```bash
cd /home/sonozuka/design_similarity
python graph/verify/pipeline.py
```

### visualize_threshold.py — triad 個別画像生成（条件を変えて都度実行）

`--t1 / --t2 / --no-consec` で条件を指定する。出力ディレクトリ名は引数から自動生成される。

```bash
# 全 triad, T1=0.90, T2=0.90（デフォルト）
python graph/verify/visualize_threshold.py

# 全 triad, 閾値変更
python graph/verify/visualize_threshold.py --t1 0.975 --t2 0.90

# 連番D-ID除去済みデータ (wcc_no_consec.jsonl) を使用
python graph/verify/visualize_threshold.py --t1 0.975 --t2 0.90 --no-consec
```

| オプション | デフォルト | 説明 |
|---|---|---|
| `--t1` | `0.90` | S1 (weakest-link) の下限閾値 |
| `--t2` | `0.90` | S_WCC の下限閾値 |
| `--no-consec` | なし | `wcc_no_consec.jsonl` を使用。出力ディレクトリ末尾に `_no_consec` が付く |

**出力ディレクトリの命名規則:**

| 条件 | 出力先 |
|---|---|
| T1=0.90, T2=0.90 | `visualize/wcc_s1_0900_wcc_0900/` |
| T1=0.975, T2=0.90 | `visualize/wcc_s1_0975_wcc_0900/` |
| T1=0.975, T2=0.90, --no-consec | `visualize/wcc_s1_0975_wcc_0900_no_consec/` |

**前提条件:**  
`pipeline.py` を先に実行して `wcc_scored.jsonl` と `wcc_no_consec.jsonl` を最新化しておくこと。

---

## `wcc_scoring.py` の出力ファイル一覧

`graph/output/D18/verify/` に出力される。

| ファイル | 内容 |
|---|---|
| `wcc_scored.jsonl` | 全 triad のスコア（JSONL、フィールド一覧は下記） |
| `wcc_distribution.png` | S2(WCC) の分布ヒストグラム |
| `wcc_vs_scores.png` | S2 vs S1・S3(at)・S4 散布図（`triadic_scored.jsonl` 結合時のみ） |
| `wcc_threshold_grid.png` | S1 × S2 閾値グリッド（全 triad） |
| `wcc_threshold_grid_no_consec.png` | 同上、連番D-ID triad 除去済み |
| `wcc_adj_threshold_grid.png` | S1 × S2_adj (Triad-adjusted WCC) 閾値グリッド（全 triad） |
| `wcc_adj_threshold_grid_no_consec.png` | 同上、連番D-ID triad 除去済み |
| `s3_degree_threshold_grid.png` | S1 × score_ext_degree 閾値グリッド（外部次数 = min(deg-2)） |
| `fp_wcc_grid.png`, `fn_wcc_grid.png` | FP / FN triad の S1 × S2 グリッド |
| `fp_wcc_grid_no_consec.png`, `fn_wcc_grid_no_consec.png` | 同上、連番D-ID除去済み |

`graph/output/D18/triads/wcc_no_consec.jsonl` — 連番D-ID triad を除去した filtered 版（triad_plotter 向け）。

---

## wcc_threshold_grid.png

`graph/output/D18/verify/wcc_threshold_grid.png`

縦軸 T₁（weakest-link 閾値）× 横軸 T₂（局所クラスタリング係数閾値）のグリッド。
各セルは S1 ≥ T₁ かつ S2 ≥ T₂ を満たす D18 閉引用三角形の件数を示す。強調なし。

### 実測値（D18, Watts-Strogatz 実装）

| T₁ | T₂ | 件数 | 備考 |
|---|---|:---:|---|
| 0.900 | 0.900 | **125** | — |
| 0.950 | 0.850 | **38** | — |
| 0.950 | 0.900 | **38** | — |

### S2 の定義変更履歴

| 変更日 | 変更内容 |
|---|---|
| 2026-05-26 | S2 を **Watts-Strogatz 局所クラスタリング係数** から **Schubert 三角不等式適合度** に変更。Schubert 実装では (T₁=0.90, T₂=0.90) で 46 件となり旧論文値に一致したが、論文の数式記述（Eq.2: Cv = 2Lv/(kv(kv-1))）と整合しないため差し戻し。 |
| 2026-05-26 | S2 を **Schubert 三角不等式適合度** から **Watts-Strogatz 局所クラスタリング係数** に差し戻し。無重み無向グラフに nx.clustering を適用し S2 = min(C_A, C_B, C_C) を計算。論文のデータが更新されたため数値は旧論文値（46, 34, 13）と異なる。 |

---

## 入力ファイル

| ファイル | 内容 |
|---|---|
| `graph/output/D18/verify/wcc_scored.jsonl` | 全 triad のスコア（下記フィールド一覧参照） |
| `/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl` | 辺ごとの source, target, rank, similarity, judgment, reason |

### `wcc_scored.jsonl` フィールド一覧

`wcc_scoring.py` が出力する全フィールド。`triadic_scored.jsonl` が存在する場合は結合済みフィールドも付与される。

| フィールド | 由来 | 内容 |
|---|---|---|
| `rank` | wcc_scoring | score_wcc 降順の順位 |
| `A`, `B`, `C` | wcc_scoring | 特許 ID |
| `s_AB`, `s_BC`, `s_AC` | wcc_scoring | 各辺の cosine 類似度 |
| `score_wcc` | wcc_scoring | Watts-Strogatz 局所クラスタリング係数の最小値 S2 = min(C_A, C_B, C_C) |
| `score_wcc_adj` | wcc_scoring | Triad-adjusted WCC。triad 内部エッジを除外して計算。計算不能のとき null |
| `cc_adj_A`, `cc_adj_B`, `cc_adj_C` | wcc_scoring | 各ノードの triad-adjusted クラスタリング係数（null = 外部次数 < 2） |
| `score_ext_degree` | wcc_scoring | 外部次数の最小値 = min(deg(A)-2, deg(B)-2, deg(C)-2) |
| `score_weakest_link` | triadic_scored | S1 = min(s_AB, s_BC, s_AC)（結合フィールド） |
| `score_angular_tightness` | triadic_scored | 角度的一致度（結合フィールド） |
| `score_snn` | triadic_scored | 3-way Shared Nearest Neighbor 類似度（結合フィールド） |
| `confidence` | triadic_scored | S1〜S4 加重平均の統合確信度（結合フィールド） |
