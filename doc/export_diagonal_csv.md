# 分類コード別対角値CSV出力 (`export_diagonal_csv.py`)

各分類コードについて、Reference（全審査官引用ペア）と Similar（LLM類似判定Yesペア）の
対角値（within-class）と非対角値合計（cross-class）を CSV に出力する。

---

## スクリプト

```
/home/sonozuka/design_similarity/export_diagonal_csv.py
```

---

## 入出力

| | パス | 内容 |
|---|---|---|
| 入力（Reference） | `/mnt/eightthdd/uspto/all_pair/qwen_all_pairs/{year}.jsonl` | 全ペア（`extract_all_pairs.py` の出力） |
| 入力（Similar） | `/mnt/eightthdd/uspto/yes_pair/qwen/exact_match/jsonl/{year}.jsonl` | 完全一致ペア |
| 入力（Similar） | `/mnt/eightthdd/uspto/yes_pair/qwen/high_similar/jsonl/{year}.jsonl` | 高類似ペア |
| 入力（Similar） | `/mnt/eightthdd/uspto/yes_pair/qwen/similar/jsonl/{year}.jsonl` | 類似ペア |
| 出力 | `output/diagonal_summary.csv` | 分類コード別集計CSV |

---

## 出力スキーマ

| カラム | 内容 |
|--------|------|
| `class` | 分類コード（例: `D26`） |
| `reference_diagonal` | Reference の対角値（同一クラス内ペア数） |
| `reference_cross_class` | Reference の非対角値合計（他クラスへのペア数） |
| `similar_diagonal` | Similar の対角値 |
| `similar_cross_class` | Similar の非対角値合計 |

---

## 実行前のデータ更新手順

`judge_cited_pairs.py` が新たなデータを出力したとき、以下の順で更新してから実行する。

### Step 1 — Reference データの更新

```bash
cd /home/sonozuka/design_similarity
python extract_all_pairs.py
```

入力: `qwen_similarity_results/{year}.jsonl`  
出力: `all_pair/qwen_all_pairs/{year}.jsonl`

### Step 2 — Similar データの更新

```bash
python extract_yes_pairs.py
```

入力: `qwen_similarity_results/{year}.jsonl`  
出力: `yes_pair/qwen_yes_pairs/{year}.jsonl`（スキップモードで差分のみ追記）

```bash
python analysis/split_by_reason.py
```

入力: `yes_pair/qwen_yes_pairs/{year}.jsonl`  
出力: `yes_pair/qwen/{exact_match,high_similar,similar}/jsonl/{year}.jsonl`（スキップモードで差分のみ追記）

### Step 3 — CSV 生成

```bash
python export_diagonal_csv.py
```

---

## 注意事項

- `extract_yes_pairs.py` と `analysis/split_by_reason.py` はスキップモード実装済みのため、
  中断後の再実行や差分追加の場合はそのまま再実行すればよい（削除不要）
- `extract_all_pairs.py` は上書きモードのため、再実行しても重複は発生しない

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [extract_all_pairs.md](extract_all_pairs.md) | `export_diagonal_csv.py` | 論文・分析資料への組み込み |
| [extract_yes_pairs.md](extract_yes_pairs.md) → [split_by_reason.md](../analysis/doc/split_by_reason.md) | → `output/diagonal_summary.csv` | — |