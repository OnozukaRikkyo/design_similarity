# 画像インデックス (image_index.py)

特許 ID → 画像ファイルパスのマッピングを提供する共通ライブラリ。
複数のスクリプトから `import` して使用する。

---

## スクリプト

```
/home/sonozuka/design_similarity/image_index.py
```

---

## データソース

| パス | 内容 |
|------|------|
| `/mnt/eightthdd/uspto/data/{year}.csv` | 特許メタデータ (2007〜2022 全年) |
| `/mnt/eightthdd/impact/images/{year}/` | 特許画像ファイル (TIF) |

`data/{year}.csv` の使用カラム:

| カラム | 内容 | 例 |
|--------|------|-----|
| `id` | 意匠特許 ID | `D0746370` |
| `file_names` | 全図ファイル名リスト | `['USD0746370-20151229-D00000.TIF', ...]` |
| `fig_desc` | 全図の説明文リスト | `['FIG. 1 is a front view...', ...]` |

---

## タイプ判定ルール

`image_vector_no_text.py` の `detect_type()` と同一ロジック。
`fig_desc` リスト全体を走査し、特許ごとに **1 つのタイプ** を決定する。

| 優先順 | 条件 | 割り当てタイプ |
|--------|------|--------------|
| 1 | `fig_desc` のいずれかに `\bperspective\b` を含む | `"perspective"` |
| 2 | `fig_desc` のいずれかに `\bfront (view\|elevation\|elevational\|plan)\b` を含む | `"front"` |
| 3 | 上記いずれにも該当しない（フォールバック） | `"overview"` |

使用画像は常に `file_names[0]`（D00000、主要図）。

> **1 特許 = 1 タイプ = 1 画像**：各特許はこのルールで必ず 1 タイプのみに分類され、
> `source_images` / `target_images` の dict には常に 1 エントリのみ格納される。
> D00001 以降の図は使用しない。

### 全体のタイプ別件数（image_index.py 出力例）

```
front=45,913  overview=13,730  perspective=374,849  合計 434,492 件
```

### D18 タイプ別内訳

| タイプ | cited_image_pairs ペア数 | rank_index ユニーク特許数 |
|--------|------------------------:|------------------------:|
| perspective | 1,447 (94.6%) | 959 |
| overview | 74 (4.8%) | 59 |
| front | 9 (0.6%) | 12 |

`judge_cited_pairs.py` は 3 タイプすべてを処理するが、
retrieval 実験（`compute_ranks.py`）は perspective インデックスのみ使用する。

---

## インデックス構造

```python
{
    patent_id_int: {
        "perspective": "/mnt/eightthdd/impact/images/2007/USD0543613-20070529-D00000.TIF"
    },
    ...
}
```

- キー: `DESIGN_OFFSET (10_000_000_000) + 特許番号` の int64
- 値: `{ image_type: file_path }` — タイプは 1 特許につき 1 つ

---

## キャッシュ

初回構築後は pickle キャッシュに保存し、2 回目以降は即座にロードする。

| パス | 内容 |
|------|------|
| `/mnt/eightthdd/uspto/_image_index.pkl` | pickle キャッシュ |

---

## 公開インターフェース

### `patent_id_int(did: str) -> int | None`

意匠特許 ID 文字列を整数キーに変換する。

```python
from image_index import patent_id_int

patent_id_int("D0543613")   # → 10_000_543_613
patent_id_int("D543613")    # → 10_000_543_613
patent_id_int("invalid")    # → None
```

### `detect_image_type(fig_desc_list: list[str]) -> str`

fig_desc リストからタイプを判定する（"perspective" / "front" / "overview"）。

```python
from image_index import detect_image_type

detect_image_type(["FIG. 1 is a perspective view..."])  # → "perspective"
detect_image_type(["FIG. 1 is a front view..."])        # → "front"
detect_image_type(["FIG. 1 is a top plan view..."])     # → "overview"
```

### `load_image_index(rebuild: bool = False) -> dict[int, dict[str, str]]`

メインエントリポイント。インデックスをロードして返す。

