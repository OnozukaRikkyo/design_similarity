# 高信頼 Triadic ペアの画像抽出

`graph/extract_high_sim_triads.py` により、triadic 確信度スコアで順位付けされた全 3-clique から上位・下位 N 件を抽出し、各 triad の 3 枚の特許画像を横並びにした確認図を生成する。

---

## 入力

| ファイル | 内容 |
|---|---|
| `graph/output/D18/triadic_scored.jsonl` | 全 1593 三角形のスコア（confidence 降順） |
| `/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl` | patent_id → 画像パスのマップ源 |
| `/mnt/eightthdd/uspto/data/{year}.csv` | patent_id → 意匠タイトルのマップ源（`title` 列） |

画像ファイルは TIFF 形式（1-bit bi-level, PhotometricInterpretation=WhiteIsZero）。

---

## 出力

`graph/output/D18/high_sim_triads/`

| ファイル | 内容 |
|---|---|
| `overview.png` | 上位 N 件を縦に並べた概観図（1枚） |
| `overview_bottom.png` | 下位 N 件の概観図（`--bottom` 時） |
| `triad_001.png` 〜 | 上位 N 件の個別図（3枚横並び + メタ情報） |
| `bottom_001.png` 〜 | 下位 N 件の個別図（`--bottom` 時） |
| `triad_summary.csv` | 上位 N 件の triad メタデータ（ID・タイトル・スコア） |
| `bottom_summary.csv` | 下位 N 件の triad メタデータ（`--bottom` 時） |

`graph/output/D18/`（`graph_analysis.py` が生成）

| ファイル | 内容 |
|---|---|
| `summary.csv` | D18 グラフ全体の基本統計（ノード数・ペア数・三角形数など） |
| `triadic_scored.jsonl` | 全 1593 三角形のスコア（confidence 降順） |

---

## 抽出ルール

### デフォルト（上位抽出）

1. 全 1593 三角形にフィルタを適用
   - `S1 (weakest-link) ≥ 0.90`：三辺すべての cosine 類似度が 0.90 以上
   - `S3 (Schubert compliance) ≥ 0.70`：幾何的整合性の下限
2. フィルタ通過分を confidence 降順にソートし、上位 N 件を選択

D18 での結果（デフォルト条件）: 1593件 → 274件 → 上位 30件  
confidence 範囲（上位 30）: **0.8981 〜 0.9298**

### 下位抽出（`--bottom`）

フィルタを適用せず、全 1593 件を confidence 昇順に並べて下位 N 件を選択。

D18 での結果（`--bottom -N 10`）:  
confidence 範囲（下位 10）: **0.3440 〜 0.4489**

---

## 画像処理

TIF ファイルは 1-bit 2値（白背景・黒線）。PIL で `'L'` モードに変換後、以下の処理を適用する。

### 線強調パイプライン

```
TIF (WhiteIsZero)
  └─ PIL convert('L')     → paper=255, lines≈0
  └─ 2値化 (< 128)        → line_mask (True=線, False=背景)
  └─ 線強調（下記選択）
  └─ 出力配列             → lines=0 (最大黒), background=255 (白)
```

`cmap='gray', vmin=0, vmax=255` で表示: 0=黒（最大）, 255=白。

### 線強調手法（`--line-enhance` で選択）

| 手法 | 内容 |
|---|---|
| `dilation`（デフォルト） | 二値膨張 3×3 正方形構造要素、1回。線を 1px 太くする |
| `closing` | Closing（膨張→侵食）。線の切れ目を補完しつつ太くする |
| `gaussian` | ガウスぼかし（σ=0.8）後に再2値化。滑らかな細線 |
| `none` | 2値化のみ（強調なし） |

---

## 個別図のレイアウト

```
┌──────────┬──────────┬──────────┬────────────────────┐
│  Image A │  Image B │  Image C │  メタ情報           │
│  patent  │  patent  │  patent  │  rank    : 1        │
│  画像    │  画像    │  画像    │  conf    : 0.9298   │
│          │          │          │  ─────────────      │
├──────────┼──────────┼──────────┤  S1 (min): 0.9754  │
│ D0XXXXXX │ D0XXXXXX │ D0XXXXXX │  S2 (ang): 0.8586  │  ← 特許 ID（上段）
│ title A  │ title B  │ title C  │  S3 (sch): 0.9183  │  ← 意匠タイトル（下段）
│ s_AB     │ s_AB     │ s_BC     │  S4 (snn): 1.0000  │  ← cosine similarity
│ s_AC     │ s_BC     │ s_AC     │  ─────────────      │
│          │          │          │  s_AB    : 0.9754  │
│          │          │          │  s_BC    : 0.9770  │
│          │          │          │  s_AC    : 0.9923  │
└──────────┴──────────┴──────────┴────────────────────┘
```

