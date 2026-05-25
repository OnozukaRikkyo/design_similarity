# システム全体設計

USPTO 意匠特許データから「引用ペアの視覚的類似度」を定量化するまでの全パイプライン概要。

---

## パイプライン一覧

| スクリプト | 役割 | 実行環境 |
|---|---|---|
| `design_similarity/run_pipeline.py` | **上流パイプライン**（エッジ構築・LLM 判定） | 本ディレクトリ |
| `design_similarity/update_downstream.py` | **下流一括更新**（ベクトル検索・分析・集計・グラフ解析） | 本ディレクトリ |
| `image_vector/build_cited_image_vectors.py` | **全クラスベクトル生成**（GPU 必須・前提作業） | `/home/sonozuka/image_vector/` |
| `vector/reasoning/` 各スクリプト | **PMS パイプライン**（類似判定根拠の定量評価） | 本ディレクトリ |

> **更新コマンドは `update_downstream.py` に一本化されている。**  
> `qwen_similarity_results/` が進んだときは `python update_downstream.py` だけを実行する。  
> `vector/run_pipeline.py` は `update_downstream.py --with-vector` に統合済みで直接使わない。

---

## 全体フロー図

```
【生データ】
  /mnt/eightthdd/uspto/json/{year}.json      ← USPTO 引用データ
  /mnt/eightthdd/uspto/data/{year}.csv       ← 特許属性・画像パス索引
  /mnt/eightthdd/impact/images/{year}/       ← 特許画像 TIF

          │
          ▼ STEP 1: build_edge_list.py
  edge_list/{year}.csv                       ← 共引用エッジリスト

          │                         │
          ▼ STEP 2a                 ▼ STEP 2c
  extract_cited_image_pairs.py     add_class_to_edge_list.py
          │                         │
          ▼                         ▼
  cited_image_pairs/{year}.jsonl   edge_list_with_class/{year}.csv
  （全クラス・画像パス付き）        （クラス情報付きエッジリスト）
          │    │
          │    │ ◀─── GPU サーバー（別 venv）
          │    ▼ image_vector/build_cited_image_vectors.py
          │  cited_image_vectors/{type}/        ← 全クラスベクトル（前提）
          │
          ▼ STEP 3: judge_cited_pairs.py
  qwen_similarity_results/{year}.jsonl        ← 全クラス LLM 判定（Yes/No）
  ★ 全クラスのペアを処理する（D18 以外も含む）
  ★ run_pipeline.py には含まれない（手動実行）

─────────── 上流パイプライン ここまで ───────────────────────────────────────

          cited_image_pairs/{year}.jsonl    ← ★ 橋渡しデータ（1）
          edge_list_with_class/{year}.csv   ← ★ 橋渡しデータ（2）
          cited_image_vectors/{type}/       ← ★ 橋渡しデータ（3）
          qwen_similarity_results/{year}.jsonl ← ★ 橋渡しデータ（4）

─────────── ベクトル検索パイプライン（update_downstream.py --with-vector）──────

          ▼ Step 1: filter_pairs_by_class.py --class D18
  class/D18/cited_image_pairs/{year}.jsonl   ← D18 ペアのみ

          ▼ Step 2: build_class_vectors.py --class D18
  class/D18/cited_image_vectors/{type}/      ← D18 ベクトル（全クラス版からコピー）
  ※ GPU なし（--no-gpu）で完結（D18 は cited_image_vectors/ 100% カバー済み）

          ▼ Step 3: build_rank_index.py --class D18
  class/D18/rank_index/{type}/               ← 全年結合・重複排除・L2 正規化
    patent_ids.npy / vectors_l2norm.npy      ← D18 perspective: 959 件

          ▼ Step 4: compute_ranks.py --class D18
  class/D18/rank_results/cosine_numpy/{year}.jsonl
    source, target, type, rank, n_candidates, similarity,
    source_image, target_image

          ▼ Step 5: join_judgments.py --class D18
  class/D18/rank_judgments/cosine_numpy/all.jsonl
    （rank_results + qwen 判定を結合。1530 件・全年 n_candidates=958）

─────────── 分析 ─────────────────────────────────────────────────────────────

          ▼ update_downstream.py（Step H: vector/analysis/rank_analysis.py）
  vector/output/D18/cosine_numpy/
    sim_histogram_perspective.png
    rank_ccdf_perspective.png
    rank_scatter_perspective.png
    high_sim_perspective_0950_judged.csv     ← ★ PMS への橋渡し

─────────── PMS パイプライン（vector/reasoning/）────────────────────────────

          ▼ extract_pilot.py → patent_rationale_pms.py
            patent_visual_probes.py → merge_results.py → analyze_results.py
  vector/output/D18/cosine_numpy/reasoning/
    unified_results.csv / fig_*.png          ← 論文図・仮説検定
```

