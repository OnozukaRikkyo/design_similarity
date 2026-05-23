# Yes 判定ペアの抽出・可視化 (`extract_yes_pairs.py`)

`qwen_similarity_results/` の JSONL から `similarity=Yes` のレコードを抽出し、
JSONL ファイルと画像ペアを保存する。パイプラインの最終ステップ。

---

## スクリプト

```
/home/sonozuka/design_similarity/extract_yes_pairs.py
```

---

## 入出力

| | パス | 内容 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/qwen_similarity_results/*.jsonl` | `judge_cited_pairs.py` の出力 |
| 入力 | `/mnt/eightthdd/uspto/data/*.csv` | 特許属性（`title`, `class` 列を使用） |
| 出力 | `/mnt/eightthdd/uspto/yes_pair/qwen_yes_pairs/{year}.jsonl` | Yes レコードの年別 JSONL |
| 出力 | `/mnt/eightthdd/uspto/yes_pair/qwen_yes_image_pair/` | source + target の横並び画像 |
| キャッシュ | `/mnt/eightthdd/uspto/yes_pair/_patent_index.pkl` | `patent_id → {title, class}` の pickle キャッシュ |

---

## 処理フロー

```
data/*.csv  ──→  build_patent_index()  ──→  patent_index (dict)
                  └─ pickle キャッシュ                    │
                     (yes_pair/_patent_index.pkl)         │
                                                          │
qwen_similarity_results/*.jsonl  ──→  process_file()  ←──┘
      │  similarity=Yes のみ抽出
      │
      ├──→  yes_pair/qwen_yes_pairs/{year}.jsonl   （年別 JSONL）
      └──→  yes_pair/qwen_yes_image_pair/          （横並び画像）
```

---

## 出力画像のレイアウト

```
┌─────────────────────────────────────────────────────┐
│  [タイトル A]        │  [タイトル B]                  │  ← 上部ヘッダー
│  [分類 A]            │  [分類 B]                      │
├──────────────────────┼──────────────────────────────-│
│                      │                               │
│    source 画像        │    target 画像                │
│                      │                               │
├─────────────────────────────────────────────────────┤
│  confidence: 4                                       │  ← 下部フッター
│  Both designs share identical silhouette...          │
└─────────────────────────────────────────────────────┘
```

- 上部: `patent_index` から取得したタイトル・分類を両側に表示
- 画像: `image_type_used` で指定された図タイプを使用、高さ 400px に統一
- 下部: `confidence` と `reason` を描画

### 分類コード（`class` フィールド）について

ヘッダー2行目に表示される `D 6484, D6477` のような「D」で始まる値は、
**USPC（米国特許分類）の意匠サブクラスコード**であり、特許番号とは異なる。

形式は `D[クラス番号][サブクラス番号]`（スペースの有無は揺れあり）：
- 例: `D 6484` → 意匠クラス D6（家具）サブクラス 484
- 例: `D6477` → 意匠クラス D6（家具）サブクラス 477
- カンマ区切りは複数サブクラスへの分類を意味する

なお特許番号は `D0579680` のような形式で、`id` 列に格納される。

| 場所 | フィールド名 |
|------|-------------|
| `data/*.csv` | `class` 列 |
| `patent_index`（メモリ・pickle） | `index[patent_id]["class"]` |
| 出力 JSONL (`yes_pairs/*.jsonl`) | `source_class` / `target_class` |
| 画像ヘッダー（左パネル） | `src_info.get("class", "")` |
| 画像ヘッダー（右パネル） | `tgt_info.get("class", "")` |

---

## 実行方法

引数なし。`qwen_similarity_results/` 以下の全 JSONL を処理する（`BACKEND` により自動決定）。

```bash
python extract_yes_pairs.py
```

### スキップモード（resume）

スクリプト起動時に `OUT_JSONL_DIR`（`qwen_yes_pairs/`）の既存 JSONL を読み込み、
処理済みの `(source, target)` ペアをスキップして未処理分のみ追記する。
中断後の再開や、新年度データ追加時の差分更新に使用できる。

- 画像ファイルは上書き保存のため重複しない
- JSONL は追記モードのため、スキップ判定なしに再実行すると重複が発生する（スキップモードで防止）

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [judge_cited_pairs.md](judge_cited_pairs.md) | `extract_yes_pairs.py` | 目視確認・レビュー |
| `qwen_similarity_results/*.jsonl` | → `yes_pair/qwen_yes_pairs/`, `yes_pair/qwen_yes_image_pair/` | — |

パイプライン全体の位置付けは [pipeline.md](pipeline.md) を参照。