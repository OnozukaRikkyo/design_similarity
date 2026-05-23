# PMS パイプライン・コアモジュール (`patent_rationale_pms.py`)

VLM ラショナルテキストから Perfect-Match Score (PMS) を算出する中心モジュール。
M1（側面グラフ抽出）・M2（NLI 採点）・M3（言い換え一貫性）・M4（クロス LLM アンサンブル）
の 4 モジュールを組み合わせ、視覚的同等性の推定値を 0–1 のスカラーで出力する。

処理順序の全体像は [pipeline.md](pipeline.md) を参照。

---

## スクリプト

```
vector/reasoning/patent_rationale_pms.py
```

---

## 出力ファイル

```
vector/output/{CLASS}/{sim_func}/reasoning/
  pms_results.csv          — PMS スコア + M1/M2/M3 詳細列
```

---

## 設計原則と文献

| 設計 | 出典 |
|------|------|
| Reasoning-first Pydantic フィールド順序 | Castillo 2024; techsy.io 2026 |
| 2-step structured output（DICE） | Pan et al. 2025; Shorten et al. arXiv 2604.03616 |
| Self-Harmony 言い換え一貫性 | ICLR 2026, arXiv 2511.01191 |
| 位置バイアス (A,B)/(B,A) スワップ | Shi et al. IJCNLP 2025 |
| クロス LLM Krippendorff α | Rating Roulette EMNLP 2025; Guerdan et al. 2025 |
| WIPO 本体論 | PatentScore (Yoo et al. EMNLP 2025) |
| 普通観察者テスト | Egyptian Goddess v. Swisa, 543 F.3d 665 (Fed. Cir. 2008) |

---

## Facet 本体論

8 + 1 カテゴリ（WIPO 準拠）:

| Facet | 説明 |
|-------|------|
| `GlobalShape` | 全体シルエット・外形 |
| `Proportions` | 縦横比・寸法バランス |
| `PartLayout` | 部品の配置・相対位置 |
| `LocalJunction` | 接続部・角部・局所形状 |
| `LineStyle` | 線種（実線・破線・点線）|
| `Texture` | 表面テクスチャ・ハッチング |
| `Ornamentation` | 装飾・模様・ロゴ |
| `Orientation` | 向き・鏡像・回転 |
| `Uncategorized` | 上記に属さないその他 |

---

## Pydantic スキーマ

### FacetEvaluation（M1 単位出力）

フィールドは推論優先順序（Reasoning-first）で定義されている:
LLM が `facet_reasoning` を先に生成することで、`state` の決定前に分析が完結する。

| フィールド | 型 | 説明 |
|----------|-----|------|
| `facet_reasoning` | str（≥20 文字） | ラショナルのこの Facet に関する逐次分析 |
| `facet` | Facet | 対象 Facet |
| `state` | FacetState | `Identical` / `Minor_Difference` / `Significant_Difference` / `Not_Discussed` |
| `evidence_span` | str | ラショナルから抜き出した根拠テキスト（state ≠ NOT_DISCUSSED のとき必須） |
| `confidence` | float 0–1 | この state への確信度 |

### RationaleGraph（M1 全体出力）

| フィールド | 型 | 説明 |
|----------|-----|------|
| `overall_reasoning` | str（≥50 文字） | Facet 抽出前の全体分析 |
| `consistency_flag` | Literal | `consistent` / `internally_contradictory` / `ambiguous` |
| `aspects` | list[FacetEvaluation] | 言及された Facet のみ（NOT_DISCUSSED のプレースホルダは不要）|

### PerfectMatchScore（M2 出力）

| フィールド | 型 | 説明 |
|----------|-----|------|
| `nli_reasoning` | str（≥40 文字） | premise→hypothesis の NLI 推論 |
| `nli_label` | Literal | 5 クラス: `strong_entailment` / `weak_entailment` / `neutral` / `weak_contradiction` / `strong_contradiction` |
| `match_probability` | float 0–1 | 完全一致確率（キャリブレーション目安は下表） |

**match_probability キャリブレーション目安:**

| nli_label | match_probability 範囲 |
|-----------|----------------------|
| strong_entailment | ≥ 0.85 |
| weak_entailment | 0.55–0.85 |
| neutral | 0.40–0.55 |
| weak_contradiction | 0.15–0.40 |
| strong_contradiction | ≤ 0.15 |

---

## モジュール詳細

### M1: 側面グラフ抽出

ラショナルテキストを入力とし、言及された各 Facet の equivalence 状態を構造化して抽出する。

- **プロンプト戦略**: LLM はラショナルの著者ではなくパーサーとして振る舞う
  （「新たな意見を生成するのではなく、既存のラショナルを構造化グラフに変換する」）
- **important な修飾語の扱い**:
  - "despite identical X" → X は Identical だが全体として矛盾
  - "mirror image" → ORIENTATION = Significant_Difference
  - "rotated" → ORIENTATION = Minor_Difference（自明な回転でなければ）
  - "appears" / "seems" / "likely" → confidence を下げる

### M2: NLI 採点

ラショナルを**前提 (premise)**、「2 枚の画像は視覚的に同一の線図を描写している」
を**仮説 (hypothesis)** とした 5 クラス NLI 採点。

**2-step fallback（`--twostep` 時）:**

```
Step 1: 自由記述分析（200–400 語）— JSON 不要、思考を展開
Step 2: Step 1 の分析を PerfectMatchScore JSON に変換
```