各パネルの表示内容:
- **タイトル行**（上）: 特許 ID（例: `D0724142`）
- **xlabel 行**（下）: 意匠タイトル（例: `Electronic device`）＋ cosine similarity ペア

タイトルは `/mnt/eightthdd/uspto/data/{year}.csv` の `title` 列から全年スキャンで取得。
D18 対象 1030 件すべてでタイトルを確認済み。

---

## 実行コマンド

```bash
cd /home/sonozuka/design_similarity

# デフォルト: S1≥0.90, S3≥0.70 でフィルタ後、上位 30 件
python graph/extract_high_sim_triads.py

# フィルタ条件を変える（上位 20 件）
python graph/extract_high_sim_triads.py --min-s1 0.95 -N 20

# フィルタなしで上位 50 件
python graph/extract_high_sim_triads.py --no-filter -N 50

# 最下位 10 件（比較用）
python graph/extract_high_sim_triads.py --bottom -N 10

# 線強調手法を変える
python graph/extract_high_sim_triads.py --line-enhance closing
python graph/extract_high_sim_triads.py --line-enhance gaussian
python graph/extract_high_sim_triads.py --line-enhance none

# overview のみ（個別図を省略、高速）
python graph/extract_high_sim_triads.py --no-individual -N 50
```

---

## summary.csv の列定義（`graph_analysis.py` 出力）

`graph/output/D18/summary.csv` — D18 共引用グラフの基本統計を metric/value 形式で格納。

| metric | 内容 |
|---|---|
| `patents_nodes` | ユニーク特許数（グラフのノード数） |
| `pairs_edges` | 共引用ペア数（グラフのエッジ数） |
| `triangles_3cliques` | 3-clique（三角形）の総数 |
| `pairs_perspective` | 画像タイプ perspective のペア数 |
| `pairs_overview` | 画像タイプ overview のペア数 |
| `pairs_front` | 画像タイプ front のペア数 |
| `degree_min/median/max` | ノード次数の最小・中央値・最大 |
| `cosine_sim_min/median/max` | エッジ cosine 類似度の最小・中央値・最大 |
| `s1_weakest_link_*` | Score 1 の最小・中央値・最大 |
| `s2_angular_tightness_*` | Score 2 の最小・中央値・最大 |
| `s3_bound_compliance_*` | Score 3 の最小・中央値・最大 |
| `s4_snn_*` | Score 4 の最小・中央値・最大 |
| `confidence_min/median/max` | 統合確信度の最小・中央値・最大 |

D18 実測値:

| metric | value |
|---|---|
| patents_nodes | 1030 |
| pairs_edges | 1530 |
| triangles_3cliques | 1593 |
| pairs_perspective | 1447 |
| pairs_overview | 74 |
| pairs_front | 9 |
| degree_min | 1 |
| degree_median | 2.0 |
| degree_max | 21 |
| cosine_sim_min | 0.401826 |
| cosine_sim_median | 0.891905 |
| cosine_sim_max | 0.996734 |
| confidence_min | 0.344034 |
| confidence_median | 0.758897 |
| confidence_max | 0.929797 |

## triad_summary.csv の列定義（`extract_high_sim_triads.py` 出力）

| 列 | 内容 |
|---|---|
| `rank` | confidence 順位（全 1593 件中） |
| `A`, `B`, `C` | 三角形を構成する特許 ID |
| `title_A`, `title_B`, `title_C` | 各特許の意匠タイトル |
| `s_AB`, `s_BC`, `s_AC` | 各辺の cosine 類似度 |
| `score_weakest_link` | S1 |
| `score_angular_tightness` | S2 |
| `score_bound_compliance` | S3 |
| `score_snn` | S4 |
| `confidence` | 統合確信度（加重和） |

---

## D18 スコア分布の比較

| | confidence 範囲 | 件数 |
|---|---|---|
| 全体 | 0.3440 〜 0.9298 | 1593 |
| フィルタ後（S1≥0.90, S3≥0.70） | 0.8277 〜 0.9298 | 274 |
| 上位 30 件 | 0.8981 〜 0.9298 | 30 |
| 下位 10 件 | 0.3440 〜 0.4489 | 10 |
