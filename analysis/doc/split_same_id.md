# Yes ペアの同一ID振り分け (`analysis/split_same_id.py`)

Yes 判定ペアを「source == target（同一特許ID）」と「source != target（異なる特許ID）」の
2 グループに振り分け、それぞれ JSONL と画像を別ディレクトリに保存する。

通常の共引用ペアは必ず source ≠ target となるため、same グループは
データ異常・重複エントリの検出に相当する。

---

## スクリプト

```
/home/sonozuka/design_similarity/analysis/split_same_id.py
```

---

## 入出力

| | パス | 形式 |
|---|---|---|
| 入力 JSONL | `/mnt/eightthdd/uspto/yes_pair/{backend}_yes_pairs/{year}.jsonl` | JSONL |
| 入力 画像 | `/mnt/eightthdd/uspto/yes_pair/{backend}_yes_image_pair/` | PNG |
| 出力（同一ID） JSONL | `/mnt/eightthdd/uspto/yes_pair/{backend}/same/jsonl/{year}.jsonl` | JSONL |
| 出力（同一ID） 画像 | `/mnt/eightthdd/uspto/yes_pair/{backend}/same/images/` | PNG |
| 出力（異なるID） JSONL | `/mnt/eightthdd/uspto/yes_pair/{backend}/distinct/jsonl/{year}.jsonl` | JSONL |
| 出力（異なるID） 画像 | `/mnt/eightthdd/uspto/yes_pair/{backend}/distinct/images/` | PNG |

入力元のファイルは削除・移動せず、コピーのみ行う。

---

## 振り分けロジック

`source` / `target` フィールドの D 番号を正規化（スペース除去・7 桁ゼロパディング）し、
集合の積（`&`）が空でなければ same、空なら distinct に分類する。

```
"D0534345"  →  {"D0534345"}
"D0534345"  →  {"D0534345"}
  積 = {"D0534345"}  →  same（source == target）

"D0534345"  →  {"D0534345"}
"D0534346"  →  {"D0534346"}
  積 = {}            →  distinct（source != target）
```

same レコードには `matched_d_classes` フィールドが追加される。

---

## 出力スキーマ

入力レコードのフィールドをそのまま引き継ぎ、same グループのみ以下を追加：

| フィールド | 内容 |
|-----------|------|
| `matched_d_classes` | 一致した D 番号のリスト（例: `["D0534345"]`） |

---

## ディレクトリ構造（`{backend} = qwen` の場合）

```
/mnt/eightthdd/uspto/yes_pair/
  qwen_yes_pairs/          ← 入力 JSONL（変更なし）
  qwen_yes_image_pair/     ← 入力 画像（変更なし）
  qwen/
    same/
      jsonl/
        2007.jsonl
        2008.jsonl
        ...
      images/
        {src}__{tgt}.png
    distinct/
      jsonl/
        2007.jsonl
        ...
      images/
        {src}__{tgt}.png
```

---

## 実行方法

```bash
python analysis/split_same_id.py
```

バックエンドは スクリプト冒頭の `BACKEND` 変数で切り替える：

```python
BACKEND = "qwen"    # "gemini" | "qwen"
```

再実行する場合は出力ディレクトリを事前に削除：

```bash
rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/same
rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/distinct
```

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `extract_yes_pairs.py`（STEP 4） | `analysis/split_same_id.py` | 目視確認・異常値除去 |
| `{backend}_yes_pairs/*.jsonl` | → `{backend}/same/`, `{backend}/distinct/` | — |
| `{backend}_yes_image_pair/` | → 同上（コピー） | — |