# ランク検索結果の統計分析・可視化 (`rank_analysis.py`)

`join_judgments.py`（Step 3）が生成した `all.jsonl` を読み込み、`reason` フィールドのキーワードマッチで Yes ペアを **Exact match** / **Non-exact similar** に分類したうえで、3 種の図を生成する。

**前提**: `join_judgments.py` の実行完了後に本スクリプトを実行すること。
処理順序の全体像は [pipeline.md](pipeline.md) を参照。

---

## スクリプト

```
vector/analysis/rank_analysis.py
```

---

## 出力ファイル

```
vector/output/{CLASS}/{sim_func}/
  rank_ccdf_{type}.png              — Figure 1: 順位の CCDF
  rank_scatter_{type}.png           — Figure 2: 順位 vs 類似度の散布図
  rank_scatter_{type}_zoom.png      — Figure 2b: 散布図拡大（rank ≤ 20, sim ≥ 0.85）
  high_sim_{type}_0950.csv          — 高類似度レコード（similarity ≥ 0.950）
  pair_comparison/
    {src}--{tgt}_{type}_top10.png   — Figure 3: ベースペア + Top-10 近傍グリッド
```

---

## Figure 1: 順位の CCDF

**横軸**: 順位 $r$（1〜`n_candidates`）  
**縦軸**: $P(\mathrm{rank} \geq r)$（補累積分布関数）

| 系列 | 内容 |
|------|------|
| Similar (Yes) | LLM が類似と判定した引用ペア（青実線） |
| Non-similar (No) | LLM が非類似と判定した引用ペア（赤破線） |
| Random baseline | 順位が一様分布の場合の期待値（灰点線） |

**D18 perspective の観察（2026-05-18）:**

- Yes 群の中央値ランク: **4** / 456  
- No 群の中央値ランク: **29** / 456  
- 両群ともランダム期待値（斜線）を大きく下回り、ベクトル類似度が引用の視覚的関係を捉えていることを示す  
- Yes 群は No 群より急峻に降下 → LLM 判定と視覚的類似度ランクの整合性を確認

---

## Figure 2: 順位 vs 類似度の散布図

**横軸**: 順位 $r$  
**縦軸**: コサイン類似度

`judgment=Yes` のレコードは、`reason` テキストのキーワードマッチにより **Exact match** と **Similar, non-exact** に分類されてプロットされる。

| マーカー | 色 | 意味 |
|---------|-----|------|
| 赤×（Non-similar） | 赤 | LLM 非類似判定の引用ペア |
| 灰△（Unknown） | グレー | Qwen 結果に対応なし |
| 紫□ 中抜き（Exact match） | 紫 | Yes かつ reason に完全一致キーワードを含む |
| 青◇ 中抜き（Similar, non-exact） | 青 | Yes かつ reason に完全一致キーワードを含まない |

### Exact / Non-exact 分類ロジック

```python
FALLBACK_EXACT_KEYWORDS = ["identical", "exact", "same"]
```

`reason` 文字列に対して単語境界（`\b`）付き正規表現でいずれかがマッチすれば **Exact match**、しなければ **Non-exact**。`--use-llm` を付けると Qwen3-VL-4B-Instruct がキーワードを動的に取得する（詳細は [export_non_exact_pairs.md](export_non_exact_pairs.md) 参照）。

### D18 perspective の観察（2026-05-19）

- Exact match（102 件）は低ランク・高類似度（左上）に密集
- Non-exact similar（7 件）はランク 5〜18 付近に散在し、類似度もやや低め
- Exact match は類似度 ≥ 0.9 の領域で Non-similar と明確に分離できる

---

## CSV エクスポート: 高類似度レコード（`export_high_sim_csv`）

`similarity >= 0.950` のレコードを類似度降順でソートし CSV に出力する。

**出力列:**

| 列名 | 内容 |
|------|------|
| `source` | クエリ特許番号 |
| `target` | 引用対象特許番号 |
| `rank` | コサイン類似度ランク |
| `n_candidates` | 候補数 |
| `similarity` | コサイン類似度 |
| `judgment` | LLM 判定（Yes / No / Unknown） |
| `confidence` | 信頼度（1〜5） |
| `reason` | LLM が判定した理由テキスト |
| `source_image` | クエリ画像ファイルパス |
| `target_image` | 引用対象画像ファイルパス |

