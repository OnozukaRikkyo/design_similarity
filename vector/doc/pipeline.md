# クラス別ベクトル検索パイプライン

意匠特許クラス単位で引用ペアを絞り込み、画像ベクトルを生成・保存するパイプライン。  
`--class` 引数でクラスを切り替えるだけで任意のクラスに適用できる。

---

## ディレクトリ構成

```
/home/sonozuka/design_similarity/vector/
  filter_pairs_by_class.py   ← Step 1: クラス別ペア抽出
  build_class_vectors.py     ← Step 2: 画像ベクトル生成
  doc/
    pipeline.md              ← このファイル
    filter_pairs_by_class.md
    build_class_vectors.md
```

---

## データフロー

```
[共通データ（全クラス）]
/mnt/eightthdd/uspto/
  cited_image_pairs/{year}.jsonl      ← 全クラスの引用ペア
  edge_list_with_class/{year}.csv     ← 特許のクラス情報
  cited_image_vectors/{type}/         ← 全クラスの既存ベクトル（2007〜2014）

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
```

### 複数クラスを扱う場合

クラスごとに独立したサブディレクトリに格納されるため、互いに干渉しない。

```
/mnt/eightthdd/uspto/class/
  D18/
    cited_image_pairs/
    cited_image_vectors/
  D5/       ← 同じスクリプトを --class D5 で実行するだけで追加される
    cited_image_pairs/
    cited_image_vectors/
  D23/
    ...
```

---

## 実行手順

```bash
cd /home/sonozuka/design_similarity

# --- D18（初回・GPU 不要な場合） ---
python vector/filter_pairs_by_class.py --class D18
python vector/build_class_vectors.py   --class D18 --no-gpu

# --- 別クラス（D5）を追加する場合 ---
python vector/filter_pairs_by_class.py --class D5
python vector/build_class_vectors.py   --class D5 --no-gpu
# cited_image_vectors/ にベクトルがなければ --no-gpu を外す（GPU が必要）
```

---

## データ量（2025-05-18 実行済み）

### D18ペア件数（年別）

| 年 | D18ペア数 | 全体ペア数 |
|----|----------:|----------:|
| 2007 | 103 | 5,859 |
| 2008 |  54 | 6,786 |
| 2009 |  46 | 7,630 |
| 2010 |  50 | 7,443 |
| 2011 |  53 | 7,957 |
| 2012 |  65 | 9,122 |
| 2013 | 191 | 13,577 |
| 2014 |  72 | 14,406 |
| **合計** | **634** | **72,780** |

2015〜2017 は `cited_image_pairs/` が空ファイルのため対象外。

### ベクトル（D18）

| データ | 件数 |
|--------|------|
| D18特許×タイプ（ベクトル総数） | 82件 |
| 既存ベクトルカバー率 | 100%（新規推論なし） |
| ベクトル次元 | 2,048（Qwen3-VL-Embedding-2B） |

---

## ストレージ

| パス | 内容 |
|------|------|
| `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/` | クラス別ペアJSONL |
| `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_vectors/` | クラス別ベクトル（perspective/front/overview） |

---

## 2回目以降の実施手順（データ更新時）

**いずれのケースも Step 1 → Step 2 の順序は変わらない。**

---

### ケース A: 新しい年のデータが追加された

```bash
CLASS=D18
YEAR=2015

# Step 1: 新年のみフィルタ（既存年は自動スキップ）
python vector/filter_pairs_by_class.py ${YEAR} --class ${CLASS}

# Step 2: 新年のみベクトル生成
# cited_image_vectors/ に該当年のベクトルがある場合 → --no-gpu で完結
python vector/build_class_vectors.py ${YEAR} --class ${CLASS} --no-gpu
# なければ GPU が必要
python vector/build_class_vectors.py ${YEAR} --class ${CLASS}
```

起動時のログで GPU 要否を確認:

```
[2015/perspective] 合計: 30  既存コピー: 30  新規生成: 0   → --no-gpu で OK
[2015/perspective] 合計: 30  既存コピー: 10  新規生成: 20  → GPU 必要
```

---

### ケース B: 既存年のペアデータが更新された

```bash
CLASS=D18
YEAR=2013
BASE=/mnt/eightthdd/uspto/class/${CLASS}

# Step 1: 対象年を上書き
python vector/filter_pairs_by_class.py ${YEAR} --class ${CLASS} --no-resume

# Step 2: 対象年の出力ファイルを削除してから再生成
for TYPE in perspective front overview; do
    rm -f "${BASE}/cited_image_vectors/${TYPE}/vectors_${YEAR}.npy"
    rm -f "${BASE}/cited_image_vectors/${TYPE}/patent_ids_${YEAR}.npy"
    rm -f "${BASE}/cited_image_vectors/${TYPE}/file_paths_${YEAR}.txt"
    rm -f "${BASE}/cited_image_vectors/${TYPE}/_checkpoint_${YEAR}.pkl"
done
python vector/build_class_vectors.py ${YEAR} --class ${CLASS} --no-gpu
```

> **注意:** `build_class_vectors.py` の完了マーカーは `vectors_{year}.npy` の存在。  
> `--no-resume` は pkl チェックポイントを無視するだけで完了済みファイルは上書きしない。

---

### ケース C: 新しいクラスを追加する

```bash
CLASS=D5   # 任意のクラスコード

python vector/filter_pairs_by_class.py --class ${CLASS}
python vector/build_class_vectors.py   --class ${CLASS} --no-gpu
```

出力は `/mnt/eightthdd/uspto/class/${CLASS}/` 以下に作成され、既存クラスとは完全に独立する。

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

| スクリプト | 役割 | ドキュメント |
|-----------|------|------------|
| `extract_cited_image_pairs.py` | 全クラスペアJSONLを生成 | [image_pairs.md](../../doc/image_pairs.md) |
| `add_class_to_edge_list.py` | エッジリストにクラス情報を付与 | [edge_list_with_class.md](../../doc/edge_list_with_class.md) |
| `build_cited_image_vectors.py` | 全クラスのベクトルを生成 | [cited_image_vectors.md](../../../image_vector/doc/cited_image_vectors.md) |
| **`filter_pairs_by_class.py`** | **クラス別ペア抽出** | [filter_pairs_by_class.md](filter_pairs_by_class.md) |
| **`build_class_vectors.py`** | **クラス別ベクトル生成** | [build_class_vectors.md](build_class_vectors.md) |
