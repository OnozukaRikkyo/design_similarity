# Yes 判定ペアの抽出・可視化 (`extract_yes_pairs.py`)

`similarity_results/` の JSONL から `similarity=Yes` のレコードを抽出し、
JSON ファイルと画像ペアを保存する。パイプラインの最終ステップ。

---

## スクリプト

```
/home/sonozuka/design_similarity/extract_yes_pairs.py
```

---

## 入出力

| | パス | 内容 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/similarity_results/*.jsonl` | `judge_cited_pairs.py` の出力 |
| 入力 | `/mnt/eightthdd/uspto/data/*.csv` | 特許属性（`title`, `class` 列を使用） |
| 出力 | `debug/yes_json/<src>__<tgt>.json` | Yes レコードの JSON（1ファイル1ペア） |
| 出力 | `debug/yes_image_pair/<src>__<tgt>.png` | source + target の横並び画像 |
| キャッシュ | `debug/_patent_index.pkl` | `patent_id → {title, class}` の pickle キャッシュ |

---

## 処理フロー

```
data/*.csv  ──→  build_patent_index()  ──→  patent_index (dict)
                  └─ pickle キャッシュ              │
                     (debug/_patent_index.pkl)      │
                                                    │
similarity_results/*.jsonl  ──→  process_file()  ←─┘
      │  similarity=Yes のみ抽出
      │
      ├──→  debug/yes_json/<src>__<tgt>.json   （JSON レコード）
      └──→  debug/yes_image_pair/<src>__<tgt>.png  （横並び画像）
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

---

## 実行方法

引数なし。`similarity_results/` 以下の全 JSONL を処理する。

```bash
python extract_yes_pairs.py
```

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [judge_cited_pairs.md](judge_cited_pairs.md) | `extract_yes_pairs.py` | 目視確認・レビュー |
| `similarity_results/*.jsonl` | → `debug/yes_json/`, `debug/yes_image_pair/` | — |

パイプライン全体の位置付けは [pipeline.md](pipeline.md) を参照。