# 画像ペア抽出 (image pairs)

共引用エッジリスト CSV から、同じ図タイプの画像ペアを JSONL 形式で抽出する。

---

## スクリプト: `extract_cited_image_pairs.py`

```
/home/sonozuka/design_similarity/extract_cited_image_pairs.py
```

### 入力

| パス | 内容 |
|------|------|
| `/mnt/eightthdd/uspto/edge_list/<年>.csv` | `build_edge_list.py` の出力 |
| `/mnt/eightthdd/uspto/data/<年>.csv` | 特許 ID → 画像ファイルパスの対応（`image_index.py` 経由） |

### 出力

```
/mnt/eightthdd/uspto/cited_image_pairs/
  2007.jsonl
  2008.jsonl
  ...
  2022.jsonl
/mnt/eightthdd/uspto/_image_index.pkl   （画像インデックスキャッシュ、image_index.py が管理）
```

---

## 処理フロー

```
data/<年>.csv  ──→  image_index.load_image_index()  ──→  index (dict)
                                                              │
edge_list/<年>.csv  ──→  extract_pairs()  ←─────────────────┘
                              │
                              │  (source, target) で集約
                              │  共通図タイプが存在するペアのみ出力
                              ↓
                   cited_image_pairs/<年>.jsonl
```

---

## 画像インデックスの構造

`image_index.py` が `data/{年}.csv` から構築する。詳細は [image_index.md](image_index.md) を参照。

- `{type}` は `front` / `overview` / `perspective` の 3 種類
- 特許 1 件につき 1 タイプ・1 画像（D00000 を使用）
- カバー年: 2007〜2022

構築結果: `{ patent_id_int: { image_type: file_path } }` の辞書。
初回構築後は `_image_index.pkl` にキャッシュされ、2 回目以降は即座にロードされる。

---

## 出力フォーマット（JSONL）

1 行 = 1 ユニークペア (source, target)。`source < target` でアルファベット順に正規化済み。

```json
{
  "source": "D0535736",
  "target": "D0537156",
  "source_images": {
    "perspective": "/mnt/eightthdd/impact/images/2007/USD0535736-20070123-D00000.TIF"
  },
  "target_images": {
    "perspective": "/mnt/eightthdd/impact/images/2007/USD0537156-20070220-D00000.TIF"
  },
  "events": [
    {
      "patentApplicationNumber": "29701893",
      "officeActionDate": "2020-10-06T00:00:00",
      "officeActionCategory": "CTNF",
      "citationCategoryCode": "A",
      "examinerCitedReferenceIndicator": "True",
      "applicantCitedExaminerReferenceIndicator": "False",
      "workGroup": "2900-WG",
      "groupArtUnitNumber": "2914",
      "techCenter": "2900"
    }
  ]
}
```

### フィールド説明

| フィールド | 内容 |
|-----------|------|
| `source` | 意匠 ID（D0XXXXXX） |
| `target` | 意匠 ID（D0XXXXXX、source < target） |
| `source_images` | `{image_type: file_path}` — source が持つ全図タイプの画像パス |
| `target_images` | `{image_type: file_path}` — target が持つ全図タイプの画像パス |
| `events` | このペアを繋いだ全出願のレコード（重複除去済み） |

### 出力条件

- source と target が**少なくとも 1 つの共通図タイプ**を持つペアのみ出力
- 共通図タイプを持たないペアはスキップ（画像なしスキップとしてカウント）

### 1特許あたりの画像数

`source_images` / `target_images` の各エントリは **1タイプ → 1パス** の dict が 1 件のみ。
各特許は `image_index.py` のタイプ判定で 1 タイプだけを割り当てられるため、
1 ペアレコード内で source または target が複数タイプを持つことはない。

使用画像は常に `file_names[0]`（`D00000.TIF`、主要図）の **1 枚のみ**。

### D18 タイプ別ペア分布（実測値）

D18 class の `cited_image_pairs/`（全年合計 1,530 ペア）のタイプ内訳：

| タイプ | ペア数 | 割合 |
|--------|-------:|-----:|
| perspective | 1,447 | 94.6% |
| overview | 74 | 4.8% |
| front | 9 | 0.6% |

> **論文の「959 unique patents, perspective-view drawings」との関係**：
> `judge_cited_pairs.py` は上記 3 タイプすべてを処理するが、
> retrieval 実験（`build_rank_index.py` → `compute_ranks.py`）は
> **perspective タイプのインデックスのみ**を使用する。
> 959 は D18 内で perspective に分類された特許の数であり、
> overview（59 件）・front（12 件）は判定対象だがランク検索実験には含まれない。

---

## 実行方法

```bash
# 全年処理（2007〜2010）
python extract_cited_image_pairs.py

# 指定年のみ
python extract_cited_image_pairs.py 2007 2008

# 画像インデックスを再構築してから処理
python extract_cited_image_pairs.py --rebuild
```

---

## 実験での使い方

### 図タイプで絞り込む

```python
import json

# perspective のみ、両方が持つペア
pairs = [
    json.loads(line)
    for line in open("/mnt/eightthdd/uspto/cited_image_pairs/2007.jsonl")
    if "perspective" in json.loads(line)["source_images"]
    and "perspective" in json.loads(line)["target_images"]
]
```

```bash
# jq を使う場合
jq 'select(.source_images.perspective and .target_images.perspective)' 2007.jsonl
```

### 出願回数でフィルタ（強いペアのみ）

```python
# 2 つ以上の出願で共引用されたペア
strong = [r for r in rows if len(r["events"]) >= 2]
```

### フィールドを後から追加する

```python
# 類似スコアを追加する例
with open("2007.jsonl") as f, open("2007_scored.jsonl", "w") as out:
    for line in f:
        row = json.loads(line)
        row["similarity_score"] = compute_score(row)
        out.write(json.dumps(row, ensure_ascii=False) + "\n")
```

---

## 整合性チェック結果（最終確認）

| チェック項目 | 2007 | 2008 | 2009 | 2010 |
|-------------|:----:|:----:|:----:|:----:|
| 自己ペア (edge / jsonl) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| source ≥ target | 0 | 0 | 0 | 0 |
| JSONL に edge 外のペアが混入 | 0 | 0 | 0 | 0 |
| events 件数不一致 | 0 | 0 | 0 | 0 |
| 画像パス欠損 (source / target) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| events 内容不一致 | 0 | 0 | 0 | 0 |
| 共通図タイプなし | 0 | 0 | 0 | 0 |

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [citation_graph.md](citation_graph.md) | `extract_cited_image_pairs.py` | [design_similarity.md](design_similarity.md) |
| `build_edge_list.py` → `edge_list/<年>.csv` | → `cited_image_pairs/<年>.jsonl` | `design_similarity.py` で類似判定 |
