# 引用recency効果の可視化 (`analysis/citation_recency.py`)

USPTO 意匠特許共引用ネットワークにおける **ReceiverRecency 効果**を可視化するスクリプト。
累積共引用数（ヴィンテージ効果）と年間共引用率（Recency 効果）を**公告年別**箱ひげ図で比較し、
ERGM の ReceiverRecency 係数と対応付けて示す。

---

## スクリプト

```
/home/sonozuka/design_similarity/analysis/citation_recency.py
```

---

## 入出力

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/all_pair/qwen_all_pairs/*.jsonl` | JSONL（論文の 55,794 ペアと同一集合） |
| 入力 | `/mnt/eightthdd/uspto/data/*.csv` | CSV（特許属性: `id`, `date`） |
| 出力 | `analysis/output/fig_vintage_effect.png` | 300 DPI PNG |
| 出力 | `analysis/output/fig_recency_rate.png` | 300 DPI PNG |

> **変更履歴（2026-05-27）**: エッジソースを `edge_list/*.csv`（全引用・クラス不問）から
> `qwen_all_pairs/*.jsonl` + `parse_class` フィルタ（D01〜D34）に変更。
> 図の N 値が論文記載の 55,794 ペアと同一集合に対応するようになった。
> X 軸ラベルも "Filing Year" → "Publication Year" に修正（`date` 列 = 公告日）。

---

## 出力図の詳細

### fig_vintage_effect.png — 引用次数（公告年別）

| 視覚要素 | 内容 |
|---------|------|
| X 軸 | 特許公告年（Publication Year）|
| Y 軸 | Citation Count（リニアスケール、範囲 0–16） |
| 箱 | 四分位範囲（IQR）。外れ値は小点で表示 |
| 黒線 | 各年の中央値 |
| ひげ先端の横線（cap） | Q3 + 1.5×IQR 以内の最大実データ点。固定パーセンタイルではなく分布形状に依存する |
| ひげ上注記 | 各年のユニーク特許数 n（55,794 ペアに登場する特許の公告年別集計） |

> **Y 軸クリップについて**: 全体の最大次数は **105**、degree > 16 の特許は 651 件（全体の 2.7%）存在するが、
> `set_ylim(0, 16)` により表示範囲外となっている。ひげを超えた外れ値点は `markersize=2.0, alpha=0.4` の
> 小点として描かれているが、視認困難。主要な分布（中央値・IQR）の比較を目的とした図であり、
> 高次数の外れ値の存在は caption またはテキスト側で言及することが望ましい。

**実測値（2026-05-27 時点, 55,794 ペア / 24,449 ユニーク特許）:**

| 公告年 | パテント数 n |
|--------|------------:|
| 2007 | 922 |
| 2008 | 947 |
| 2009 | 908 |
| 2010 | 948 |
| 2011 | 1,087 |
| 2012 | 1,110 |
| 2013 | 1,277 |
| 2014 | 1,292 |
| 2015 | 1,596 |
| 2016 | 1,862 |
| 2017 | 2,396 |
| 2018 | 2,310 |
| 2019 | 2,652 |
| 2020 | 2,044 |
| 2021 | 1,898 |
| 2022 | 1,200 |
| **合計** | **24,449** |

### fig_recency_rate.png — 年間共引用率（公告年別）

| 視覚要素 | 内容 |
|---------|------|
| X 軸 | 特許公告年（Publication Year） |
| Y 軸 | 年間共引用率 = 累積共引用数 / 有効観測年数 |

---

## 年間率の計算式

```
annual_rate = cumulative_count / effective_age

effective_age = max(1, OBS_END_YEAR − max(pub_year, OBS_START_YEAR) + 1)
```

| 定数 | 値 | 意味 |
|------|---|------|
| `OBS_END_YEAR` | 2022 | 観測窓末尾年 |
| `OBS_START_YEAR` | 2007 | 観測窓開始年 |

---

## 共引用数の定義

共引用ネットワーク上の**無向次数**を使用する。  
`qwen_all_pairs/*.jsonl` を `parse_class` フィルタ（D01〜D34）で絞り込んだ
55,794 ペアのみを対象とし、同一ペアは 1 エッジとしてカウントする。

```
count(patent P) = |{Q : (P, Q) は 55,794 ペア集合に存在}|
```

---

## データ規模（全年: 2007–2022）

| 量 | 値 |
|----|---|
| qwen_all_pairs 総ペア数 | 462,641 |
| parse_class フィルタ後（D01〜D34） | 55,794 |
| 共引用ネットワーク上のユニーク特許数 | 24,449 |
| 公告年が判明したノード数 | 24,449（100%） |
| 有効ビン（≥ 10 件）の年範囲 | 2007–2022 |

---

## 図スタイル

Physical Review Letters (PRL) 準拠の物理学論文スタイル。

| 設定項目 | 値 |
|----------|----|
| フォント | serif（DejaVu Serif） |
| 目盛り方向 | 内向き（4 辺すべて） |
| 解像度 | 300 DPI |
| 背景 | 白（`figure.facecolor = white`） |

---

## 実行方法

```bash
# デフォルト実行
python analysis/citation_recency.py

# パス・ビン閾値を指定
python analysis/citation_recency.py \
    --edge-dir /mnt/eightthdd/uspto/all_pair/qwen_all_pairs \
    --data-dir /mnt/eightthdd/uspto/data \
    --out-dir  analysis/output \
    --min-n    10

# 観測窓の末尾年を変更（例: 2020 年時点の分析）
python analysis/citation_recency.py --obs-end 2020
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--edge-dir` | `/mnt/eightthdd/uspto/all_pair/qwen_all_pairs` | 共引用ペア JSONL のディレクトリ |
| `--data-dir` | `/mnt/eightthdd/uspto/data` | 特許属性 CSV のディレクトリ |
| `--out-dir` | `analysis/output` | PNG 出力先 |
| `--min-n` | `10` | ビンに含む最低特許件数 |
| `--obs-end` | `2022` | 観測窓末尾年 |

---

## ERGM ReceiverRecency 係数との対応

| ERGM 変数 | 係数範囲 | 意味 |
|-----------|---------|------|
| `ReceiverRecency_5yr` | β = +0.07 〜 +0.20 | 出願から 5 年以内の特許ほど共引用されやすい |
| `ReceiverRecency_10yr` | β = +0.29 〜 +0.51 | 出願から 10 年以内の特許ほど共引用されやすい |

年間引用率の中央値比（2007 年 → 2017 年 = 0.125 → 0.667）はこの正の係数と整合し、
ERGM 係数の符号を記述統計レベルで直感的に説明する。

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `build_edge_list.py`（STEP 1） | `analysis/citation_recency.py` | 論文・発表スライドへの組み込み |
| `/mnt/eightthdd/uspto/edge_list/*.csv` | → `analysis/output/fig*.png` | — |
| `/mnt/eightthdd/uspto/data/*.csv` | → 出願年の取得 | — |

`ergm_input/` や Gemini 判定結果には依存せず、STEP 1 の出力のみで独立実行できる。