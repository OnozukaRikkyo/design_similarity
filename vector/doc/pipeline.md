# クラス別ベクトル検索パイプライン

意匠特許クラス単位で引用ペアを絞り込み、画像ベクトルを生成・保存するパイプライン。  
`--class` 引数でクラスを切り替えるだけで任意のクラスに適用できる。

---

## ディレクトリ構成

```
/home/sonozuka/design_similarity/vector/
  run_pipeline.py            ← パイプライン一括実行（Step 1〜5）
  filter_pairs_by_class.py   ← Step 1: クラス別ペア抽出
  build_class_vectors.py     ← Step 2: 画像ベクトル生成
  build_rank_index.py        ← Step 3: 全件ベクトル結合・L2正規化
  compute_ranks.py           ← Step 4: ベクトルランク検索
  join_judgments.py          ← Step 5: ランク結果と LLM 判定を結合
  analysis/
    rank_analysis.py         ← CCDF・散布図・ペア比較画像の生成
    export_yes_reasons.py    ← Yes ペアを CSV にエクスポート
    export_non_exact_pairs.py← 完全一致でない Yes ペアの画像を出力
  doc/
    pipeline.md              ← このファイル
    filter_pairs_by_class.md
    build_class_vectors.md
    build_rank_index.md
    compute_ranks.md
    join_judgments.md        ← Step 5 の詳細・更新手順
    analysis.md              ← vector/analysis/ スクリプト群
```

---

## データフロー

```
[共通データ（全クラス）]
/mnt/eightthdd/uspto/
  cited_image_pairs/{year}.jsonl      ← 全クラスの引用ペア
  edge_list_with_class/{year}.csv     ← 特許のクラス情報
  cited_image_vectors/{type}/         ← 全クラスの既存ベクトル（2007〜2022）

        ↓ Step 1: filter_pairs_by_class.py --class {CLASS}

[クラス別データ]
/mnt/eightthdd/uspto/class/{CLASS}/
  cited_image_pairs/{year}.jsonl      ← 指定クラスのペアのみ

        ↓ Step 2: build_class_vectors.py --class {CLASS}
          （cited_image_vectors/ を最大限再利用）

  cited_image_vectors/
    perspective/
      patent_ids_{year}.npy           ← shape (N,) int64
      vectors_{year}.npy              ← shape (N, 2048) float32
      file_paths_{year}.txt
    front/
    overview/

        ↓ Step 3: build_rank_index.py --class {CLASS}
          （全年を結合・重複排除・L2正規化）

  rank_index/
    perspective/
      patent_ids.npy                  ← shape (N,) int64  ユニーク特許
      vectors_l2norm.npy              ← shape (N, 2048) float32  L2正規化済み
      file_paths.txt
    front/
    overview/

        ↓ Step 4: compute_ranks.py --class {CLASS}
          （各ペアで A→全件検索し B の順位を取得）

  rank_results/
    {sim_func}/                       ← cosine_numpy / cosine_faiss
      {year}.jsonl                    ← 1行 = 1 (ペア×タイプ) レコード
                                         フィールド: source, target, type, rank,
                                                     n_candidates, similarity,
                                                     source_image, target_image

        ↓ Step 5: join_judgments.py --class {CLASS} --sim {sim_func}
          （ランク結果・LLM 判定を結合して一括保存）
          ※ LLM 判定は qwen_similarity_results/{year}.jsonl から取得
          ※ 画像パスは rank_results から引き継ぐ（cited_image_pairs を再読み込みしない）
          ※ qwen_similarity_results/ は run_pipeline.py 外の judge_cited_pairs.py が生成

  rank_judgments/
    {sim_func}/
      all.jsonl                       ← 全年・全タイプ結合（1行 = 1 ペア×タイプ）
                                         追加フィールド: judgment, confidence, reason,
                                                         source_image, target_image

        ↓ vector/analysis/ スクリプト群（resume なし・常に上書き）
          rank_analysis.py / export_yes_reasons.py / export_non_exact_pairs.py

  vector/output/{CLASS}/{sim_func}/
    rank_ccdf_{type}.png
    rank_scatter_{type}.png           ← Similar=Yes / Non-similar=No（judgment フィールド）
    rank_scatter_{type}_zoom.png
  rank_analysis/{sim_func}/{type}/
    pair_comparison/
    non_exact_pairs/
```

