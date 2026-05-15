# 全ペアのフォーマット変換 (`extract_all_pairs.py`)

`similarity_results/` の JSONL から **全レコード**（similarity 値を問わず）を読み込み、
CSV の特許メタデータを付加して年別 JSONL に書き出す。

目的は**フォーマット変換のみ**であり、レコードの絞り込みや画像生成は行わない。

---

## スクリプト

```
/home/sonozuka/design_similarity/extract_all_pairs.py
```

---

## 入出力

| | パス | 内容 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/{backend}_similarity_results/*.jsonl` | `judge_cited_pairs.py` の生出力 |
| 入力 | `/mnt/eightthdd/uspto/data/*.csv` | 特許属性（`title`, `class`, `date` 列を使用） |
| 出力 | `/mnt/eightthdd/uspto/all_pair/{backend}_all_pairs/{year}.jsonl` | 全ペアの年別 JSONL |
| キャッシュ | `/mnt/eightthdd/uspto/all_pair/_patent_index.pkl` | `patent_id → {title, class, date, year}` の pickle キャッシュ |

---

## このスクリプトが行うこと（フォーマット変換の内容）

入力 JSONL の各レコードに対して、以下の変換のみを行う。

| 変換 | 詳細 |
|------|------|
| メタデータ付加 | `patent_index` から `source_title`, `source_class`, `source_date`, `target_title`, `target_class`, `target_date` を補完 |
| `id_diff` 算出 | source / target の特許番号数値差の絶対値を追加 |
| 年別ファイル分割 | `source` の CSV 年（`2007.csv` → `"2007"`）を基準に `{year}.jsonl` へ振り分け |
| フィールド順統一 | `extract_yes_pairs.py` の出力と同一のキー順に整形 |

similarity 値によるフィルタリング・画像の生成・統計集計は**一切行わない**。

---

## 出力レコードのフィールド

`extract_yes_pairs.py` と同一のフォーマット。

```json
{
  "source":          "D0534345",
  "target":          "D0534346",
  "id_diff":         1,
  "source_title":    "...",
  "source_class":    "D 6484",
  "source_date":     "2006-01-10",
  "target_title":    "...",
  "target_class":    "D 6477",
  "target_date":     "2006-01-10",
  "source_images":   {"perspective": "/path/to/img.tif", ...},
  "target_images":   {"perspective": "/path/to/img.tif", ...},
  "events":          [...],
  "image_type_used": "perspective",
  "similarity":      "Yes",
  "confidence":      4,
  "reason":          "..."
}
```

---

## 実行方法

```bash
python extract_all_pairs.py
```

`BACKEND` 変数（スクリプト冒頭）で `"gemini"` / `"qwen"` を切り替える。

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [judge_cited_pairs.md](judge_cited_pairs.md) | `extract_all_pairs.py` | 統計分析・ERGM 入力など |
| `{backend}_similarity_results/*.jsonl` | → `all_pair/{backend}_all_pairs/{year}.jsonl` | — |

`similarity=Yes` のみを対象とする場合は [extract_yes_pairs.md](extract_yes_pairs.md) を参照。
パイプライン全体の位置付けは [pipeline.md](pipeline.md) を参照。