---

## 橋渡しデータ（パイプライン間の接続点）

| データ | 生成元 | 参照先 |
|--------|--------|--------|
| `cited_image_pairs/{year}.jsonl` | `extract_cited_image_pairs.py`（上流 STEP 2a） | `filter_pairs_by_class.py`（ベクトル Step 1）、`judge_cited_pairs.py`（上流 STEP 3） |
| `edge_list_with_class/{year}.csv` | `add_class_to_edge_list.py`（上流 STEP 2c） | `filter_pairs_by_class.py`（ベクトル Step 1） |
| `cited_image_vectors/{type}/` | `build_cited_image_vectors.py`（GPU・別リポジトリ） | `build_class_vectors.py`（ベクトル Step 2） |
| `qwen_similarity_results/{year}.jsonl` | `judge_cited_pairs.py`（上流 STEP 3） | `join_judgments.py`（ベクトル Step 5） |
| `high_sim_perspective_0950_judged.csv` | `rank_analysis.py`（分析） | `extract_pilot.py`（PMS Step 0） |

---

## ストレージ構成

```
/mnt/eightthdd/uspto/
  json/                            ← 生データ
  data/                            ← 生データ
  edge_list/                       ← 上流 STEP 1 出力
  cited_image_pairs/               ← 上流 STEP 2a 出力（全クラス）
  edge_list_with_class/            ← 上流 STEP 2c 出力
  cited_image_vectors/{type}/      ← GPU ベクトル生成出力（全クラス）
  qwen_similarity_results/         ← 上流 STEP 3 出力（全クラス LLM 判定）
  similarity_results/              ← 上流 STEP 3 出力（BACKEND=gemini 時）
  yes_pair/                        ← 上流 STEP 4 出力
  class/
    D18/
      cited_image_pairs/           ← ベクトル Step 1 出力（D18 のみ）
      cited_image_vectors/         ← ベクトル Step 2 出力（D18 ベクトルのコピー）
      rank_index/                  ← ベクトル Step 3 出力（L2 正規化済み）
      rank_results/                ← ベクトル Step 4 出力
      rank_judgments/              ← ベクトル Step 5 出力（分析の起点）
    D10/                           ← 同構造（--class D10 で追加）
    D5/
      ...

/home/sonozuka/
  design_similarity/               ← 本リポジトリ
    run_pipeline.py                ← 上流パイプライン（STEP 1〜4）
    update_downstream.py           ← 下流一括更新（通常はこれだけ実行）
    vector/
      analysis/                    ← 分析スクリプト群
      reasoning/                   ← PMS パイプライン
  image_vector/                    ← GPU ベクトル生成（別リポジトリ）
    build_cited_image_vectors.py
  multimodal/venv/                 ← image_vector/ 専用 venv（GPU 環境）
```

---

## 実行順序

### 初回セットアップ（全クラス共通の前提作業）