### 複数クラスを扱う場合

クラスごとに独立したサブディレクトリに格納されるため、互いに干渉しない。

```
/mnt/eightthdd/uspto/class/
  D18/
    cited_image_pairs/
    cited_image_vectors/
    rank_index/
    rank_results/
  D10/      ← 同じスクリプトを --class D10 で実行するだけで追加される
    cited_image_pairs/
    cited_image_vectors/
    rank_index/
    rank_results/
  D5/
    ...
```

---

## 前提条件（実行前に必要な前処理）

`run_pipeline.py`（Step 1〜5）を実行する前に、以下の 3 ディレクトリが揃っていること。

### 前提データの現状（2026-05-18 確認済み）

| ディレクトリ | 対応年 | 状態 |
|---|---|:---:|
| `cited_image_pairs/{year}.jsonl` | 2007〜2022 | ✓ |
| `edge_list_with_class/{year}.csv` | 2007〜2022 | ✓ |
| `cited_image_vectors/{type}/` | 2007〜2022（D18 カバー率 100%） | ✓ |

### 新しい年が追加されたとき

`edge_list_with_class/` は `add_class_to_edge_list.py` を手動で実行しないと更新されない。  
Step 1 がその年をスキップした場合は以下を確認・実行すること。

```bash
# edge_list_with_class/ の生成済み年を確認
ls /mnt/eightthdd/uspto/edge_list_with_class/

# 不足年を生成（例: 2023 年が追加された場合）
cd /home/sonozuka/design_similarity
python add_class_to_edge_list.py 2023
```

---

## 実行手順

### 一括実行（推奨）

**すべての実行は `update_downstream.py` で行う。** `vector/run_pipeline.py` は使わない。

```bash
cd /home/sonozuka/design_similarity

# 通常の更新（qwen_similarity_results/ が進んだとき）
python update_downstream.py

# 新クラス・新年追加時（ベクトルインデックスから再構築 + 全下流更新）
python update_downstream.py --with-vector --no-gpu --class D18

# 別クラス（D10）を新規追加する場合
python update_downstream.py --with-vector --no-gpu --class D10
```

| オプション | 説明 |
|---|---|
| `--class CLASS` | 対象クラスコード（デフォルト: D18） |
| `--with-vector` | ベクトルインデックス再構築（Step V1〜V4）を先頭に追加 |
| `--no-gpu` | V2（build_class_vectors）で GPU を使わない |
| `--with-graph` | グラフ解析（Step K〜M）を末尾に追加 |
| `--from-step STEP` | 指定ステップ以降を連続実行 |
| `--steps STEP ...` | 実行するステップを個別指定 |

---

## データ量（2026-05-18 実行済み）

### D18ペア件数（年別）

| 年 | D18ペア数 |
|----|----------:|
| 2007 | 103 |
| 2008 |  54 |
| 2009 |  46 |
| 2010 |  50 |
| 2011 |  53 |
| 2012 |  65 |
| 2013 | 191 |
| 2014 |  72 |
| 2015 |  79 |
| 2016 | 189 |
| 2017 | 120 |
| 2018 | 258 |
| 2019 |  93 |
| 2020 |  56 |
| 2021 |  35 |
| 2022 |  66 |
| **合計** | **1,530** |

### ベクトル（D18）

| データ | 件数 |
|--------|------|
| cited_image_vectors ユニーク件数（perspective） | 959件 |
| cited_image_vectors ユニーク件数（front） | 12件 |
| cited_image_vectors ユニーク件数（overview） | 59件 |
| 既存ベクトルカバー率 | 100%（新規推論なし） |
| ベクトル次元 | 2,048（Qwen3-VL-Embedding-2B） |

