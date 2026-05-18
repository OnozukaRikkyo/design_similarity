# 引用recency効果の可視化 (`analysis/citation_recency.py`)

USPTO 意匠特許共引用ネットワークにおける **ReceiverRecency 効果**を可視化するスクリプト。
累積共引用数（ヴィンテージ効果）と年間共引用率（Recency 効果）を出願年別箱ひげ図で比較し、
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
| 入力 | `/mnt/eightthdd/uspto/edge_list/*.csv` | CSV（共引用ペア） |
| 入力 | `/mnt/eightthdd/uspto/data/*.csv` | CSV（特許属性: `id`, `date`） |
| 出力 | `analysis/output/fig1_vintage_effect.png` | 300 DPI PNG |
| 出力 | `analysis/output/fig2_receiver_recency.png` | 300 DPI PNG |
| 出力 | `analysis/output/fig3_comparison.png` | 300 DPI PNG（学会発表用） |

---

## 出力図の詳細

### fig_vintage_effect.png — 引用次数（出願年別）

| 視覚要素 | 内容 |
|---------|------|
| タイトル | Vintage Effect: Citation Count by Filing Year |
| X 軸 | 特許出願年（全年表示・45° 斜め）|
| Y 軸 | Citation Count（リニアスケール、範囲 0–25） |
| 箱 | 四分位範囲（IQR）。外れ値は小点で表示 |
| 赤線 | 各年の中央値 |
| ひげ上注記 | 各年のデータ件数 n |
| 注釈 | 直感に反し **2013–2017 年特許が最も引用数が多い**（ReceiverRecency が絶対値でも優位） |

**実測中央値（2007–2017 年）:**

| 出願年 | パテント数 | 中央値 | IQR |
|-------|-----------|-------|-----|
| 2007 | 5,363 | 2.0 | [1.0, 3.0] |
| 2010 | 6,099 | 2.0 | [1.0, 3.0] |
| 2013 | 8,558 | 2.0 | [1.0, 5.0] |
| 2015 | 11,257 | 3.0 | [1.0, 6.0] |
| 2016 | 14,114 | 4.0 | [2.0, 9.0] |
| 2017 | 12,140 | 4.0 | [2.0, 8.0] |

### fig2_receiver_recency.png — 年間共引用率（出願年別）

| 視覚要素 | 内容 |
|---------|------|
| X 軸 | 特許出願年 |
| Y 軸 | 年間共引用率 = 累積共引用数 / 有効観測年数 |
| 注釈ボックス | ERGM ReceiverRecency 係数（β₅ᵧᵣ・β₁₀ᵧᵣ）の範囲 |

**実測中央値（年間率）:**

| 出願年 | 中央値 (citations/year) | IQR |
|-------|------------------------|-----|
| 2007 | 0.125 | [0.062, 0.188] |
| 2012 | 0.182 | [0.091, 0.364] |
| 2015 | 0.375 | [0.125, 0.750] |
| 2017 | 0.667 | [0.333, 1.333] |

2007 年→2017 年で中央値が **約 5.3 倍**に増加。ERGM の正の ReceiverRecency 係数と整合する。

### fig3_comparison.png — 2 パネル比較（学会発表推奨）

左右に並べることで「累積数でも近年特許が優位」「年間率では差がさらに拡大」という
ReceiverRecency 効果の構造が一目で伝わる。

---

## 年間率の計算式

```
annual_rate = cumulative_count / effective_age

effective_age = max(1, OBS_END_YEAR − max(filing_year, OBS_START_YEAR) + 1)
```

| 定数 | 値 | 意味 |
|------|---|------|
| `OBS_END_YEAR` | 2022 | edge_list の最終年 |
| `OBS_START_YEAR` | 2007 | edge_list の開始年 |

出願年が観測窓開始（2007）より古い特許は有効観測期間を 16 年（最大）に頭打ちする。

---

## 共引用数の定義

共引用ネットワーク上の**無向次数**を使用する。  
同一ペア（source, target）が複数の出願イベントで共引用されていても 1 エッジとしてカウントする。

```
count(patent P) = |{Q : (P, Q) は共引用ペアとして edge_list に存在}|
```

`edge_list/*.csv` の全ファイルを結合し、`source < target` に正規化した後に重複削除してから次数を集計する。

---

## データ規模（全年: 2007–2022 edge_list）

| 量 | 値 |
|----|---|
| edge_list 総行数（重複含む） | 323,132 |
| 重複除去後ユニークエッジ数 | — |
| 共引用ネットワーク上のノード数 | 91,556 |
| 出願年が判明したノード数 | 91,556（100%） |
| 有効ビン（≥ 10 件）の年範囲 | 2007–2017 |

**2018–2022 年特許がネットワークに出現しない理由:** 出願から付与まで平均 1〜2 年かかるため、
2018 年以降に付与された意匠特許は 2022 年時点では先行技術として引用される期間が短く、
共引用ネットワークへの組み込みがほぼゼロ。これ自体が ReceiverRecency の傍証となる。

---

## 図スタイル

Physical Review Letters (PRL) 準拠の物理学論文スタイル。

| 設定項目 | 値 |
|----------|----|
| フォント | serif（DejaVu Serif） |
| 目盛り方向 | 内向き（4 辺すべて） |
| 補助目盛り | Y 軸に `AutoMinorLocator` |
| 解像度 | 300 DPI |
| 背景 | 白（`figure.facecolor = white`） |
| グリッド | 有効（薄灰 `#DDDDDD`、α=0.7） |

---

## 実行方法

```bash
# デフォルト実行
python analysis/citation_recency.py

# パス・ビン閾値を指定
python analysis/citation_recency.py \
    --edge-dir /mnt/eightthdd/uspto/edge_list \
    --data-dir /mnt/eightthdd/uspto/data \
    --out-dir  analysis/output \
    --min-n    10

# 観測窓の末尾年を変更（例: 2020 年時点の分析）
python analysis/citation_recency.py --obs-end 2020
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--edge-dir` | `/mnt/eightthdd/uspto/edge_list` | 共引用ペア CSV のディレクトリ |
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