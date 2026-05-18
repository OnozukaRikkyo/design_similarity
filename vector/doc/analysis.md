# vector/analysis/ — 分析・可視化スクリプト群

## 概要

`join_judgments.py`（Step 5）が生成した `rank_judgments/{sim_func}/all.jsonl` を入力として、
統計分析・可視化・データエクスポートを行うスクリプト群。

---

## スクリプト一覧

| スクリプト | 役割 |
|---|---|
| `rank_analysis.py` | CCDF・散布図・ペア比較画像を生成 |
| `export_yes_reasons.py` | Yes 判定ペアを CSV にエクスポート |
| `export_non_exact_pairs.py` | 完全一致でない Yes ペアの画像を出力 |

---

## 共通入力

**3 スクリプトすべて同じ入力源:**

```
class/{CLASS}/rank_judgments/{sim_func}/all.jsonl
```

このファイルの `judgment` フィールド（`"Yes"` / `"No"` / `"Unknown"`）を
Similar / Non-similar として使用する。

### judgment フィールドの出所

```
画像ファイル（.TIF）× 2枚
    ↓ Qwen3-VL-4B-Instruct（法的類似性プロンプト）
    ↓ judge_cited_pairs.py
qwen_similarity_results/{year}.jsonl
    ↓ join_judgments.py（Step 5）
rank_judgments/cosine_numpy/all.jsonl  ← ここを読む
```

判定は**画像の視覚内容のみ**に基づく。特許メタデータは使用しない。

### yes_pair/qwen/ との関係

`/mnt/eightthdd/uspto/yes_pair/qwen/` は**使用しない**。

`yes_pair/qwen/`（exact_match / high_similar / similar）は別系統のスクリプトが使用する:

| スクリプト | 入力 |
|---|---|
| `make_two_heatmaps.py` | `yes_pair/qwen/exact_match/`, `high_similar/`, `similar/` |
| `visualize_ergm_network.py` | `yes_pair/qwen/` 以下を再帰的に読み込み |

`vector/analysis/` はこれらとは独立したパイプラインである。

---

## 実行順序

3 スクリプトは互いに独立しており、どの順でも実行できる。
以下は目的に沿った自然な順序:

```bash
cd /home/sonozuka/design_similarity

# 1. 全体把握（CCDF・散布図・ペア比較画像）
python vector/analysis/rank_analysis.py --class D18

# 2. Yes ペアの一覧確認（CSV）
python vector/analysis/export_yes_reasons.py --class D18

# 3. 完全一致でない Yes ペアの詳細確認（画像）
python vector/analysis/export_non_exact_pairs.py --class D18
```

**いずれも resume なし（常に上書き）。** `all.jsonl` を更新した後はそのまま再実行すればよい。

---

## rank_analysis.py

### 出力

```
vector/output/{CLASS}/{sim_func}/
  rank_ccdf_{type}.png          — Figure 1: 順位の CCDF（log-log、Yes/No 別）
  rank_scatter_{type}.png       — Figure 2: 順位 vs コサイン類似度の散布図
  rank_scatter_{type}_zoom.png  — Figure 2b: 散布図拡大（rank ≤ 20, similarity ≥ 0.85）

class/{CLASS}/rank_analysis/{sim_func}/{type}/pair_comparison/
  {src}--{tgt}_rank{r:03d}.png  — Figure 3: Yes かつ rank ≤ topk の全ペア比較画像
```

### Similar / Non-similar の情報源

散布図の Similar（青・菱形）/ Non-similar（赤・×）は `all.jsonl` の `judgment` フィールド。

```python
# rank_analysis.py 内
recs = [r for r in records if r["judgment"] == "Yes"]   # Similar
recs = [r for r in records if r["judgment"] == "No"]    # Non-similar
```

### 主なオプション

```bash
python vector/analysis/rank_analysis.py --class D18
python vector/analysis/rank_analysis.py --class D18 --top-k 10   # Figure 3 の対象順位
python vector/analysis/rank_analysis.py --class D18 --type front # 画像タイプ指定
```

---

## export_yes_reasons.py

### 出力

```
vector/output/{CLASS}/{sim_func}/yes_sim{threshold}_reasons.csv
```

Yes 判定かつ指定類似度以上のペアを全フィールド付きで CSV に出力する。

### 主なオプション

```bash
python vector/analysis/export_yes_reasons.py --class D18
python vector/analysis/export_yes_reasons.py --class D18 --min-sim 0.9
```

---

## export_non_exact_pairs.py

### 出力

```
class/{CLASS}/rank_analysis/{sim_func}/{type}/non_exact_pairs/
  {src}--{tgt}_rank{r:03d}.png
```

Yes 判定かつ類似度閾値以上のペアのうち、reason に「完全一致」を示すキーワードを含まないペアの画像を出力する。
完全一致キーワードの判定は Qwen3-VL-4B-Instruct に問い合わせる（失敗時は identical / exact / same にフォールバック）。

### 主なオプション

```bash
python vector/analysis/export_non_exact_pairs.py --class D18
python vector/analysis/export_non_exact_pairs.py --class D18 --min-sim 0.9
```

---

## データ更新後の再実行

`qwen_similarity_results/` が更新された場合は先に `all.jsonl` を再生成してから実行する。

```bash
# Step 5 で all.jsonl を更新
python vector/run_pipeline.py --class D18 --steps 5 --no-resume

# 分析を再実行
python vector/analysis/rank_analysis.py --class D18
python vector/analysis/export_yes_reasons.py --class D18
python vector/analysis/export_non_exact_pairs.py --class D18
```

詳細: [join_judgments.md](join_judgments.md)

---

## D18 の現状（2026-05-19 確認）

| 項目 | 値 |
|---|---|
| 対象クラス | D18 のみ（他クラスは未作成） |
| 対象年 | 2007〜2022（16 年分） |
| all.jsonl 総件数 | 634 件 |
| Yes（Similar） | 131 件 |
| No（Non-similar） | 486 件 |
| Unknown | 17 件 |

Unknown は `qwen_similarity_results/` に対応するペアが存在しない年（2016〜2022）のレコード。
`judge_cited_pairs.py` の処理が進むにつれ Yes/No に変わる。

---

## 関連ドキュメント

- [pipeline.md](pipeline.md) — パイプライン全体
- [join_judgments.md](join_judgments.md) — Step 5: all.jsonl の生成と更新手順