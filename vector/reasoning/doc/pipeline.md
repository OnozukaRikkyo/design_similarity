# PMS パイプライン処理順序

`vector/reasoning/` ディレクトリに実装された Perfect-Match Score (PMS) パイプラインの処理フロー。
ラショナルテキスト（VLM が生成した判定根拠文）から視覚的同等性を推定する。

**入力**: `rank_analysis.py`（Step 4a）が出力した `high_sim_perspective_0950_judged.csv`  
**前提**: 入力 CSV の `reason` 列に LLM の判定根拠テキストが含まれていること。

---

## 全体フロー

```
[Step 0] extract_pilot.py
         ↓ pilot_24.csv（23 行、6 層）
         ↓ pilot_strata.csv（監査テーブル）

[Step 1] patent_rationale_pms.py   ← M1/M2/M3/M4 + PMS 集計
         ↓ pms_results.csv

[Step 2] patent_visual_probes.py   ← M5: 視覚的忠実性プローブ
         ↓ m5_scores.csv

[Step 3] patent_visual_probes.py   ← B: VLM-direct ベースライン（画像のみ）
         ↓ baseline_b.csv

[Step 4] prepare_human_annotation.py
         ↓ annotation_package/
              annotation_tasks.csv
              annotation_images/

[Step 5] merge_results.py
         ↓ unified_results.csv

[Step 6] analyze_results.py
         ↓ analysis_summary.txt
         ↓ fig_*.png（5 枚）
```

Step 1–3 は PMS / M5 / B を独立して実行するため、完了後に merge すればよい。  
Step 2・3 は同一スクリプト `patent_visual_probes.py` の `--module` 引数で切り替える。

---

## 各ステップの詳細

### Step 0: パイロットサンプリング（`extract_pilot.py`）

220 行の入力 CSV から 6 層・計 23 行をサンプリングし、LLM API コストを抑えながら
代表的なケースをカバーする。

**層定義:**

| 層 | 件数 | 条件 |
|----|------|------|
| L1 | 2 | conf=5 & No & reason に "identical" 等を含む（自己矛盾） |
| L2 | 4 | similarity ≥ 0.99 & No（高類似度パラドックス） |
| L3 | 5 | similarity ≥ 0.99 & Yes（高類似度マッチ） |
| L4 | 5 | similarity 最小 & Yes（低類似度マッチ） |
| L5 | 5 | similarity ∈ [0.965, 0.975]（キャリブレーション境界） |
| L6 | 2 | networkx 最大連結成分のエッジ（デザインファミリー） |

→ 詳細は [extract_pilot.md](extract_pilot.md) 参照。

---

### Step 1: PMS（`patent_rationale_pms.py`）

`reason` テキストに M1/M2/M3 を順次適用し、PMS スコアを算出する。

| モジュール | 役割 |
|-----------|------|
| M1 | 側面グラフ抽出（WIPO 本体論、RationaleGraph） |
| M2 | NLI 5 クラス採点（PerfectMatchScore、match_probability） |
| M3 | 言い換え一貫性（Self-Harmony k=5、std を不確実性信号に） |
| M4 | 複数 LLM アンサンブル（オプション） |

→ 詳細は [patent_rationale_pms.md](patent_rationale_pms.md) 参照。

---

### Step 2/3: 視覚的プローブ・ベースライン（`patent_visual_probes.py`）

画像を直接モデルに渡して検証する 2 つのモジュール。

| モジュール | 役割 |
|-----------|------|
| M5 | 視覚的忠実性プローブ（ラショナルの知覚的主張を画像で検証し UPR を算出） |
| B  | VLM-direct ベースライン（ラショナルなし、画像のみで Yes/No 判定） |

→ 詳細は [patent_visual_probes.md](patent_visual_probes.md) 参照。

---

### Step 4: 人手アノテーション準備（`prepare_human_annotation.py`）

パイロット 23 件の画像とタスクシートをパッケージ化する。
LLM 出力と人手評価の一致率は `analyze_results.py`（H_NLP4）で検定する。

---

### Step 5: 結合（`merge_results.py`）

全モジュール出力を `(source, target)` キーで left-join し `unified_results.csv` を生成する。

**結合対象列:**

