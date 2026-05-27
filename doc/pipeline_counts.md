# 論文集計値の出力と検証 (`export_pipeline_counts.py`)

論文テーブル "Summary counts for the citation-judgment-retrieval pipeline" の元データ CSV を生成するスクリプトと、各数値のデータ実測による検証結果をまとめる。

---

## スクリプト

```
/home/sonozuka/design_similarity/export_pipeline_counts.py
```

---

## 入出力

| | パス | 内容 |
|---|---|---|
| 入力 | `output/diagonal_summary.csv` | 引用ペア数・MLLM類似ペア数（`export_diagonal_csv.py` の出力） |
| 入力 | `class/D18/rank_index/perspective/patent_ids.npy` | D18 ユニーク特許 ID 一覧 |
| 入力 | `class/D18/rank_judgments/cosine_numpy/all.jsonl` | D18 判定付き引用ペア |
| 出力 | `output/pipeline_counts.csv` | 論文テーブル用集計 CSV |

---

## 出力 CSV スキーマ

| `stage` | `item` | 算出方法 |
|---------|--------|---------|
| IMPACT dataset | U.S. design patents | 定数（下記参照） |
| IMPACT dataset | Patent drawing figures | 定数（下記参照） |
| Full examiner-citation reference set | Citation pairs, all classes | `diagonal_summary.csv` の reference 合計 |
| Full examiner-citation reference set | Within-class pairs | `diagonal_summary.csv` の `reference_diagonal` 合計 |
| Full examiner-citation reference set | Cross-class pairs | `diagonal_summary.csv` の `reference_cross_class` 合計 |
| MLLM-judged similar pairs | Total | `diagonal_summary.csv` の similar 合計 |
| D18 embedding index | Unique patents | `patent_ids.npy` の要素数 |
| D18 embedding index | Citation-pair records | `all.jsonl` の行数 |

---

## IMPACT データセット定数

`export_pipeline_counts.py` に直書きされた定数。公式 IMPACT データセット論文・公開資料に基づく値であり、ローカルデータのカウントとは独立している（下記「検証」参照）。

```python
IMPACT_PATENTS  = 435_101
IMPACT_FIGURES  = 3_609_805
```

---

## 数値検証（2026-05-27）

本文に登場する全数値をローカルデータから実測したときの結果。

### ✅ 一致した数値

| 本文の記述 | 実測値 | 検証方法 |
|---|---|---|
| 55,794 examiner-citation pairs | **55,794** | `qwen_all_pairs` 全年を `parse_class` でフィルタして集計 |
| within-class 53,823（96.5%） | **53,823（96.46%）** | `diagonal_summary.csv` の `reference_diagonal` 合計 |
| cross-class 1,971（3.5%） | **1,971（3.54%）** | `diagonal_summary.csv` の `reference_cross_class` 合計 |
| D18: 959 unique patents | **959** | `rank_index/perspective/patent_ids.npy` の要素数 |
| D18: 1,530 citation-pair records | **1,530** | `rank_judgments/cosine_numpy/all.jsonl` の行数 |

### ⚠️ ローカルデータと不一致の数値

| 本文の記述 | ローカルデータ実測 | 差分 | 備考 |
|---|---|---|---|
| **435,101** U.S. design patents | 434,498 行 / 434,497 unique ID | −604 | 定数として直書き。公式 IMPACT 論文値の可能性が高い |
| **3,609,805** patent-drawing figures | TIF 実ファイル数: **3,030,160** | −579,645 | 下記「図数の注意点」を参照 |

#### 引用ペア 55,794 の算出ロジック

`cited_image_pairs/` に存在する全ペアは 422,109 件だが、そのうち source・target 両方の意匠分類コードが `D{1〜2桁の数字} {サブクラス}` 形式で D01〜D34 に解析できるものだけを集計した結果が 55,794 件となる。

`export_diagonal_csv.py` の `parse_class()` 関数が判定基準：

```python
def parse_class(raw: str) -> str:
    m = re.match(r"D\s*0*(\d+)", str(raw).strip(), re.I)
    if not m:
        return "D??"
    n = int(m.group(1))
    if (1 <= n <= 34) or n == 99:
        return f"D{n:02d}"
    return "D??"
```

- `"D18 50"` → n=18 → `"D18"` ✓（スペースで区切られた形式）
- `"D14138"` → n=14138 → `"D??"` ✗（スペースなし連結形式、除外）

残り 366,315 件（= 422,109 − 55,794）は `D??` クラスとして除外される。

#### 図数の注意点

`/mnt/eightthdd/impact/images/` の TIF ファイル実数（macOS `._` リソースフォークファイルを除く）：

| 年 | TIF ファイル数 |
|----|-------------:|
| 2007 | 128,486 |
| 2008 | 139,578 |
| 2009 | 133,628 |
| 2010 | 132,662 |
| 2011 | 132,449 |
| 2012 | 138,897 |
| 2013 | 153,017 |
| 2014 | 154,028 |
| 2015 | 175,890 |
| 2016 | 196,061 |
| 2017 | 218,791 |
| 2018 | 229,528 |
| 2019 | 269,715 |
| 2020 | 271,096 |
| 2021 | 272,851 |
| 2022 | 283,483 |
| **合計** | **3,030,160** |

> **注意**: 2022 年フォルダには macOS 由来の `._USD*.TIF` リソースフォークファイルが混入しており、`find -name "*.TIF"` でカウントすると 566,966（実ファイルの 2 倍）になる。`ls` または `ls -1` を使うこと。

`data/{year}.csv` の `no_figs` 列合計は 3,408,983。論文の 3,609,805 はいずれとも一致せず、公式 IMPACT 論文が採用した計数方法によるものと考えられる。

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [export_diagonal_csv.md](export_diagonal_csv.md) | `export_pipeline_counts.py` | 論文テーブルへの直接引用 |
| [join_judgments.md](../vector/doc/join_judgments.md) → `all.jsonl` | → `output/pipeline_counts.csv` | — |
