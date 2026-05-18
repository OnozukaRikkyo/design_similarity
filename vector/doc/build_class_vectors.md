# クラス別ベクトル生成 (`build_class_vectors.py`)

指定クラスの引用ペアに登場する特許の画像ベクトルを生成・保存する。

`cited_image_vectors/` に既存ベクトルがあれば再計算せずにコピーする。

---

## スクリプト

```
/home/sonozuka/design_similarity/vector/build_class_vectors.py
```

---

## 処理フロー

```
class/{CLASS}/cited_image_pairs/{year}.jsonl
        │
        │ load_pairs()
        │ year → type → {patent_id_int: file_path}
        ▼
ExistingVectorIndex（cited_image_vectors/ を全走査してインデックス構築）
        │
        │ 特許 × タイプごとに判定
        │
        ├─ 既存ベクトルあり → cited_image_vectors/{type}/vectors_{year}.npy からコピー
        │
        └─ 既存ベクトルなし
                ├─ --no-gpu かつ新規生成必要 → スキップ（警告を表示）
                └─ GPU あり → Qwen3-VL-Embedding-2B で新規生成
                        前処理: ImageProcessor.process() → 白余白除去 → 長辺768px → RGB
                        テキスト: "Design Patent Drawing."（全画像固定）
        │
        ▼
class/{CLASS}/cited_image_vectors/{type}/
  patent_ids_{year}.npy
  vectors_{year}.npy
  file_paths_{year}.txt
```

---

## 入出力

| 項目 | パス |
|------|------|
| 入力（クラス別ペアJSONL） | `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/{year}.jsonl` |
| 参照（既存ベクトル） | `/mnt/eightthdd/uspto/cited_image_vectors/{type}/` |
| 出力 | `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_vectors/{type}/` |

---

## 出力ファイル構造

```
class/{CLASS}/cited_image_vectors/
  perspective/
    patent_ids_{year}.npy        (N,) int64    — 特許 ID（昇順）
    vectors_{year}.npy           (N, D) float32 — 埋め込みベクトル（L2 未正規化）
    file_paths_{year}.txt        N 行           — 元画像パス（人間可読）
    _checkpoint_{year}.pkl       (処理中のみ)   — 中断再開用チェックポイント
  front/
    ...（同上）
  overview/
    ...（同上）
```

`patent_ids_{year}.npy[i]` ↔ `vectors_{year}.npy[i]` ↔ `file_paths_{year}.txt[i]` の 1:1 対応を保証する。

---

## 特許 ID エンコード

| 元の ID 文字列 | エンコード後 |
|---|---|
| `"D0550278"` | `10_000_550_278` |

```
DESIGN_OFFSET (= 10_000_000_000) + 特許番号の数値部
```

---

## 既存ベクトルの再利用（`ExistingVectorIndex`）

`cited_image_vectors/` を全走査し、`(image_type, patent_id_int)` → `(year, row_index)` のインデックスを構築する。

- ベクトルファイルはオンデマンドでロード・キャッシュ（対象クラスの小サブセットでは必要分だけ読み込まれる）
- 同一特許が複数年の JSONL に登場する場合は最初に見つかった年のベクトルを使用

### 前処理の一致

`cited_image_vectors/` のベクトルは `build_cited_image_vectors.py` が生成したもので、以下の前処理が適用されている。

| 処理 | 内容 |
|------|------|
| 白余白除去 | `ImageProcessor.crop_margin()` — tolerance=5、1px 余白を残す |
| リサイズ | `ImageProcessor.resize_long_side()` — 長辺 768px（縮小のみ） |
| チャネル | RGB 変換 |
| テキスト | `"Design Patent Drawing."` 固定 |

本スクリプトで新規生成する場合も同じ前処理・テキストを使用する。

---

## GPU なしでの動作確認（`--no-gpu`）

`cited_image_vectors/` に対象クラスの全ベクトルが存在する場合、
モデルロードなしで完結する。

起動時のログで GPU 要否を確認できる:

```
[2015/perspective] 合計: 30  既存コピー: 30  新規生成: 0   → --no-gpu で OK
[2015/perspective] 合計: 30  既存コピー: 10  新規生成: 20  → GPU 必要
```

---

## D18 の実行結果（2026-05-18 時点）

| タイプ | 年 | 件数 | shape |
|--------|----|----|-------|
| perspective | 2007 | 72 | (72, 2048) |
| perspective | 2008 | 41 | (41, 2048) |
| perspective | 2009 | 45 | (45, 2048) |
| perspective | 2010 | 46 | (46, 2048) |
| perspective | 2011 | 47 | (47, 2048) |
| perspective | 2012 | 60 | (60, 2048) |
| perspective | 2013 | 95 | (95, 2048) |
| perspective | 2014 | 51 | (51, 2048) |
| perspective | 2015 | 52 | (52, 2048) |
| perspective | 2016 | 106 | (106, 2048) |
| perspective | 2017 | 66 | (66, 2048) |
| perspective | 2018 | 116 | (116, 2048) |
| perspective | 2019 | 67 | (67, 2048) |
| perspective | 2020 | 49 | (49, 2048) |
| perspective | 2021 | 23 | (23, 2048) |
| perspective | 2022 | 23 | (23, 2048) |
| front | 2008 |  2 | (2, 2048) |
| front | 2010 |  2 | (2, 2048) |
| front | 2014 |  2 | (2, 2048) |
| front | 2017 |  2 | (2, 2048) |
| front | 2021 |  4 | (4, 2048) |
| overview | 2007 | 10 | (10, 2048) |
| overview | 2010 |  2 | (2, 2048) |
| overview | 2013 | 12 | (12, 2048) |
| overview | 2014 |  8 | (8, 2048) |
| overview | 2015 |  5 | (5, 2048) |
| overview | 2018 |  5 | (5, 2048) |
| overview | 2019 |  7 | (7, 2048) |
| overview | 2020 |  6 | (6, 2048) |
| overview | 2021 |  4 | (4, 2048) |

