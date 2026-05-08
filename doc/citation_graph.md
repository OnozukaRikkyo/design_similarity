# 引用グラフ構築 (citation graph)

USPTO 意匠特許の引用データ (JSON) から**共引用エッジリスト CSV** を生成し、無向グラフを構築する。

---

## エッジの定義

同一の出願審査 (`patentApplicationNumber`) で **共に引用された 2 つの意匠特許**を類似とみなしエッジを張る（共引用ネットワーク）。

```
出願 29701893 が D535736, D543613, D543266 を引用
  → エッジ (D535736, D543613)
  → エッジ (D535736, D543266)
  → エッジ (D543613, D543266)
```

- ノードは意匠特許 ID (`D0XXXXXX` 形式)
- `source < target` でアルファベット順に正規化（重複排除）
- グラフは**無向**（方向の意味なし）

---

## データソース

| パス | 内容 |
|------|------|
| `/mnt/eightthdd/uspto/json/<年>.json` | 引用データ (2007〜2010) |
| `/mnt/eightthdd/uspto/data/<年>.csv` | 意匠特許の属性 (title, id, date, class ...) |

### JSON 構造

```json
{
  "D543613": {
    "original_id": "D0543613",
    "citations_found": 5,
    "records": [
      {
        "patentApplicationNumber": "29721004",
        "citedDocumentIdentifier": "US D543613 S",
        "officeActionDate": "2021-05-07T00:00:00",
        "officeActionCategory": "CTNF",
        "citationCategoryCode": "A",
        "examinerCitedReferenceIndicator": true,
        ...
      }
    ]
  }
}
```

- **キー** (`"D543613"`) = 引用された意匠特許 (`original_id` と同一)
- **`patentApplicationNumber`** = その特許を引用した出願番号
- **`citedDocumentIdentifier`** = 引用された特許の識別子（キーと常に一致）

> **注意**: `citedDocumentIdentifier` は常にそのエントリ自身の `original_id` と同じ値を持つ。
> エッジの source/target を `original_id → citedDocumentIdentifier` とすると全件が自己ループになる。
> 正しいエッジは「同一出願で共引用されたペア」である。

---

## スクリプト: `build_edge_list.py`

```
/home/sonozuka/design_similarity/build_edge_list.py
```

### 処理フロー

```
data/<年>.csv  ──→  load_valid_ids()  ──→  valid_ids (set[str])
                                                  │
json/<年>.json  ──→  build_edge_list()  ←─────────┘
                          │
                          │  patentApplicationNumber でグループ化
                          │  同一出願で引用された特許のペアを生成
                          ↓
              edge_list/<年>.csv
```

### 主要関数

| 関数 | 役割 |
|------|------|
| `load_valid_ids(csv_dir)` | `data/` 以下の全 CSV から有効な意匠 ID の集合を構築 |
| `build_edge_list(json_path, valid_ids, out_path)` | JSON 1 ファイル → エッジ CSV 1 ファイルを生成 |
| `main(years)` | 年リストを受け取り全ファイルを処理 |

### エッジ CSV カラム

| カラム | 内容 |
|--------|------|
| `source` | 意匠 ID（D0XXXXXX、source < target で正規化） |
| `target` | 意匠 ID（D0XXXXXX） |
| `patentApplicationNumber` | 両特許を繋ぐ出願番号 |
| `officeActionDate` | source が引用された際のオフィスアクション日付 |
| `officeActionCategory` | OA 種別 (CTNF / CTFR 等) |
| `citationCategoryCode` | 引用カテゴリ (A / X / Y 等) |
| `examinerCitedReferenceIndicator` | 審査官引用フラグ |
| `applicantCitedExaminerReferenceIndicator` | 出願人引用フラグ |
| `workGroup` | ワークグループ |
| `groupArtUnitNumber` | アートユニット番号 |
| `techCenter` | テックセンター |

> source と target が同一出願で引用されたとき、エッジ属性は source 側のレコードから取得する。
> 同一ペアが複数の出願で引用された場合は出願ごとに 1 行ずつ出力される（`extract_cited_image_pairs.py` 側で集約）。

### アルゴリズム詳細

#### ステップ1 — `valid_ids` によるホワイトリストフィルタ

`data/` 以下の全 CSV から意匠 ID (`D0XXXXXX`) を `set` として収集する。JSON に含まれる引用先が実際に存在する意匠特許かどうかをここで確認し、無効な ID はエッジ生成前に除外する。

#### ステップ2 — 中間構造 `app_to_patents` への集約

```python
app_to_patents: dict[str, dict[str, dict]] = defaultdict(dict)
# 出願番号 → { 特許ID → レコード }
```

JSON を走査し、各引用レコードを `出願番号 → 特許ID → 代表レコード` の2重辞書に格納する。**同一出願で同一特許が複数回引用された場合は最初のレコードのみ保持**（辞書キーによる自然な重複排除）。

#### ステップ3 — ペア列挙と方向正規化

```python
patents = sorted(patent_map)        # source < target を保証
for i in range(len(patents)):
    for j in range(i + 1, len(patents)):
        source, target = patents[i], patents[j]
```

- `sorted()` でアルファベット順に並べることで `source < target` が常に成立し、`(A,B)` と `(B,A)` の重複エッジを防ぐ。
- `i < j` の上三角ループで全ペアを列挙（組み合わせ数 = nC2）。
- 引用された特許が 1 件だけの出願はエッジを生成できないためスキップし、`n_single` カウンタに記録する。

#### エッジ属性の付与規則

```python
row[attr] = app_no if attr == "patentApplicationNumber" else rec.get(attr, "")
```

`patentApplicationNumber` は `app_no` から直接セットし、`officeActionDate` 等その他の属性は **source 側の代表レコード** から取得する。同一ペアが複数の出願で共引用された場合は出願ごとに 1 行出力され、`extract_cited_image_pairs.py` 側で `events` 配列に集約する。

---

### 実行方法

```bash
# 全年処理（2007〜2010）
python build_edge_list.py

# 指定年のみ
python build_edge_list.py 2007 2008
```

### 出力

```
/mnt/eightthdd/uspto/edge_list/
  2007.csv   (9,645 エッジ)
  2008.csv   (11,233 エッジ)
  2009.csv   (13,504 エッジ)
  2010.csv   (10,151 エッジ)
```

---

## グラフ統計（2007–2010 合計、無向グラフ）

| 統計量 | 値 |
|--------|----|
| ノード数 N | 21,984 |
| エッジ数 | 44,533 |
| 最小次数 | 1 |
| 最大次数 | 184 |
| 平均次数 | 4.05 |

---

## 後続処理

| 目的 | スクリプト | ドキュメント |
|------|-----------|-------------|
| 画像ペア抽出 | `extract_cited_image_pairs.py` | [image_pairs.md](image_pairs.md) |
| 意匠分類の付与 | `add_class_to_edge_list.py` | [edge_list_with_class.md](edge_list_with_class.md) |
| 次数分布の可視化 | `plot_indegree.py` | [degree_distribution.md](degree_distribution.md) |