| 由来 | 代表列 |
|------|--------|
| 入力 CSV | source, target, similarity, judgment, confidence, reason, source_image, target_image |
| M1 | m1_consistency_flag |
| M2 | m2_match_prob, m2_nli_label |
| M3 | m3_paraphrase_mean, m3_paraphrase_std |
| PMS | pms, pms_confidence, flags |
| M5 | m5_score, upr, n_claims, n_supported, n_contradicted |
| B | b_baseline_judgment, b_baseline_confidence |
| Pilot | _stratum |
| Human | human_judgment, human_confidence, human_comment |

---

### Step 6: 統計分析・図生成（`analyze_results.py`）

`unified_results.csv` を読み込み、5 つの事前登録仮説を検定し 5 枚の図を生成する。

**仮説一覧:**

| 仮説 | 内容 | 検定手法 |
|------|------|----------|
| H_NLP1 | PMS と cos 類似度に正の相関 | Spearman ρ |
| H_NLP2 | Exact match の PMS > Non-exact | 片側 t 検定 |
| H_NLP3 | M5 score と PMS に正の相関 | Spearman ρ |
| H_NLP4 | Baseline B の一致率 > 0.7 | 片側 z 検定 |
| H_NLP5 | PMS の AUC > cos 類似度の AUC | Steiger の Z |

→ 詳細は [analyze_results.md](analyze_results.md) 参照。

---

## 実行方法

### フルパイプライン（`run_pipeline.sh`）

```bash
export GOOGLE_API_KEY=your_key
bash vector/reasoning/run_pipeline.sh
```

パスはすべてスクリプト内に固定されており、引数不要。

| 固定値 | 値 |
|--------|-----|
| 入力 CSV | `vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv` |
| 出力先 | `vector/output/D18/cosine_numpy/reasoning/` |
| デフォルトモデル | `gemini-flash` |
| デフォルト並列数 | `3` |

シェル変数で上書き可能（モデル・並列数のみ）:

```bash
MODEL=gemini-pro CONCURRENCY=2 bash vector/reasoning/run_pipeline.sh
```

### 個別ステップ

すべてのスクリプトは入力・出力パスが固定されており、引数不要で実行できる。

```bash
cd vector/reasoning

# Step 0: パイロットサンプリング
python3 extract_pilot.py

# Step 1: PMS（M1/M2/M3）
python3 patent_rationale_pms.py

# Step 2: M5（Step 1 と独立して並列実行可）
python3 patent_visual_probes.py --module m5

# Step 3: Baseline B（Step 1/2 と独立して並列実行可）
python3 patent_visual_probes.py --module baseline

# Step 4: 人手アノテーションパッケージ（Step 0 完了後）
python3 prepare_human_annotation.py

# Step 5: 結合（Step 1〜3 完了後）
python3 merge_results.py

# Step 6: 分析（Step 5 完了後）
python3 analyze_results.py
```

### スキーマ確認（API なし）

```bash
cd vector/reasoning
python3 demo_offline.py
```

---

## データの所在

| データ | パス |
|--------|------|
| 入力 CSV | `vector/output/{CLASS}/{sim_func}/high_sim_perspective_0950_judged.csv` |
| パイロット CSV | `vector/output/{CLASS}/{sim_func}/reasoning/pilot_24.csv` |
| PMS 結果 | `vector/output/{CLASS}/{sim_func}/reasoning/pms_results.csv` |
| M5 スコア | `vector/output/{CLASS}/{sim_func}/reasoning/m5_scores.csv` |
| Baseline B | `vector/output/{CLASS}/{sim_func}/reasoning/baseline_b.csv` |
| 統合結果 | `vector/output/{CLASS}/{sim_func}/reasoning/unified_results.csv` |
| 人手アノテーション | `vector/output/{CLASS}/{sim_func}/reasoning/annotation_package/` |
| 統計図 | `vector/output/{CLASS}/{sim_func}/reasoning/analysis/fig_*.png` |
| エラーログ | `vector/reasoning/log/error/YYYY-MM-DD.log` |

---

## 前後の処理との関係

```
rank_analysis.py (Step 4a)
  → high_sim_perspective_0950_judged.csv
      → [PMS パイプライン（本ディレクトリ）]
          → unified_results.csv → 論文図・仮説検定
```

| 前工程 | 本パイプライン | 後工程 |
|--------|--------------|--------|
| `join_judgments.py` + `rank_analysis.py` | `vector/reasoning/` | 論文統計・図 |