---

## ストレージ

| パス | 内容 |
|------|------|
| `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/` | クラス別ペアJSONL |
| `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_vectors/` | クラス別ベクトル（perspective/front/overview） |

---

## judge_cited_pairs.py 更新後の下流データ更新

→ **[UPDATE.md](../../UPDATE.md)（最初に読むべきガイド）**

```bash
cd /home/sonozuka/design_similarity
python update_downstream.py       # 通常の更新（qwen_similarity_results/ が進んだとき）
python update_downstream.py --with-vector --no-gpu  # ベクトルインデックスから再構築
```

`update_downstream.py` がすべての下流処理（Step G〜F と分析図）を一括で実行する。
Step 1〜4（`vector/run_pipeline.py`）は新クラス・新年追加時のみ必要で、通常の更新には不要。

---

### 整合性チェック

```bash
python3 -c "
import numpy as np
from pathlib import Path

CLASS = 'D18'
OUT = Path(f'/mnt/eightthdd/uspto/class/{CLASS}/cited_image_vectors')
for vtype in ('perspective', 'front', 'overview'):
    vdir = OUT / vtype
    for npy in sorted(vdir.glob('vectors_*.npy')):
        v    = np.load(npy)
        ids  = np.load(str(npy).replace('vectors_', 'patent_ids_'))
        txt  = npy.with_name(npy.name.replace('vectors_', 'file_paths_').replace('.npy', '.txt'))
        n_txt = len(txt.read_text().splitlines()) if txt.exists() else -1
        ok = '✓' if len(ids) == len(v) == n_txt else '✗'
        print(f'{ok} {vtype}/{npy.name}: ids={len(ids)} vecs={len(v)} files={n_txt}')
"
```

---

## 上流パイプラインとの関係

### スクリプト一覧

| スクリプト | 役割 | ドキュメント |
|-----------|------|------------|
| `build_edge_list.py` | 共引用エッジリスト構築 | [citation_graph.md](../../doc/citation_graph.md) |
| `extract_cited_image_pairs.py` | 全クラスペアJSONLを生成 | [image_pairs.md](../../doc/image_pairs.md) |
| `add_class_to_edge_list.py` | エッジリストにクラス情報を付与 | [edge_list_with_class.md](../../doc/edge_list_with_class.md) |
| `build_cited_image_vectors.py` | 全クラスのベクトルを生成 | [cited_image_vectors.md](../../../image_vector/doc/cited_image_vectors.md) |
| **`filter_pairs_by_class.py`** | **Step 1: クラス別ペア抽出** | [filter_pairs_by_class.md](filter_pairs_by_class.md) |
| **`build_class_vectors.py`** | **Step 2: クラス別ベクトル生成** | [build_class_vectors.md](build_class_vectors.md) |
| **`build_rank_index.py`** | **Step 3: 全件インデックス構築** | [build_rank_index.md](build_rank_index.md) |
| **`compute_ranks.py`** | **Step 4: ベクトルランク検索** | [compute_ranks.md](compute_ranks.md) |
| **`join_judgments.py`** | **Step 5: ランク結果と LLM 判定の結合** | [join_judgments.md](join_judgments.md) |
| `analysis/rank_analysis.py` | CCDF・散布図・ペア比較画像の生成 | [analysis.md](analysis.md) |
| `analysis/export_yes_reasons.py` | Yes ペアを CSV にエクスポート | [analysis.md](analysis.md) |
| `analysis/export_non_exact_pairs.py` | 完全一致でない Yes ペアの画像を出力 | [analysis.md](analysis.md) |

---

### 前提入力の依存関係

本パイプライン（Step 1〜5）は以下の 3 ディレクトリを前提とする。
それぞれを生成するスクリプトと、さらにその上流の依存関係を示す。