**D18 perspective の結果（2026-05-20）:**

- 該当件数: **370 件** / 1447 件中

---

## Figure 3: ペア比較画像グリッド

**構成（3行 × 5列）:**

| 位置 | 内容 |
|------|------|
| Row 0, Col 0–1 | Query 画像 A（クエリ特許） |
| Row 0, Col 2–3 | Expected 画像 B（引用対象、LLM 判定付き） |
| Row 0, Col 4 | 統計情報テキストボックス |
| Row 1, Col 0–4 | Top-1 〜 Top-5 近傍（類似度降順） |
| Row 2, Col 0–4 | Top-6 〜 Top-10 近傍 |

引用対象 B が Top-10 に含まれる場合はオレンジ枠と `[cited target]` ラベルで強調表示する。

画像は `ImageProcessor.process_file()` で前処理済み（余白除去・長辺 768px・RGB）。

**D18 perspective の代表ペア（D0574419 → D0574421）:**

- 引用対象 B のランク: **4** / 456（Top-10 圏内に引用ペアが出現）
- コサイン類似度: **0.9591**
- LLM 判定: Yes（信頼度 5）

---

## 入力

| データ | パス |
|--------|------|
| ランク検索結果 | `/mnt/eightthdd/uspto/class/{CLASS}/rank_results/{sim_func}/{year}.jsonl` |
| LLM 判定結果 | `/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` |
| ランクインデックス | `/mnt/eightthdd/uspto/class/{CLASS}/rank_index/{type}/` |

---

## 図のスタイル

PRL（Physical Review Letters）シングルカラム準拠:

| 設定 | 値 |
|------|-----|
| フォント | Times New Roman / serif |
| フォントサイズ | 9pt（ラベル 10pt） |
| 列幅 | 3.37 inch |
| DPI | 300 |
| 目盛り方向 | 内向き（全 4 辺） |

---

## 代表ペアの選択ロジック

1. LLM 判定 Yes かつ信頼度 5 のペアを候補とする
2. そのうち順位の中央値に最も近いペアを選ぶ
3. Yes・信頼度 5 が存在しない場合は Yes 全体にフォールバック

---

## 実行方法

```bash
# D18（デフォルト、Qwen なし）
python vector/analysis/rank_analysis.py --class D18

# Qwen LLM でキーワードを動的取得
python vector/analysis/rank_analysis.py --class D18 --use-llm

# 別クラス・画像タイプ指定
python vector/analysis/rank_analysis.py --class D10 --type overview

# ペア比較図の近傍数を変更
python vector/analysis/rank_analysis.py --class D18 --top-k 15
```

実行時の処理順序:

```
[1/3] CCDF プロット          → rank_ccdf_{type}.png
[2/3] Scatter プロット        → rank_scatter_{type}.png
[2b]  Scatter 拡大プロット    → rank_scatter_{type}_zoom.png
[3/3] 高類似度 CSV エクスポート → high_sim_{type}_0950.csv
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--class` | `D18` | 対象クラスコード |
| `--sim` | `cosine_numpy` | 類似度関数 |
| `--type` | `perspective` | 画像タイプ |
| `--top-k` | `10` | ペア比較図の近傍数 |
| `--use-llm` | False | Qwen でキーワード取得を有効化 |

---

## 前後の処理との関係

```
join_judgments.py  →  all.jsonl  →  rank_analysis.py  →  *.png（統計図）
```

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `join_judgments.py`（Step 3） | `rank_analysis.py`（Step 4a） | 論文図の使用 |
| `rank_judgments/{sim_func}/all.jsonl` | → `vector/output/{CLASS}/{sim_func}/*.png` | |

同じ `all.jsonl` を入力とする並列実行可能なスクリプト:
- `export_yes_reasons.py` — Yes ペア CSV（[pipeline.md](pipeline.md) Step 4b）
- `export_non_exact_pairs.py` — Non-exact ペア画像（[export_non_exact_pairs.md](export_non_exact_pairs.md)）
