# ERGM 分析用入力ファイル生成 (`build_ergm_input.py`)

USPTO 意匠特許共引用グラフの **EstimNetDirected 用入力ファイル**を生成するスクリプト。
意匠分類（D1–D99）をノード属性として扱い、クラス間の Homophily・Sender/Receiver 効果を
ERGM で推定するための入力ファイル群を出力する。

---

## スクリプト

```
/home/sonozuka/design_similarity/build_ergm_input.py
```

---

## 論文との対応関係

本スクリプトは以下の論文の手法を意匠特許ネットワークに適用する。

> *Patent citation network analysis: A perspective from descriptive statistics and ERGMs*

### 元論文の設計と本実装の違い

| 項目 | 元論文の設計 | 本実装 |
|------|-------------|--------|
| ネットワーク種別 | 有向引用ネットワーク（A が B を引用） | 無向共引用ネットワーク（A と B が同一出願で共引用）→ 双方向アークとして出力 |
| 分類体系 | IPC 分類（Section A–H、Subclass 4文字） | USPTO 意匠分類（D1–D99、単一階層） |
| ネットワーク範囲 | セクター B/E のサブネットワーク | 全クラス横断（D1–D99） |
| 分類の役割 | サブネット分割の基準 | ノード属性（Sender/Receiver/Homophily） |

### 統計量の対応

| 論文の統計量 | 本実装の対応変数 | 説明 |
|-------------|----------------|------|
| IPC Section（A–H）ダミー | `IsClass_D1` … `IsClass_D99` | D-class ごとのバイナリフラグ（35 変数） |
| ReceiverEffect (applicant_country) | ReceiverEffect (IsClass_Dxx) | 各クラスの特許が「共引用されやすいか」 |
| SenderEffect (language) | SenderEffect (IsClass_Dxx) | 各クラスの特許が「多くの特許と共引用されるか」 |
| OverlappingCategorization（式6）| `primary_class` Homophily | 同一メインクラス間のバイナリ Homophily |
| — （元論文にない） | `class_sim_jaccard.npz` PairAttribute | 全クラス Jaccard 類似度（連続値拡張） |
| n_sections | `n_classes` | 分類コード多様性スコア（連続変量） |

### 新たに答えられる問い（元論文との差分）

- `IsClass_D14`（Recording/Communication/Info）の ReceiverEffect が正 → IT 機器意匠は他から共引用されやすい
- `IsClass_D12`（Transportation）の SenderEffect が正 → 輸送機器意匠は多くのペアと共引用される
- Jaccard PairAttribute の係数が正 → 分類が近い（類似分野の）意匠ほど共引用されやすい

---

