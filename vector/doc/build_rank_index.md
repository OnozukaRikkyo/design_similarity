# ランク検索インデックス構築 (`build_rank_index.py`)

年別ベクトルを結合・重複排除し、コサイン類似度によるランク検索用インデックスを構築する。

---

## スクリプト

```
/home/sonozuka/design_similarity/vector/build_rank_index.py
```

---

## 処理フロー

```
cited_image_vectors/{type}/
  vectors_{year}.npy      (複数年)
  patent_ids_{year}.npy
  file_paths_{year}.txt
        │
        │ 全年を結合
        │ patent_id で重複排除（最初の出現を採用）
        │ L2 正規化（コサイン類似度 = 正規化後の内積）
        ▼
rank_index/{type}/
  patent_ids.npy       (N,) int64
  vectors_l2norm.npy   (N, D) float32
  file_paths.txt       N 行
```

---

## 入出力

| 項目 | パス |
|------|------|
| 入力（年別ベクトル） | `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_vectors/{type}/` |
| 出力（インデックス） | `/mnt/eightthdd/uspto/class/{CLASS}/rank_index/{type}/` |

---

## 出力ファイル構造

```
class/{CLASS}/rank_index/
  perspective/
    patent_ids.npy       (N,) int64   — ユニーク特許 ID
    vectors_l2norm.npy   (N, D) float32 — L2 正規化済みベクトル
    file_paths.txt       N 行
  front/
  overview/
```

`patent_ids[i]` ↔ `vectors_l2norm[i]` ↔ `file_paths[i]` の 1:1 対応を保証する。

---

## L2 正規化の意味

```python
v_norm = v / ‖v‖₂
```

正規化後のベクトル同士の内積がコサイン類似度になる。

```
cosine_similarity(A, B) = A_norm · B_norm
```

`compute_ranks.py` 側で改めて正規化する必要はない。

---

## 重複排除のルール

同じ特許 ID が複数年の JSONL に現れる場合、**年の昇順で最初に登場したベクトルを採用**する。
（`build_class_vectors.py` が同一前処理で生成したものを使うため、どの年のベクトルでも差異はない。）

---

## D18 の実行結果（2026-05-18 時点）

| タイプ | ユニーク件数 | shape |
|--------|----------:|-------|
| perspective | 959 | (959, 2048) |
| front | 12 | (12, 2048) |
| overview | 59 | (59, 2048) |

---

## 実行方法

```bash
# D18（デフォルト）
python build_rank_index.py

# 別クラス
python build_rank_index.py --class D10

# 処理済みを再構築
python build_rank_index.py --class D18 --no-resume
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--class` | `D18` | 対象クラスコード |
| `--no-resume` | — | 処理済みファイルを上書きする |

---

## データ更新時の再実行

```bash
# 新しい年が追加または既存ベクトルが更新された場合
python build_rank_index.py --class {CLASS} --no-resume
```

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [build_class_vectors.md](build_class_vectors.md) | `build_rank_index.py` | [compute_ranks.md](compute_ranks.md) |
| `cited_image_vectors/{type}/vectors_{year}.npy` | → `rank_index/{type}/vectors_l2norm.npy` | `compute_ranks.py` |
