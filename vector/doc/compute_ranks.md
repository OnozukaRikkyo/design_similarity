# ベクトルランク検索 (`compute_ranks.py`)

画像ペア (A, B) に対して、A のベクトルでクラス全件を検索し、B が何位に現れるかを計算する。

---

## スクリプト

```
/home/sonozuka/design_similarity/vector/compute_ranks.py
```

---

## 処理フロー

```
cited_image_pairs/{year}.jsonl
rank_index/{type}/
  patent_ids.npy
  vectors_l2norm.npy
        │
        │ タイプごとに rank_index を遅延ロード（初回のみ）
        │
        │ ペアごとに:
        │   A のベクトルを取得
        │   A と全件の類似度を計算
        │   A 自身を除外（sims[query_row] = -2.0）
        │   B の類似度 > B の類似度 の件数 + 1 = rank
        ▼
rank_results/{sim_func}/{year}.jsonl
  1行 = 1 (ペア × タイプ) レコード
```

---

## 入出力

| 項目 | パス |
|------|------|
| 入力（ペアJSONL） | `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/{year}.jsonl` |
| 入力（インデックス） | `/mnt/eightthdd/uspto/class/{CLASS}/rank_index/{type}/` |
| 出力（ランク結果） | `/mnt/eightthdd/uspto/class/{CLASS}/rank_results/{sim_func}/{year}.jsonl` |

---

## 出力フォーマット（JSONL）

1 行 1 レコード。1 ペアに複数タイプが存在する場合は複数行に分割される。

```json
{
  "source":       "D0550278",
  "target":       "D0550759",
  "type":         "perspective",
  "rank":         5,
  "n_candidates": 456,
  "similarity":   0.873421
}
```

### フィールド一覧

| フィールド | 型 | 内容 |
|-----------|-----|------|
| `source` | string | 画像 A の特許 ID |
| `target` | string | 画像 B の特許 ID |
| `type` | string | 画像タイプ（`perspective` / `front` / `overview`） |
| `rank` | int | A で検索したときの B の順位（1-indexed、1 が最も類似） |
| `n_candidates` | int | 候補数（= インデックス全件 − 1）|
| `similarity` | float | A–B 間のコサイン類似度（小数点以下 6 桁） |

### 順位の解釈

| 値 | 意味 |
|----|------|
| `rank = 1` | B が A に最も類似（他に誰よりも近い） |
| `rank / n_candidates` | 百分位ランク（0 に近いほど類似） |
| `rank = n_candidates` | B が A から最も遠い |

---

## 類似度バックエンド

| `--sim` | 実装 | 特徴 |
|---------|------|------|
| `cosine_numpy`（デフォルト） | `numpy BLAS dgemv` | L2 正規化済み内積、ソートなし O(N) カウント |
| `cosine_faiss` | `FAISS IndexFlatIP` | faiss-cpu インストール時のみ選択可。N が大きい場合に有利。 |

### コサイン類似度の計算（numpy backend）

```python
sims = vectors_l2norm @ vectors_l2norm[query_row]   # (N,) 内積
sims[query_row] = -2.0                               # 自身を除外
rank = np.sum(sims > sims[target_row]) + 1           # ソート不要、O(N)
```

### FAISS backend のインストール

```bash
pip install faiss-cpu
```

---

## スキップ条件

以下の場合はレコードを出力しない:

- ペアの source または target が rank_index に存在しない
- source_images / target_images に当該タイプのキーがない

---

## 実行方法

```bash
# D18 全年（デフォルト）
python compute_ranks.py --class D18

# 指定年のみ
python compute_ranks.py 2007 2008 --class D18

# 別クラス
python compute_ranks.py --class D10

# FAISS バックエンド（faiss-cpu 要インストール）
python compute_ranks.py --class D18 --sim cosine_faiss

# 処理済みを上書き
python compute_ranks.py --class D18 --no-resume
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `years` | 全年 | 処理する年（複数指定可） |
| `--class` | `D18` | 対象クラスコード |
| `--sim` | `cosine_numpy` | 類似度計算バックエンド |
| `--no-resume` | — | 処理済みファイルを上書きする |

---

## D18 の実行結果（2026-05-18 時点）

総レコード数: 634 件（`cosine_numpy`、各ペア 1 タイプ = 1 レコード）

| タイプ | レコード数 | n_candidates | rank 中央値 | 百分位中央値 | rank=1 割合 |
|--------|----------:|-------------:|------------:|------------:|------------:|
| perspective | 584 | 456 | 22.0 | 0.048 | 0.146 |
| overview | 47 | 31 | 5.0 | 0.161 | 0.106 |
| front | 3 | 5 | 1.0 | 0.200 | 1.000 |

perspective の百分位中央値 0.048 は、引用された意匠特許ペアが上位 5% 程度に類似することを示す。

---

## 分析例（Python）

```python
import json
import numpy as np
from pathlib import Path

CLASS = "D18"
SIM   = "cosine_numpy"
base  = Path(f"/mnt/eightthdd/uspto/class/{CLASS}/rank_results/{SIM}")

records = []
for f in sorted(base.glob("[0-9]*.jsonl")):
    for line in f.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))

# perspective のみ
persp = [r for r in records if r["type"] == "perspective"]

ranks    = np.array([r["rank"] for r in persp])
n_cands  = np.array([r["n_candidates"] for r in persp])
pct_rank = ranks / n_cands  # 百分位ランク（0 が最良）

print(f"件数        : {len(ranks)}")
print(f"中央値ランク : {np.median(ranks):.1f}")
print(f"中央値百分位 : {np.median(pct_rank):.3f}")
print(f"rank=1 の割合: {(ranks == 1).mean():.3f}")
```

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程（想定） |
|--------|-------------|--------------|
| [build_rank_index.md](build_rank_index.md) | `compute_ranks.py` | ランク分布の可視化・Gemini スコアとの相関分析 |
| `rank_index/{type}/vectors_l2norm.npy` | → `rank_results/{sim_func}/{year}.jsonl` | |
