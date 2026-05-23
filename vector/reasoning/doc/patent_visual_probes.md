# 視覚的プローブ・ベースライン (`patent_visual_probes.py`)

ラショナルテキストではなく**画像そのもの**を入力として使う 2 つのモジュール。

| モジュール | 略称 | 役割 |
|-----------|------|------|
| Visual faithfulness probe | M5 | ラショナルの知覚的主張が画像で支持されるかを検証し UPR を算出 |
| VLM-direct baseline | B | 画像だけで Yes/No を判定（ラショナルなし） |

処理順序の全体像は [pipeline.md](pipeline.md) を参照。

---

## スクリプト

```
vector/reasoning/patent_visual_probes.py
```

---

## 出力ファイル

```
vector/output/{CLASS}/{sim_func}/reasoning/
  m5_scores.csv     — M5 スコア（UPR・m5_score・claim 詳細）
  baseline_b.csv    — Baseline B の Yes/No 判定
```

---

## M5: 視覚的忠実性プローブ

### 概念

VLM ラショナルが画像に基づく正確な観察を反映しているかを 2 ステップで検証する。
「supported / contradicted / unverifiable」の内訳から **Unverified-claim Penalty Rate (UPR)** を算出し、
ラショナルの視覚的忠実性スコア `m5_score = 1 - UPR` を得る。

### 処理ステップ

```
[Step 1] 知覚的主張の抽出（テキストのみ）
  入力: reason テキスト
  出力: ClaimExtractionResult（PerceptualClaim リスト）

[Step 2] 主張の画像検証（マルチモーダル）
  入力: ソース画像 + ターゲット画像 + 主張リスト
  出力: ImageVerificationResult（ClaimVerdict リスト）

[集計] UPR = (contradicted + unverifiable) / n_claims
        m5_score = 1 - UPR
```

### Pydantic スキーマ

**PerceptualClaim**（主張単位）

| フィールド | 型 | 説明 |
|----------|-----|------|
| `claim_text` | str（≥10 文字） | 知覚的主張のテキスト |
| `facet` | str | 対象 Facet（例: GlobalShape）|
| `polarity` | Literal | `similarity` / `difference` |

**ClaimVerdict**（検証結果単位）

| フィールド | 型 | 説明 |
|----------|-----|------|
| `claim_text` | str | 検証対象の主張 |
| `verification_reasoning` | str（≥20 文字） | 画像を見た検証推論 |
| `verdict` | Literal | `supported` / `contradicted` / `unverifiable` |
| `confidence` | float 0–1 | 判定確信度 |

**VisualFaithfulnessScore**（ペア集計出力）

| 列名 | 内容 |
|------|------|
| `source` | クエリ特許番号 |
| `target` | 引用対象特許番号 |
| `n_claims` | 抽出した主張数 |
| `n_supported` | 画像で支持された主張数 |
| `n_contradicted` | 画像で否定された主張数 |
| `n_unverifiable` | 判定不能な主張数 |
| `upr` | Unverified-claim Penalty Rate |
| `m5_score` | 視覚的忠実性スコア（= 1 - UPR）|
| `claims_json` | ClaimExtractionResult の JSON ダンプ |

### 注意事項

- 画像ファイルが存在しない場合は Step 2 を画像なしで実行（`unverifiable` 判定が増加する）
- `n_claims = 0`（主張なし）の場合は `m5_score = 1.0`、`upr = 0.0` を返す
- verdicts の件数と claims の件数が一致しない場合は実際の verdicts から集計する

---

## B: VLM-direct ベースライン

### 概念

ラショナルテキストを一切使わず、**画像ペアのみ**を入力として普通観察者テスト
（Egyptian Goddess v. Swisa, 543 F.3d 665, Fed. Cir. 2008）を適用し Yes/No を判定する。

PMS（ラショナル依存）と Baseline B（画像依存）の乖離を検出することで、
ラショナルの役割を定量評価する（H_NLP4・H_NLP5 で検定）。

### Pydantic スキーマ

**BaselineResult**

| 列名 | 内容 |
|------|------|
| `source` | クエリ特許番号 |
| `target` | 引用対象特許番号 |
| `baseline_reasoning` | 判定推論テキスト（≥30 文字）|
| `baseline_judgment` | `Yes` / `No` |
| `baseline_confidence` | 判定確信度（0–1）|
| `baseline_rationale` | 具体的な視覚的特徴への言及を含む根拠（≥20 文字）|

---

## Gemini API 実装詳細

`patent_rationale_pms.py` の `_limiter` シングルトンを共有し、
M5 / B のリクエストを同一レート制限ウィンドウで管理する。

| 機能 | 実装 |
|------|------|
| レート制限 | `_limiter.acquire_slot()` → `_limiter.update_tokens()` を各 `_call()` 内で実行 |
| thinking_budget | `_THINKING_BUDGET_MAP[cfg.thinking_level]`（patent_rationale_pms から import）|
| response_schema | `response_schema=PydanticModel`（`TypeError` fallback あり）|
| 待機 | `time.sleep(remaining if remaining > 0 else 2)` |
| 非同期 | `loop.run_in_executor(None, _call)` |
| 画像 | `base64.b64encode(image_bytes)` → `genai_types.Part.from_bytes()` |

---

## 固定パス

| 種別 | パス |
|------|------|
| 入力 CSV | `vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv` |
| M5 出力 | `vector/output/D18/cosine_numpy/reasoning/m5_scores.csv` |
| Baseline B 出力 | `vector/output/D18/cosine_numpy/reasoning/baseline_b.csv` |

## 実行方法

```bash
cd vector/reasoning

# M5 + Baseline B 両方（デフォルト）
python3 patent_visual_probes.py

# M5 のみ
python3 patent_visual_probes.py --module m5

# Baseline B のみ
python3 patent_visual_probes.py --module baseline

# パイロット行のみ（extract_pilot.py を先に実行しておく必要あり）
python3 patent_visual_probes.py --pilot-only
```

入力・出力パスはスクリプト内に固定。処理済みペアは自動スキップ（resume 対応）。

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--module` | `both` | `m5` / `baseline` / `both` |
| `--model` | `gemini-flash` | モデルエイリアス |
| `--concurrency` | `3` | 並列リクエスト数 |
| `--pilot-only` | False | `_stratum` 列が存在する行のみ処理 |

---

## 前後の処理との関係

```
high_sim_perspective_0950_judged.csv  →  patent_visual_probes.py
                                              ↓               ↓
                                        m5_scores.csv   baseline_b.csv
                                              ↓               ↓
                                           merge_results.py（Step 5）
```

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `extract_pilot.py`（Step 0）| `patent_visual_probes.py`（Step 2/3）| `merge_results.py`（Step 5）|

`patent_rationale_pms.py`（Step 1）とは独立して並列実行可能。