## 入出力

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/edge_list/<year>.csv` | CSV（共引用エッジリスト） |
| 入力 | `/mnt/eightthdd/uspto/data/<year>.csv` | CSV（特許属性: `id`, `class`, `date`） |
| 出力 | `ergm_input/arc_list.txt` | エッジリスト（EstimNetDirected 形式） |
| 出力 | `ergm_input/attributes.txt` | ノード属性（タブ区切り） |
| 出力 | `ergm_input/class_sim_binary.npy` | クラス一致バイナリ行列（密行列 bool） |
| 出力 | `ergm_input/class_sim_jaccard.npy` | Jaccard 類似度行列（密行列 float32） |
| 出力 | `ergm_input/model.cfg` | EstimNetDirected 設定ファイルのひな型 |
| キャッシュ | `ergm_input/_patent_attr_cache.pkl` | 特許属性インデックスの pickle キャッシュ |

---

## 処理フロー

```
data/*.csv  ──→  build_patent_index()  ──→  patent_index (dict)
                  └─ pickle キャッシュ              │
                     (_patent_attr_cache.pkl)       │
                                                    │
edge_list/<year>.csv  ──→  build_graph()            │
                               │                    │
                               │ node_list, edges   │
                               ▼                    │
                         Phase 1 ←──────────────────┘
                  build_node_attributes()
                               │ IsClass_D1..D99 + primary_class + n_classes + date
                               │
                         Phase 2
                  compute_class_similarities()
                      (転置インデックス)
                               │ binary_csr, jaccard_csr
                               │
                         Phase 3
                  export_arc_list()   → arc_list.txt
                  export_attributes() → attributes.txt
                  save_npz()          → *.npz
                               │
                         Phase 4
                  export_cfg()        → model.cfg
```

---

## Phase 1: ノード属性抽出

`data/*.csv` の `class` フィールドを解析し、各ノードに以下の属性を付与する。

### 多クラス対応パーサ `_extract_all_classes()`

元の `add_class_to_edge_list.py` はメインクラス（先頭1件）のみ抽出するが、
本スクリプトはカンマ区切りの**全クラスを抽出**してセットとして保持する。

| 入力形式 | 例 | 出力 |
|----------|-----|------|
| カンマ区切り複数クラス | `"D14422,D6100"` | `{"D14", "D6"}` |
| スペース入り1桁 | `"D 9"` | `{"D9"}` |
| 2桁クラス (D10-D34, D99) | `"D23366"` | `{"D23"}` |
| 1桁クラス (D1-D9) | `"D6..."` | `{"D6"}` |

### 出力ノード属性一覧

| 属性名 | 型 | 内容 |
|--------|-----|------|
| `primary_class` | カテゴリ | メインクラス（先頭）。例: `D14` |
| `n_classes` | 整数 | 保有クラス数（多様性スコア） |
| `date` | 文字列 | 特許日付（`data/*.csv` の `date` 列） |
| `IsClass_D1` … `IsClass_D99` | 0/1 | 各 D-class への所属フラグ（35 変数） |

---

## Phase 2: クラス類似度行列

2 種類の密行列を chunk + memmap 方式で計算して `.npy` として保存する。

### 計算方式

| ファイル | dtype | 計算式 | 論文対応 |
|---------|-------|--------|----------|
| `class_sim_binary.npy` | bool | 共通クラスがあれば True、なければ False | 論文式(6) OverlappingCategorization の直接実装 |
| `class_sim_jaccard.npy` | float32 | \|A ∩ B\| / \|A ∪ B\| | OverlappingCategorization の連続値拡張 |

### chunk + memmap による省メモリ計算

N×N を一括で RAM に載せずに、`--chunk-rows`（デフォルト 500）行ずつ処理する。

```
cls_vec (N×35 uint8) → cls_vec_i16 (N×35 int16)
chunk: cls_vec_i16[start:end] @ cls_vec_i16.T  →  inter (chunk×N int16)
union = n_cls[start:end] + n_cls - inter
jac_chunk = inter / union (float32)

→ np.memmap (tmp ファイル) に書き込み → flush 後に _save_npy_chunked で .npy 変換
```

ピーク RAM: `chunk_rows × N × 6 bytes`（inter int16 + union int16 + jac float32）  
例: chunk=500, N=22,000 → 約 **66 MB**（旧来の全行列確保方式 ~4.65 GB から大幅削減）

### メモリ監視

`psutil.virtual_memory()` で各 chunk の開始前に使用率を確認し、`--mem-limit`（デフォルト 0.80）を超えたら `MemoryError` で停止する。

---

## Phase 3: EstimNetDirected 用ファイル

### `arc_list.txt`

共引用ネットワークは**無向**なので、各エッジを双方向アークとして出力する。

```
0 1
1 0
2 3
3 2
...
```

ノード ID はアルファベット順ソートされた特許 ID のゼロ始まりインデックス。

### `attributes.txt`

ノード順（arc_list のインデックスと対応）のタブ区切りテーブル。
ヘッダー行あり。クラスが不明なノードは `primary_class=Unknown`、フラグ列はすべて 0。

```tsv
primary_class	n_classes	date	IsClass_D1	IsClass_D2	...	IsClass_D99
D14	1	1997-01-21	0	0	...	0
D6	2	2001-03-15	0	0	...	0
```

---

## Phase 4: 設定ファイルひな型 (`model.cfg`)

EstimNetDirected の設定ファイルを自動生成する。実際の推定前に
パス・パラメータを手動で調整すること。

```ini
; 主要エントリ（抜粋）
ArcListFile       = arc_list.txt
AttributesFile    = attributes.txt
PairAttributeFile = class_sim_jaccard.npy

Param_AltInStar     = 1    ; GWIDegree
Param_AltOutStar    = 1    ; GWODegree
Param_AltKTriangleT = 2    ; GWESP 推移性

ReceiverEffect = IsClass_D1 ... IsClass_D17   ; 35クラスを2行に分割
ReceiverEffect = IsClass_D18 ... IsClass_D99
SenderEffect   = IsClass_D1 ... IsClass_D17
SenderEffect   = IsClass_D18 ... IsClass_D99

Homophily      = primary_class          ; バイナリ Homophily
PairAttribute  = class_sim_jaccard.npy  ; 連続値 Homophily
```

---

## 実行方法

```bash
# 全年処理（2007–2010）、デフォルト出力先: ergm_input/
python build_ergm_input.py

# 指定年のみ
python build_ergm_input.py 2007 2008

# ノード数が多く類似度行列計算が重い場合はスキップ
python build_ergm_input.py --no-sim

# data/ を変更した場合はキャッシュを再構築
python build_ergm_input.py --rebuild

# 出力先を変更
python build_ergm_input.py --out-dir ./my_ergm
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `years` | 全年 | 処理する年（複数指定可） |
| `--edge-dir` | `/mnt/eightthdd/uspto/edge_list` | エッジリスト CSV のディレクトリ |
| `--data-dir` | `/mnt/eightthdd/uspto/data` | 特許属性 CSV のディレクトリ |
| `--out-dir` | `ergm_input` | 出力ディレクトリ |
| `--no-sim` | — | 類似度行列計算をスキップ |
| `--rebuild` | — | 特許属性キャッシュを再構築 |
| `--chunk-rows` | `500` | Phase 2 の chunk サイズ（行数） |
| `--mem-limit` | `0.80` | RAM 使用率の上限（超えたら停止） |

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [citation_graph.md](citation_graph.md) | `build_ergm_input.py` | EstimNetDirected での ERGM 推定 |
| `edge_list/<year>.csv` | → `ergm_input/arc_list.txt` など | `EstimNetDirected` / `ergm` |
| `data/<year>.csv` | → `ergm_input/attributes.txt` | — |

- `add_class_to_edge_list.py`（STEP 2c）と同じ `data/*.csv` を参照するが、
  出力形式・目的が異なる独立したサイドブランチ
- Phase 2 の `_extract_all_classes()` は `add_class_to_edge_list.py` の
  `extract_main_class()` を多クラス対応に拡張したもの

パイプライン全体の位置付けは [pipeline.md](pipeline.md) を参照。

---

## 後続分析・可視化

`ergm_input/` に保存された各ファイルを使って実施できる分析と描画の一覧。

### 記述統計・可視化（前処理なしで実行可能）

#### `attributes.txt` を使うグラフ

| グラフ | 使用列 | 内容 |
|--------|--------|------|
| **D-class 別ノード数棒グラフ** | `primary_class` | 各クラスの特許件数分布 |
| **`n_classes` 分布ヒストグラム** | `n_classes` | 複数クラス所属の特許の割合 |
| **年代別ノード数の時系列折れ線** | `date` | ネットワーク成長の推移 |

```python
import pandas as pd
attrs = pd.read_csv("ergm_input/attributes.txt", sep="\t")
attrs["primary_class"].value_counts().plot(kind="bar")   # クラス分布
attrs["n_classes"].hist()                                 # 多様性スコア分布
```

#### `arc_list.txt` + `attributes.txt` を組み合わせたグラフ

| グラフ | 内容 |
|--------|------|
| **クラス間共引用ヒートマップ（35×35）** | `primary_class` でノードをグループ化し、クラス間エッジ数を行列表示。対角成分が大きければ Homophily が強い |
| **次数分布（PDF / CCDF）** | `arc_list.txt` から無向次数を集計（`plot_indegree.py` と同等、クラス別に色分け可能） |
| **ネットワーク可視化** | `networkx` のスプリング配置でノードを D-class ごとに色分け、ノードサイズを次数に対応 |

#### `class_sim_jaccard.npy` を使うグラフ

| グラフ | 内容 |
|--------|------|
| **Jaccard 値のヒストグラム** | ほとんどのペアが 0 に集中する分布を確認 |
| **Jaccard ≥ 閾値のサブグラフ** | 類似度の高いペアだけ抽出した類似度グラフ |

```python
import numpy as np
# mmap_mode='r' でディスク上の行列を RAM に全載せせず参照
jac = np.load("ergm_input/class_sim_jaccard.npy", mmap_mode="r")
# 非ゼロ要素（共通クラスを持つペア）だけ取り出す場合
nonzero_vals = jac[jac > 0]
```

---

### ERGM 推定（メイン分析）

EstimNetDirected に `model.cfg` を渡して推定し、各係数を解釈する。

```bash
EstimNetDirected model.cfg
```

#### 係数の解釈

| 係数 | 正の場合の意味 |
|------|--------------|
| `ReceiverEffect(IsClass_D14)` | IT機器デザインは他のペアから共引用されやすい |
| `SenderEffect(IsClass_D12)` | 輸送機器デザインは多くのペアと共引用する傾向 |
| `ReceiverEffect(n_classes)` | 複数クラス所属の特許ほど共引用ターゲットになりやすい |
| `Homophily(primary_class)` | 同一 D-class の特許同士が共引用されやすい（類似分野の設計参照） |
| `PairAttribute(class_sim_jaccard)` | Jaccard 類似度が高いペアほど共引用確率が高い |
| `Param_AltKTriangleT`（GWESP） | 推移的閉包（A–B, B–C → A–C）がランダム期待より多い |

---

### Gemini 類似判定との突合（プロジェクト統合分析）

`similarity_results/*.jsonl`（STEP 3 出力）と `attributes.txt` を結合することで、以下を検証できる。

| 問い | 使用データ |
|------|-----------|
| Gemini が「視覚的に類似」と判定したペアは同一 D-class に偏るか | `similarity=Yes` レコード × `primary_class` |
| Jaccard 類似度が高いペアと `similarity=Yes` の一致率 | `class_sim_jaccard.npz` × `similarity` |
| クラス内 / クラス間での `confidence` スコアの分布差 | `confidence` × `primary_class` の組み合わせ |

> **視覚的類似（Gemini）と分類的類似（Jaccard）が乖離するケースを特定**することが、このプロジェクト固有の知見となる。

---

### 分析の優先順位

| 優先度 | 分析 | 必要ファイル |
|--------|------|------------|
| 1（確認用） | クラス分布・ヒートマップ | `attributes.txt`, `arc_list.txt` |
| 2（ERGM 前提） | 記述統計で density / degree 確認 | `attributes.txt`, `arc_list.txt` |
| 3（本命） | EstimNetDirected で ERGM 推定 | `model.cfg` 一式 |
| 4（統合） | Gemini Yes ペアと ERGM 結果の突合 | `similarity_results/`, `attributes.txt` |

---

## 分析スクリプト `analyze_ergm.py`

`ergm_input/` の出力を対象に、上記の優先度 1–4 を一括実行するスクリプト。

```
/home/sonozuka/design_similarity/analyze_ergm.py
```

### 出力ファイル一覧

| ファイル | 優先度 | 内容 |
|---------|--------|------|
| `output/priority1_class_dist.png` | 1 | D-class 別ノード数棒グラフ |
| `output/priority1_n_classes_hist.png` | 1 | n_classes 分布ヒストグラム |
| `output/priority1_date_timeline.png` | 1 | 年代別ノード数折れ線 |
| `output/priority1_cocite_heatmap.png` | 1 | クラス間共引用ヒートマップ（35×35） |
| `output/priority2_degree_dist.png` | 2 | 次数分布（無向・In・Out の PDF+CCDF、対数軸） |
| `output/priority2_network_stats.png` | 2 | Transitivity / Reciprocity / Betweenness 棒グラフ（論文 Table 6 比較） |
| `output/priority2_descriptive.csv` | 2 | 記述統計サマリ（Table 6 完全対応） |
| `output/priority2_triangle_twopath.csv` | 2 | ERGM 収束診断用 triangle/two-path 統計 |
| `output/priority3_ergm_coefs.png` | 3 | ERGM 係数フォレストプロット |
| `output/priority4_gemini_vs_class.png` | 4 | Gemini Yes/No のクラス分布比較 |
| `output/priority4_jaccard_vs_sim.png` | 4 | Jaccard 類似度 vs Gemini 判定（箱ひげ図） |
| `output/phase4_smallworld.png` | SW | Small-World λ / γ 可視化（論文比較） |
| `output/phase4_smallworld.csv` | SW | Small-World 指標（λ, γ, σ, L_real, C_real 等） |
| `output/analysis_summary.csv` | — | 全分析の数値サマリ |

各 PNG には `.meta.json`（caption / description）が付随する。

### 実行方法

```bash
# デフォルト（全分析）
python analyze_ergm.py

# 記述統計のみ高速実行（P3/P4/Small-World をスキップ）
python analyze_ergm.py --skip-p3 --skip-p4 --skip-sw

# Betweenness の精度を上げる（時間と精度のトレードオフ）
python analyze_ergm.py --betweenness-k 1000

# ER null model の試行数を増やす（Small-World 結果の安定化）
python analyze_ergm.py --er-samples 10

# ER 解析近似のみ（シミュレーションなし、高速）
python analyze_ergm.py --er-samples 0

# 出力先を変更
python analyze_ergm.py --out-dir ./my_output
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--ergm-dir` | `ergm_input` | `build_ergm_input.py` の出力ディレクトリ |
| `--sim-dir` | `/mnt/eightthdd/uspto/similarity_results` | Gemini 判定 JSONL のディレクトリ |
| `--out-dir` | `output` | グラフ・CSV の出力先 |
| `--betweenness-k` | `200` | Betweenness 近似の BFS ソース数（大きいほど精度向上） |
| `--er-samples` | `5` | Small-World の ER ランダムグラフ試行数（0=解析近似のみ） |
| `--skip-p3` | — | 優先度3（ERGM係数可視化）をスキップ |
| `--skip-p4` | — | 優先度4（Gemini突合）をスキップ |
| `--skip-sw` | — | Small-World 検証をスキップ |

### 論文 Table 6 対応指標

`priority2_descriptive.csv` に出力される指標と Chakraborty et al. (2020) の参考値:

| 指標 | 論文参考値 | 実装 |
|------|----------|------|
| Density | — | `2M / (N(N-1))` |
| Mean degree | — | `undir_deg.mean()` |
| Transitivity | 0.005 | `3 × triangles / connected_triples`（エッジ共通隣接数ベース） |
| Reciprocity | 0.001 | `bidirectional_arcs / total_arcs` |
| Mean Betweenness | 8.29e-06 | Brandes k-sample 近似（`--betweenness-k` で調整） |

### Small-World 検証（`phase4_small_world()`）

Watts-Strogatz (1998) に基づく Small-World 指標を計算する。

```
λ = C_real / C_ER     （クラスタリング比）
γ = L_real / L_ER     （平均最短路長比）
σ = λ / γ             （Small-World index; σ >> 1 ならば Small-World）
```

| 量 | 計算方法 |
|----|---------|
| `C_real` | 実ネットワークの Transitivity（全体） |
| `L_real` | LCC 内 BFS サンプリング（500 ノードから平均） |
| `C_ER` | `2M / (N(N-1))` = 密度（ER の解析的期待値） |
| `L_ER` | ER ランダムグラフ `G(N_lcc, M_lcc)` を `--er-samples` 回生成し BFS 平均、または `ln(N)/ln(k_avg)` 近似 |

論文参考値: λ=0.897, γ=2.346 → σ≈0.382 (NOT Small-World)

### ERGM 収束診断（`priority2_triangle_twopath.csv`）

EstimNetDirected の `AltKTriangleT`（GWESP）・`AltTwoPathsTD`（GWDSP）が収束しない場合の原因特定に使用する。

| 指標 | 内容 |
|------|------|
| `n_triangles` | 実ネットワーク内の三角形数 |
| `n_connected_triples` | 連結三つ組数（次数 ≥ 2 のノード中心） |
| `triangle_to_triple_ratio` | `3 × n_triangles / n_connected_triples`（= Transitivity） |
| `n_two_paths_directed` | 有向2パス数（`u→w→v` の形） |
| `two_path_per_arc` | アーク1本あたりの平均2パス数 |

### 優先度4の特許ID解決

`similarity_results/*.jsonl` の `source`/`target` フィールドは特許ID文字列（例: `D0535736`）。  
`attributes.txt` には `patent_id` 列がないため、`_patent_attr_cache.pkl` からクラス情報を直接引く。

- **P4a（クラス分布比較）**: `_patent_attr_cache.pkl` があれば実行可能
- **P4b（Jaccard vs Gemini）**: `_patent_attr_cache.pkl` のソート済みキーをノード順として使用（build_ergm_input.py と同じ `sorted()` 適用）

### 必要ライブラリ

```
numpy pandas plotly kaleido psutil
```

`kaleido` は Plotly の静止画 PNG 書き出しに必要。