```python
from image_index import load_image_index

index = load_image_index()           # キャッシュがあれば即座にロード
index = load_image_index(rebuild=True)  # 強制再構築
```

### 定数

| 定数 | 値 | 内容 |
|------|----|------|
| `DESIGN_OFFSET` | `10_000_000_000` | 意匠特許 ID のオフセット |
| `IMAGE_TYPES` | `["front", "overview", "perspective"]` | 有効なタイプ一覧 |

---

## 利用例

### 基本的な使い方

```python
from image_index import load_image_index, patent_id_int

index = load_image_index()

pid = patent_id_int("D0543613")
entry = index.get(pid)
# → {"perspective": "/mnt/eightthdd/impact/images/2007/USD0543613-20070529-D00000.TIF"}

# 画像パスを取得
path = entry.get("perspective") if entry else None
```

### スクリプトへの組み込み

```python
from image_index import load_image_index, patent_id_int

def process(patent_ids: list[str]) -> None:
    index = load_image_index()
    for did in patent_ids:
        pid = patent_id_int(did)
        images = index.get(pid, {})
        # images = {"perspective": "/path/to/file.TIF"}
```

---

## 初期構築手順

キャッシュ (`/mnt/eightthdd/uspto/_image_index.pkl`) が存在しない場合、
`load_image_index()` を呼び出したときに自動で構築される。
**パイプラインを初めて実行する前**、または `data/{year}.csv` が更新された場合は
以下のコマンドで明示的に構築・再構築する。

```bash
cd /home/sonozuka/design_similarity

# 初回構築（キャッシュがなければ自動実行されるが、事前に確認したい場合）
python image_index.py

# data/*.csv が更新されたとき（強制再構築）
python image_index.py --rebuild
```

**期待される出力例:**

```
画像インデックス構築中 (ソース: /mnt/eightthdd/uspto/data) ...
  2007.csv: 24,063 件  (24,063 件登録)
  ...
  2022.csv: 33,541 件  (33,541 件登録)
合計 434,492 件の特許を登録
インデックスをキャッシュ: /mnt/eightthdd/uspto/_image_index.pkl

front=45,913  overview=13,730  perspective=374,849
```

**再構築が必要なタイミング:**

| 状況 | 対応 |
|------|------|
| 初めてパイプラインを実行する | 自動構築されるため不要（任意で事前実行可） |
| `data/{year}.csv` に新しい年のファイルが追加された | `--rebuild` で再構築 |
| キャッシュファイルが破損した | `--rebuild` で再構築 |

---

## CLI（単体確認・再構築）

```bash
# インデックスを構築してタイプ別件数を表示
python image_index.py

# 強制再構築
python image_index.py --rebuild

# 特定特許の画像パスを確認
python image_index.py D0543613 D0746370
```

---

## 利用しているスクリプト

| スクリプト | 利用内容 |
|-----------|---------|
| `extract_cited_image_pairs.py` | `load_image_index()`, `patent_id_int()` |

---

## 前後の処理との関係

| 前工程 | 本モジュール | 後工程 |
|--------|------------|--------|
| `data/{year}.csv` (USPTO 生データ) | `image_index.py` | `extract_cited_image_pairs.py` |

---

## 旧実装との違い

旧実装 (`extract_cited_image_pairs.py` の `build_image_index()`) は
`/mnt/eightthdd/uspto/image_numpy_data_no_text/` の numpy ファイルを参照していたため、
2007〜2014 年のデータしか利用できなかった。

本モジュールは `data/{year}.csv` を正規ソースとして使用するため、
2007〜2022 年の全期間をカバーする。

| 項目 | 旧実装 | 本モジュール |
|------|--------|------------|
| データソース | `image_numpy_data_no_text/*.npy` | `data/{year}.csv` |
| カバー年 | 2007〜2014 | 2007〜2022 |
| キャッシュパス | `cited_image_pairs/_image_index.pkl` | `_image_index.pkl` |
| タイプ判定 | numpy インデックス内のタイプ分類を継承 | `image_vector_no_text.py` と同一ロジック |