「The Format Tax」（Shorten et al. 2026）を回避するため、難事例に使用する。

**位置バイアスチェック（`--position-check` 時）:**

A/B を B/A にスワップしたラショナルでも採点し、両者の NLI ラベルと確率が
一致するかを検証する（一致しない場合 `position_inconsistent` フラグを付与）。

### M3: 言い換え一貫性（Self-Harmony）

Self-Harmony（ICLR 2026, arXiv 2511.01191）の手法: ラショナルを k=5 回言い換えて
M2 で採点し、スコアの分散を**ラベル不確実性信号**として使う。

```
mean_p  = mean(M2 scores over k paraphrases + original)
std     = stdev(M2 scores)
ci_low, ci_high = 95% bootstrap CI (1000 回)
```

`std` が高い（> 0.20）場合は `M3_high_variance` フラグを付与する。

### M4: クロス LLM アンサンブル（オプション）

複数の LLM クライアント（`judges` リスト）に M1–M3 を並列実行し、
Krippendorff α で NLI ラベルの評価者間信頼性を算出する。

```python
aggregated_pms = median(per-judge PMS values)
krippendorff_alpha_nli = krippendorff.alpha(nli_labels, level="nominal")
```

---

## PMS 集計式

```
PMS = clip( mean_p × (1 - std_penalty) × (1 - consistency_penalty), 0, 1 )

confidence = max(0, 1 - std_penalty - consistency_penalty)
```

| 項 | 計算式 | 説明 |
|----|--------|------|
| `mean_p` | M3 の mean（M3 失敗時 M2 の match_probability） | 基準スコア |
| `std_penalty` | `min(1, M3 std × 2)` | 言い換え分散ペナルティ |
| `consistency_penalty` | 0.4（internally_contradictory）/ 0.2（ambiguous）/ 0.0（consistent） | M1 整合性ペナルティ |

**フラグ一覧:**

| フラグ | 付与条件 |
|--------|---------|
| `M3_unavailable` | M3 std が NaN |
| `M3_high_variance` | M3 std > 0.20 |
| `M1_internally_contradictory` | M1 consistency_flag = "internally_contradictory" |
| `M1_ambiguous` | M1 consistency_flag = "ambiguous" |
| `position_inconsistent` | A/B スワップで NLI ラベルまたは確率が乖離 |
| `processing_failed` | 例外により処理失敗 |

---

## 出力列（pms_results.csv）

| 列名 | 内容 |
|------|------|
| `source` | クエリ特許番号 |
| `target` | 引用対象特許番号 |
| `pms` | Perfect-Match Score |
| `pms_confidence` | PMS 信頼度（ペナルティの残余）|
| `m2_match_prob` | M2 match_probability |
| `m2_nli_label` | M2 NLI ラベル |
| `m1_consistency_flag` | M1 整合性フラグ |
| `m3_paraphrase_mean` | M3 スコア平均 |
| `m3_paraphrase_std` | M3 スコア標準偏差 |
| `cot_m1_reasoning` | M1 全体推論テキスト |
| `cot_m2_nli_reasoning` | M2 NLI 推論テキスト |
| `flags` | カンマ区切りフラグ |

---

## Gemini API 実装詳細

`design_similarity.py` のパターンに準拠:

| 機能 | 実装 |
|------|------|
| レート制限 | `RateLimiter`（RPM/TPM/RPD スライディングウィンドウ、スレッドセーフ） |
| thinking_level → budget | `_THINKING_BUDGET_MAP`（minimal=512, low=1024, medium=2048, high=8192） |
| 構造化出力 | `response_schema=PydanticModel`（非対応版への `TypeError` fallback あり） |
| 待機 | API 呼び出し後 `MIN_INTERVAL_SEC = 1.0` 秒以上待機 |
| 非同期 | `asyncio.get_running_loop().run_in_executor(None, _call)` |
| エラーログ | `vector/reasoning/log/error/YYYY-MM-DD.log` |

---

## 固定パス

| 種別 | パス |
|------|------|
| 入力 CSV | `vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv` |
| 出力 CSV | `vector/output/D18/cosine_numpy/reasoning/pms_results.csv` |
| 出力 JSONL | `vector/output/D18/cosine_numpy/reasoning/pms_results.pms.jsonl` |

## 実行方法

```bash
cd vector/reasoning

# デフォルト（gemini-flash、concurrency=4）
python3 patent_rationale_pms.py

# 難事例に 2-step M2 を使用
python3 patent_rationale_pms.py --twostep

# 位置バイアスチェックを有効化
python3 patent_rationale_pms.py --position-check

# テスト用に先頭 5 件のみ処理
python3 patent_rationale_pms.py --sample-n 5
```

入力・出力パスはスクリプト内に固定。処理済みペアは自動スキップ（resume 対応）。

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--judge` | `gemini-flash` | モデルエイリアス |
| `--concurrency` | `4` | 並列リクエスト数 |
| `--paraphrase-k` | `5` | M3 言い換え数 |
| `--twostep` | False | M2 を 2-step で実行 |
| `--position-check` | False | 位置バイアスチェックを有効化 |
| `--sample-n` | None | 先頭 N 件のみ処理（テスト用）|

---

## 前後の処理との関係

```
high_sim_perspective_0950_judged.csv  →  patent_rationale_pms.py  →  pms_results.csv
                                                                         ↓
                                                                    merge_results.py
```

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `rank_analysis.py`（Step 4a） | `patent_rationale_pms.py`（Step 1） | `merge_results.py`（Step 5） |