```
【生データ（変更不可）】
  /mnt/eightthdd/uspto/json/{year}.json    ← USPTO 引用データ
  /mnt/eightthdd/uspto/data/{year}.csv     ← 特許属性・画像パス
  /mnt/eightthdd/impact/images/{year}/     ← 特許画像 TIF
          │
          ▼ build_edge_list.py
            /home/sonozuka/design_similarity/build_edge_list.py
          │
          ▼ edge_list/{year}.csv
          │
          ├──▶ extract_cited_image_pairs.py ─────────────────────────────────▶ cited_image_pairs/{year}.jsonl
          │      /home/sonozuka/design_similarity/                                 ★ Step 1 の入力
          │      （image_index.py 経由で data/ を参照）
          │
          ├──▶ add_class_to_edge_list.py ────────────────────────────────────▶ edge_list_with_class/{year}.csv
          │      /home/sonozuka/design_similarity/                                 ★ Step 1 の入力
          │      （data/ を参照）
          │
          └──▶ cited_image_pairs/{year}.jsonl
                        │
                        ▼ build_cited_image_vectors.py
                          /home/sonozuka/image_vector/   ← 別ディレクトリ
                          venv: /home/sonozuka/multimodal/venv/
                          GPU 必須（Qwen3-VL-Embedding-2B）
                        │
                        ▼ cited_image_vectors/{type}/    ← ★ Step 2 の参照元
```

---

### 前提スクリプトの実行方法

#### 1. 共引用エッジリスト構築

```bash
cd /home/sonozuka/design_similarity
python build_edge_list.py
# 出力: /mnt/eightthdd/uspto/edge_list/{year}.csv
```

#### 2. 全クラスペア JSONL 生成（cited_image_pairs/）

```bash
cd /home/sonozuka/design_similarity
python extract_cited_image_pairs.py          # 全年
python extract_cited_image_pairs.py 2015     # 指定年のみ
python extract_cited_image_pairs.py --rebuild # 画像インデックスを再構築
# 出力: /mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl
```

#### 3. クラス付きエッジリスト生成（edge_list_with_class/）

```bash
cd /home/sonozuka/design_similarity
python add_class_to_edge_list.py
# 出力: /mnt/eightthdd/uspto/edge_list_with_class/{year}.csv
```

> **現状（2026-05-25 確認済み）**: 2007〜2022 全年生成済み。

#### 4. 全クラスベクトル生成（cited_image_vectors/）

```bash
cd /home/sonozuka/image_vector
/home/sonozuka/multimodal/venv/bin/python build_cited_image_vectors.py       # 全年
/home/sonozuka/multimodal/venv/bin/python build_cited_image_vectors.py 2015  # 指定年のみ
# 出力: /mnt/eightthdd/uspto/cited_image_vectors/{type}/
# GPU 必須（Qwen3-VL-Embedding-2B）
```

> **D18 の場合**: `cited_image_vectors/` は既に全年分のデータが存在し、
> `build_class_vectors.py` のカバー率が 100% のため GPU 不要（`--no-gpu` で完結）。

---

### 前提データの所在まとめ

| ディレクトリ | 生成スクリプト | スクリプトの場所 | GPU |
|---|---|---|:---:|
| `edge_list/{year}.csv` | `build_edge_list.py` | `design_similarity/` | 不要 |
| `cited_image_pairs/{year}.jsonl` | `extract_cited_image_pairs.py` | `design_similarity/` | 不要 |
| `edge_list_with_class/{year}.csv` | `add_class_to_edge_list.py` | `design_similarity/` | 不要 |
| `cited_image_vectors/{type}/` | `build_cited_image_vectors.py` | `/home/sonozuka/image_vector/` | **必須** |

---

## 関連ドキュメント

本ファイルはベクトル検索パイプライン（Step 1〜5）のみを扱う。  
上流・分析・PMS パイプラインとの全体的な関係は以下を参照。

- [**../../doc/architecture.md**](../../doc/architecture.md) — 全パイプラインの設計・接続点・ストレージ構成
