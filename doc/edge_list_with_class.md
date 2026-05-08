# 意匠分類付きエッジリスト (`add_class_to_edge_list.py`)

共引用エッジリスト CSV に source・target それぞれの**意匠分類コード**と**分類名**を付与した
`edge_list_with_class/<year>.csv` を生成する。

---

## スクリプト

```
/home/sonozuka/design_similarity/add_class_to_edge_list.py
```

---

## 入出力

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/data/*.csv`（全年分） | CSV (`id`, `class` 列を使用) |
| 入力 | `/mnt/eightthdd/uspto/edge_list/<year>.csv` | CSV (`build_edge_list.py` の出力) |
| 出力 | `/mnt/eightthdd/uspto/edge_list_with_class/<year>.csv` | CSV |
| キャッシュ | `/mnt/eightthdd/uspto/edge_list_with_class/_class_index.pkl` | pickle |

---

## 処理フロー

```
data/*.csv  ──→  build_class_index()  ──→  class_index (dict)
                  └─ pickle キャッシュ              │
                     (_class_index.pkl)             │
                                                    │
edge_list/<year>.csv  ──→  add_class()  ←───────────┘
                                │
                                │  source/target ごとにクラスを付与
                                ↓
                   edge_list_with_class/<year>.csv
```

### `build_class_index()`

`data/*.csv` の全行を走査し `{ patent_id: main_class }` の dict を構築する。
初回構築後は `_class_index.pkl` に pickle キャッシュされ、2回目以降は即座にロードされる。

### `extract_main_class()`

`class` 列の文字列からメインクラス（例: `"D14"`, `"D9"`）を抽出するパーサ。
`plot_class_histogram.py` と共通のロジック。

| 入力形式 | 例 | 出力 |
|----------|-----|------|
| カンマ区切り複数クラス | `"D14422,D18 50"` | `"D14"` (先頭のみ使用) |
| スペース入り1桁 | `"D 9"` | `"D9"` |
| 2桁クラス (D10-D34, D99) | `"D23366"` | `"D23"` |
| 1桁クラス (D1-D9) | `"D6..."` | `"D6"` |

### `add_class()`

エッジリストを行ごとに読み込み、`class_index` で `source`・`target` を O(1) 検索して
クラス列を追記する。クラスが不明な行もスキップせず出力し、空文字を付与する。

---

## 出力カラム

元の全カラムに加えて以下の 4 列を末尾に追加する。

| カラム | 例 | 内容 |
|--------|-----|------|
| `source_class` | `D14` | source のメイン意匠分類コード |
| `source_class_name` | `Recording/Communication/Info` | source の分類名 |
| `target_class` | `D23` | target のメイン意匠分類コード |
| `target_class_name` | `Environmental Heating/Cooling` | target の分類名 |

クラスが不明な場合は `source_class`・`source_class_name` ともに空文字。

### 意匠分類コード一覧

| コード | 分類名 |
|--------|--------|
| D1 | Edible Products |
| D2 | Apparel & Haberdashery |
| D3 | Travel Goods & Personal Items |
| D4 | Brushware |
| D5 | Textile/Fabric Articles |
| D6 | Furnishings |
| D7 | Equipment for Preparing Food |
| D8 | Tools & Hardware |
| D9 | Tools & Hardware (misc) |
| D10 | Measuring/Testing Devices |
| D11 | Jewelry/Symbolic Insignia |
| D12 | Transportation |
| D13 | Equipment for Production/Distribution |
| D14 | Recording/Communication/Info |
| D15 | Machines |
| D16 | Photography & Optics |
| D17 | Musical Instruments |
| D18 | Printing & Office Machinery |
| D19 | Office Supplies/Equipment |
| D20 | Sales/Advertising/Signs |
| D21 | Amusement Devices |
| D22 | Arms/Pyrotechnics/etc. |
| D23 | Environmental Heating/Cooling |
| D24 | Medical/Lab Equipment |
| D25 | Building Units & Construction |
| D26 | Lighting |
| D27 | Tobacco & Smoking |
| D28 | Pharmaceuticals & Cosmetics |
| D29 | Animal Husbandry |
| D30 | Outdoor/Garden |
| D31 | Articles of Manufacture |
| D32 | Washing/Cleaning Equipment |
| D33 | Food/Beverage Service |
| D34 | Material/Article Handling |
| D99 | Miscellaneous |

---

## 実行方法

```bash
# 全年処理（edge_list/ 以下の全 CSV を対象）
python add_class_to_edge_list.py

# 指定年のみ
python add_class_to_edge_list.py 2007 2008

# クラス索引を再構築してから処理（data/ に変更があった場合）
python add_class_to_edge_list.py --rebuild
```

---

## 前後の処理との関係

パイプラインの STEP 2c（分析用サイドブランチ）として実行する。
入力は STEP 1 出力の `edge_list/<year>.csv` のみであり、STEP 2a・3・4 とは独立している。

| 前工程 | 本スクリプト | 想定される後工程 |
|--------|-------------|----------------|
| [citation_graph.md](citation_graph.md) | `add_class_to_edge_list.py` | クラス間共引用の集計・可視化 |
| `build_edge_list.py` → `edge_list/<year>.csv` | → `edge_list_with_class/<year>.csv` | クロスクラスエッジの分析など |

パイプライン全体の位置付けは [pipeline.md](pipeline.md) を参照。