全 2007〜2022 年（一部年はデータなし）、既存ベクトルカバー率 100%（新規生成なし）。

---

## 実行方法

```bash
# D18（デフォルト）全年処理
python build_class_vectors.py

# 別クラスを指定
python build_class_vectors.py --class D5

# 指定年のみ
python build_class_vectors.py 2007 2008 --class D18

# GPU なしで動作確認
python build_class_vectors.py --no-gpu

# チェックポイントを無視して最初から処理し直す
python build_class_vectors.py --no-resume
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `years` | 全年 | 処理する年（複数指定可） |
| `--class` | `D18` | 対象クラスコード |
| `--no-resume` | — | チェックポイントを無視して最初から処理し直す |
| `--no-gpu` | — | GPU を使わない（既存ベクトルのコピーのみ実行） |

---

## データ更新時の再実行

完了マーカーは **`vectors_{year}.npy` の存在**。上書きにはファイルを削除してから再実行する。

### 新しい年が追加された場合

```bash
python build_class_vectors.py {year} --class {CLASS} --no-gpu
# cited_image_vectors/ にベクトルがなければ --no-gpu を外す
```

### 既存年のデータが更新された場合

```bash
YEAR=2013
CLASS=D18
BASE=/mnt/eightthdd/uspto/class/${CLASS}/cited_image_vectors
for TYPE in perspective front overview; do
    rm -f "${BASE}/${TYPE}/vectors_${YEAR}.npy"
    rm -f "${BASE}/${TYPE}/patent_ids_${YEAR}.npy"
    rm -f "${BASE}/${TYPE}/file_paths_${YEAR}.txt"
    rm -f "${BASE}/${TYPE}/_checkpoint_${YEAR}.pkl"
done
python build_class_vectors.py ${YEAR} --class ${CLASS} --no-gpu
```

> `--no-resume` は中断時の pkl チェックポイントを無視するオプションであり、  
> 完了済みの `vectors_{year}.npy` は削除しない限り上書きされない。

---

## 再開モードとチェックポイント

バッチごとにチェックポイントを保存する。

```
class/{CLASS}/cited_image_vectors/{type}/_checkpoint_{year}.pkl
```

| フィールド | 型 | 内容 |
|---|---|---|
| `ids` | `list[int]` | 処理済み patent_id |
| `vecs` | `ndarray (M, D) float32` | 処理済みベクトルの結合配列 |
| `paths` | `list[str]` | 対応する画像ファイルパス |

`vectors_{year}.npy` 書き込み完了後に自動削除される。

---

## プログレスバー

| バー | 単位 | 内容 |
|------|------|------|
| 外側（全体進捗） | タスク | 年 × タイプの組み合わせ数 |
| 内側（タスク進捗） | 件 | 1 タスク内の特許数（再開時は残り件数から） |

各タスク開始時に「合計 / 既存コピー / 新規生成」の内訳を表示する。

---

## コサイン類似度計算の例

```python
import numpy as np
from pathlib import Path

CLASS    = "D18"
TYPE_DIR = Path(f"/mnt/eightthdd/uspto/class/{CLASS}/cited_image_vectors/perspective")

all_ids, all_vecs = [], []
for ids_path in sorted(TYPE_DIR.glob("patent_ids_*.npy")):
    year = ids_path.stem.replace("patent_ids_", "")
    all_ids.append(np.load(ids_path))
    all_vecs.append(np.load(TYPE_DIR / f"vectors_{year}.npy"))

patent_ids = np.concatenate(all_ids)
vectors    = np.concatenate(all_vecs, axis=0).astype(np.float32)

norms   = np.linalg.norm(vectors, axis=1, keepdims=True)
vectors /= np.where(norms == 0, 1, norms)   # L2 正規化

id_to_idx = {int(pid): i for i, pid in enumerate(patent_ids)}

src_id = 10_000_550_278
tgt_id = 10_000_550_759
sim = float(vectors[id_to_idx[src_id]] @ vectors[id_to_idx[tgt_id]])
print(f"cosine similarity: {sim:.4f}")
```

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程（想定） |
|--------|-------------|---------------|
| [filter_pairs_by_class.md](filter_pairs_by_class.md) | `build_class_vectors.py` | ベクトル類似度検索・FAISS 近傍探索 |
| `class/{CLASS}/cited_image_pairs/{year}.jsonl` | → `class/{CLASS}/cited_image_vectors/{type}/` | Gemini 判定スコアとの相関分析 |
| `cited_image_vectors/`（既存ベクトル参照） | | |