```bash
# 1. 上流パイプライン（エッジ構築・LLM 判定）
cd /home/sonozuka/design_similarity
python run_pipeline.py                        # STEP 1〜2a・2c
python judge_cited_pairs.py                  # STEP 3（時間がかかる・手動実行）

# 2. GPU ベクトル生成（別リポジトリ・別 venv）
cd /home/sonozuka/image_vector
/home/sonozuka/multimodal/venv/bin/python build_cited_image_vectors.py
```

### クラス別分析（D18 の例、初回セットアップ）

```bash
cd /home/sonozuka/design_similarity

# ベクトルインデックス構築 + 全下流更新
python update_downstream.py --with-vector --no-gpu --class D18

# PMS パイプライン（高類似度ペアのみ、必要に応じて）
cd vector/reasoning
python extract_pilot.py
python patent_rationale_pms.py
python patent_visual_probes.py --module m5
python patent_visual_probes.py --module baseline
python merge_results.py
python analyze_results.py
```

### LLM 判定が進んだときの更新（通常の更新）

```bash
cd /home/sonozuka/design_similarity
python update_downstream.py   # これだけ
```

---

## 設計上の注意点

### 1. ベクトルの二重保存

`cited_image_vectors/`（全クラス）の D18 分が `class/D18/cited_image_vectors/` にコピーされる。
`build_rank_index.py` がクラス別フォルダのみを参照する設計のため現状は必要。
D18 perspective で約 7.8 MB（959 件 × 2048 次元 × 4 bytes）が二重に存在する。

### 2. LLM 判定が全クラス対象

`judge_cited_pairs.py` は全クラス混在の `cited_image_pairs/` を処理する（1年あたり数千〜1万件）。
ベクトル検索パイプラインが使うのはそのうち D18 分のみ（1年あたり数十〜数百件）。
別クラスを分析するとき LLM 判定を再利用できる設計のため、意図的な広範囲処理。

### 3. 下流更新は `update_downstream.py` に一本化

`qwen_similarity_results/` が更新されたときは `python update_downstream.py` だけを実行する。  
ベクトルインデックス再構築が必要なとき（新クラス・新年）は `--with-vector` を追加する。  
`vector/run_pipeline.py` は廃止扱いで直接使わない。

### 5. レコード数がインデックス件数を超える理由

`rank_results` のレコード数（D18 perspective: 1,447件）は rank_index の特許数（959件）より多いが、これは正常。

- **インデックス件数（959）** = ユニーク特許数（グラフの**節点**数）
- **レコード数（1,447）** = 引用ペア数（グラフの**辺**数）

同一の特許が複数のペアの source または target として登場するため、辺の数が節点数を超える。
D18 perspective では source∪target のユニーク特許数がちょうど 959件で rank_index 全件と一致する。

---

### 4. `n_candidates` の統一（2026-05-23 修正済み）

2007〜2014 年の rank_results が旧インデックス（457 件、n_candidates=456）で計算されたまま
2015〜2022 年（n_candidates=958）と混在していた。
全年を `--no-resume` で再計算し、perspective は全年 n_candidates=958 に統一済み。

---

## ドキュメント一覧

| ドキュメント | 内容 |
|---|---|
| **`doc/architecture.md`**（本ファイル） | 全体設計・パイプライン間の関係 |
| `doc/pipeline.md` | 上流パイプライン詳細（STEP 1〜6） |
| `vector/doc/pipeline.md` | ベクトル検索パイプライン詳細（Step 1〜5） |
| `vector/analysis/doc/pipeline.md` | 分析スクリプト群の処理順序 |
| `vector/reasoning/doc/pipeline.md` | PMS パイプライン詳細 |
| `judge_cited_pairs_downstream.md` | LLM 判定更新後の下流更新手順 |
| `vector/doc/compute_ranks.md` | Step 4 詳細・出力スキーマ |
| `vector/doc/join_judgments.md` | Step 5 詳細・更新手順 |
