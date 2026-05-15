# 2種ヒートマップ生成スクリプト (`make_two_heatmaps.py`)

Reference（全ペア）と LLM 類似判定ペアの2種類のクラス間頻度ヒートマップを、APS Physical Review 準拠の査読対応品質で生成する。

---

## スクリプト

```
/home/sonozuka/design_similarity/make_two_heatmaps.py
```

---

## 生成される画像

| ファイル | 内容 |
|---------|------|
| `output/heatmap_reference.png` | Reference：審査官引用ペア全件 |
| `output/heatmap_similar.png`   | LLM 類似判定ペア（exact_match + high_similar + similar） |

---

## 入力データ

### Heatmap 1 — Reference（全ペア）

```
/mnt/eightthdd/uspto/all_pair/qwen_all_pairs/
├── 2007.jsonl
├── 2008.jsonl
…
└── 2012.jsonl
```

### Heatmap 2 — LLM 類似ペア

```
/mnt/eightthdd/uspto/yes_pair/qwen/
├── exact_match/jsonl/2007.jsonl … 2012.jsonl
├── high_similar/jsonl/2007.jsonl … 2012.jsonl
└── similar/jsonl/2007.jsonl … 2012.jsonl
```

各ディレクトリを再帰的に `rglob("*.jsonl")` で検索する。

### 使用する JSONL フィールド

| フィールド | 用途 |
|-----------|------|
| `source_class` | 引用する側の D-class（例: `"D14 38"` → `"D14"`） |
| `target_class` | 引用される側の D-class |

---

## 実行方法

```bash
cd /home/sonozuka/design_similarity
python make_two_heatmaps.py
```

引数なし。入力・出力パスはすべてスクリプト内にインライン記述。

---

## 主要関数

| 関数 | 役割 |
|------|------|
| `parse_class(raw)` | `"D 6480"` → `"D06"`、`"D34 38"` → `"D34"`（ゼロ埋め2桁） |
| `load_class_pairs(roots)` | 複数ディレクトリの JSONL を再帰的に読み込み、クラスペア件数・クラス別件数を返す |
| `make_heatmap(...)` | N×N 行列を描画・保存（APS スタイル適用） |

---

## ヒートマップの見方

| 視覚要素 | 意味 |
|---------|------|
| 行（y 軸） | Source class：引用する側（citing patent）の D-class |
| 列（x 軸） | Target class：引用される側（cited patent）の D-class |
| セルの色 | `ln(件数 + 1)`（YlOrRd カラーマップ） |
| ティール枠（対角） | Within-class ペア（同一クラス内） |
| セル内の数値 | 最大値の 4% 以上のセルに実件数を表示 |
| 右上の注釈ボックス | $N$（総ペア数）、Within/Cross-class 比率 |

### 軸ラベルについて

軸には分類コード（`D06` など）のみ表示する。コードと名称の対応は `CLASS_NAMES` 辞書（スクリプト内）に保持しており、別途 CSV で出力予定。

---

## D-class 名称マッピング（`CLASS_NAMES`）

出典：`/home/sonozuka/multimodal/plot_class_histogram.py`

| コード | 名称 |
|--------|------|
| D01 | Edible Products |
| D02 | Apparel & Haberdashery |
| D03 | Travel Goods & Personal Items |
| D04 | Brushware |
| D05 | Textile/Fabric Articles |
| D06 | Furnishings |
| D07 | Equipment for Preparing Food |
| D08 | Tools & Hardware |
| D09 | Tools & Hardware (misc) |
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

## 図のスタイル（APS Physical Review 準拠）

| 項目 | 設定値 |
|------|--------|
| フォント | Times New Roman / STIX（LaTeX 数式統一） |
| DPI | 600（印刷投稿基準） |
| 図サイズ | 9.5 × 8.5 inch（ダブルカラム相当） |
| タイトル | "Figure" プレフィックスなし |
| X 軸ラベル | 45° 斜め、右揃え |
| 目盛り方向 | 内向き、上辺・右辺にも表示 |
| カラーバー | $\ln(\mathrm{count}+1)$ を LaTeX 数式で表記 |
| 統計注釈 | 右上、15pt、背景半透過（alpha=0.55） |
| PDF フォント埋め込み | `pdf.fonttype=42`（TrueType） |

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [extract_all_pairs.md](extract_all_pairs.md) | `make_two_heatmaps.py` | 論文・プレゼン資料への組み込み |
| [extract_yes_pairs.md](extract_yes_pairs.md) | ↓ | D-class 名称 CSV 出力（予定） |
| `qwen_all_pairs/**/*.jsonl` | → `output/heatmap_reference.png` | — |
| `yes_pair/qwen/**/*.jsonl` | → `output/heatmap_similar.png` | — |