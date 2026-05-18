# クラス別ペア抽出 (`filter_pairs_by_class.py`)

`cited_image_pairs` JSONL から指定クラスのペアのみを抽出し、`class/{CLASS}/cited_image_pairs/` に出力する。

---

## スクリプト

```
/home/sonozuka/design_similarity/vector/filter_pairs_by_class.py
```

---

## 処理フロー

```
cited_image_pairs/{year}.jsonl
edge_list_with_class/{year}.csv  ──→  load_class_map()  ──→  {patent_id: class_code}
        │                                                              │
        │  1行ずつ読み込み                                              │
        ▼                                                              │
フィルタ: source_class == CLASS AND target_class == CLASS  ←───────────┘
        │
        │  source_class / target_class フィールドを追加
        ▼
class/{CLASS}/cited_image_pairs/{year}.jsonl
```

---

## 入出力

| 項目 | パス |
|------|------|
| 入力（ペアJSONL） | `/mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl` |
| 入力（クラスCSV） | `/mnt/eightthdd/uspto/edge_list_with_class/{year}.csv` |
| 出力 | `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/{year}.jsonl` |

`{CLASS}` は `--class` 引数で指定（デフォルト: `D18`）。

---

## フィルタ条件

`source` と `target` の**両方**が指定クラスであるペアのみを出力する。

クラス情報は `edge_list_with_class/{year}.csv` の `source_class` / `target_class` 列から取得する。

対応クラス（`edge_list_with_class/` に存在するクラス）:
D1〜D30 / D32 / D34 / D99（計34クラス）

---

## 出力フォーマット（JSONL）

1行 1ペア。入力レコードの全フィールドをそのまま引き継ぎ、`source_class` / `target_class` を追加する。

### 完全なレコード例

```json
{
  "source": "D0550278",
  "target": "D0550759",
  "source_images": {
    "perspective": "/mnt/eightthdd/impact/images/2007/USD0550278-20070904-D00000.TIF"
  },
  "target_images": {
    "perspective": "/mnt/eightthdd/impact/images/2007/USD0550759-20070911-D00000.TIF"
  },
  "events": [
    {
      "patentApplicationNumber": "29666802",
      "officeActionDate": "2020-11-12T00:00:00",
      "officeActionCategory": "CTNF",
      "citationCategoryCode": "A",
      "examinerCitedReferenceIndicator": "True",
      "applicantCitedExaminerReferenceIndicator": "False",
      "workGroup": "2900-WG",
      "groupArtUnitNumber": "2921",
      "techCenter": "2900"
    }
  ],
  "source_class": "D18",
  "target_class": "D18"
}
```

### フィールド一覧

| フィールド | 型 | 内容 |
|-----------|-----|------|
| `source` | string | 引用された意匠特許 ID（例: `"D0550278"`） |
| `target` | string | 引用した意匠特許 ID（`source < target` でアルファベット順に正規化済み） |
| `source_images` | object | source が持つ図タイプ → 画像パスの対応表 |
| `target_images` | object | target が持つ図タイプ → 画像パスの対応表 |
| `events` | array | このペアを共引用した出願のレコード一覧（1件以上） |
| `source_class` | string | 本スクリプトが追加（`--class` で指定した値） |
| `target_class` | string | 本スクリプトが追加（`--class` で指定した値） |

**`source_images` / `target_images` のキー（図タイプ）:**

| キー | 内容 |
|------|------|
| `perspective` | パース図（斜視図） |
| `front` | 正面図 |
| `overview` | 上記いずれとも判定されなかった図 |

**`events` の各要素:**

| フィールド | 内容 |
|-----------|------|
| `patentApplicationNumber` | 出願番号 |
| `officeActionDate` | 拒絶理由通知日（ISO 8601） |
| `officeActionCategory` | 通知カテゴリ（例: `CTNF` = Non-Final Rejection） |
| `citationCategoryCode` | 引用カテゴリコード（例: `A` = 先行技術） |
| `examinerCitedReferenceIndicator` | 審査官による引用か（`"True"` / `"False"`） |
| `applicantCitedExaminerReferenceIndicator` | 出願人が審査官引用を引用したか（`"True"` / `"False"`） |
| `workGroup` | ワークグループ |
| `groupArtUnitNumber` | アートユニット番号 |
| `techCenter` | テクノロジーセンター番号 |

---

## D18 の実行結果（2025-05-18 時点）

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

2015〜2017 は `cited_image_pairs/` が空ファイルのため出力なし。

---

## 実行方法

```bash
# D18（デフォルト）全年処理
python filter_pairs_by_class.py

# 別クラスを指定
python filter_pairs_by_class.py --class D5

# 指定年のみ
python filter_pairs_by_class.py 2007 2008 --class D18

# 処理済みを上書き（データ更新時）
python filter_pairs_by_class.py --no-resume --class D18
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `years` | 全年 | 処理する年（複数指定可） |
| `--class` | `D18` | 抽出するクラスコード |
| `--no-resume` | — | 処理済みファイルを上書きする |

### 再開（resume）

デフォルトで有効。出力 JSONL が存在する年はスキップされる。  
中断後は同じコマンドを再実行するだけで続きから再開できる。

---

## データ更新時の再実行

| 状況 | 操作 |
|------|------|
| 新しい年の `cited_image_pairs/{year}.jsonl` が追加された | `python filter_pairs_by_class.py {year} --class {CLASS}` |
| 既存年のペアデータが更新された | `python filter_pairs_by_class.py {year} --no-resume --class {CLASS}` |
| `edge_list_with_class/{year}.csv` のクラス情報が更新された | 上と同じ（クラス情報を読み直すため `--no-resume` が必要） |

---

## 注意事項

- クラス CSV が存在しない年はスキップされる
- GPU 不要（テキスト処理のみ）

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [image_pairs.md](../../doc/image_pairs.md) | `filter_pairs_by_class.py` | [build_class_vectors.md](build_class_vectors.md) |
| `cited_image_pairs/{year}.jsonl` | → `class/{CLASS}/cited_image_pairs/{year}.jsonl` | `build_class_vectors.py` |
