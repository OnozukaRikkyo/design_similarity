# join_judgments.py — Step 5: ランク結果と LLM 判定の結合

## 概要

ベクトルランク検索の結果（`rank_results/`）と LLM 類似判定（`qwen_similarity_results/`）を
結合して、分析用の全件 JSONL を生成する。

---

## 入出力

### 入力（3 つ）

| ディレクトリ | 内容 | 生成元 |
|---|---|---|
| `class/{CLASS}/rank_results/{sym_func}/{year}.jsonl` | ベクトルランク検索結果 | Step 4: `compute_ranks.py` |
| `qwen_similarity_results/{year}.jsonl` | LLM 類似判定（Yes/No） | `judge_cited_pairs.py`（外部） |
| `class/{CLASS}/cited_image_pairs/{year}.jsonl` | 画像パス取得用 | Step 1: `filter_pairs_by_class.py` |

### 出力

```
class/{CLASS}/rank_judgments/{sim_func}/all.jsonl
```

1 行 = 1 (ペア × 画像タイプ) レコード。全年・全タイプを結合。

追加フィールド:

| フィールド | 内容 |
|---|---|
| `judgment` | `"Yes"` / `"No"` / `"Unknown"` |
| `confidence` | 1〜5（LLM 確信度。Unknown 時は 0） |
| `reason` | 判定根拠テキスト |
| `source_image` | source の当該タイプ画像パス |
| `target_image` | target の当該タイプ画像パス |

---

## judgment フィールドの仕組み

`qwen_similarity_results/{year}.jsonl` に該当ペアのレコードがあれば `judgment` に Yes/No を付与する。
存在しない場合は `"Unknown"` になる。

```
cited_image_pairs/{year}.jsonl  （全クラス対象・全ペアの画像パスを含む）
    ↓ judge_cited_pairs.py  ← run_pipeline.py には含まれない外部スクリプト
      画像 2 枚を Qwen3-VL-4B-Instruct で比較
      法的類似性プロンプト（US/EU 意匠法・観察者テスト）
      → メタデータは一切使わない。判定は画像の視覚内容のみに基づく
    ↓
qwen_similarity_results/{year}.jsonl  → join_judgments.py が参照
```

**重要:** `class/{CLASS}/cited_image_pairs/{year}.jsonl` には Yes/No 情報は含まれない。
フィールドは `source`・`target`・`source_images`・`target_images`・`events`・`source_class`・`target_class` のみ。
Yes/No 判定は `judge_cited_pairs.py` による画像比較によって初めて付与される。

`judge_cited_pairs.py` は全クラス混在の `cited_image_pairs/` を処理するため、
D18 以外のペアも含む大量の判定を実行する（1 年あたり数千〜1 万件以上）。

---

## データの対象年

`join_judgments.py` は `rank_results/` に存在する全年を対象とする。
D18 の場合、`rank_results/` と `cited_image_pairs/` はともに 2007〜2022 の 16 年分が存在する。

`qwen_similarity_results/` の整備状況により `judgment` の付与状況が変わる:

| 年 | rank_results | qwen_similarity_results | judgment |
|----|:---:|:---:|:---:|
| 2007〜2016 | あり | あり（完了） | Yes / No |
| 2017 | あり | 処理中（途中） | 一部 Yes/No、残りは Unknown |
| 2018〜2022 | あり | 未処理（0件） | Unknown |

> **確認日: 2026-05-20**  
> `judge_cited_pairs.py` が処理を進めるたびに `qwen_similarity_results/` が更新されるため、
> 下記「更新手順」を実行するたびに最新の判定が `all.jsonl` に反映される。

---

## 実行方法

```bash
cd /home/sonozuka/design_similarity

# 通常（resume 有効: all.jsonl が既存ならスキップ）
python vector/join_judgments.py --class D18

# 強制上書き（qwen_similarity_results/ が更新されたとき）
python vector/join_judgments.py --class D18 --no-resume

# run_pipeline.py 経由（Step 5 のみ、強制上書き）
python vector/run_pipeline.py --class D18 --steps 5 --no-resume
```

---

## LLM 判定が追加されたときの更新手順

`judge_cited_pairs.py` が実行中または完了後、任意のタイミングで以下を実行する。
途中段階のデータ（一部の年のみ判定済み）でも安全に実行できる。

### Step 1: qwen_similarity_results/ の現状を確認

```bash
for f in /mnt/eightthdd/uspto/qwen_similarity_results/*.jsonl; do
    echo "$(basename $f): $(wc -l < $f)件"
done
```

0 件の年は `judgment=Unknown` になる。判定済み年のみ有効な Yes/No が付与される。

### Step 2: all.jsonl を再生成（Step 5 を --no-resume で実行）

```bash
cd /home/sonozuka/design_similarity
python vector/run_pipeline.py --class D18 --steps 5 --no-resume
```

または直接:

```bash
python vector/join_judgments.py --class D18 --no-resume
```

> **ここまでで `all.jsonl`（データ出力）は完成。**  
> Step 1〜4（ペア抽出・ベクトル生成・インデックス・ランク検索）は
> `qwen_similarity_results/` と無関係なので実行不要。

#### Step 5 が行うこと（ステップバイステップ）

1. `--no-resume` → 既存の `all.jsonl` があっても上書きする
2. `rank_results/cosine_numpy/` にある全年の `.jsonl` を年順に列挙
3. `qwen_similarity_results/{year}.jsonl` を全年メモリに読み込み `(source, target) → {judgment, confidence, reason}` の辞書を構築
4. `class/D18/cited_image_pairs/{year}.jsonl` を全年メモリに読み込み `(source, target) → {source_images, target_images}` の辞書を構築
5. ランク結果の各行に judgment / confidence / reason / source_image / target_image を付与して `all.jsonl` に書き出す

> **注意:** `qwen_similarity_results/` に 0 件の年は `judgment=Unknown`、`confidence=0`、`reason=""` になる。壊れるわけではない。

### Step 3: 図の生成（任意・データ出力には不要）

`all.jsonl` を使って CCDF・散布図・ペア比較画像などを生成する場合のみ実行する。

```bash
python vector/analysis/rank_analysis.py --class D18
python vector/analysis/export_yes_reasons.py --class D18
python vector/analysis/export_non_exact_pairs.py --class D18
```

`vector/analysis/` の各スクリプトは resume なし（常に上書き）のため、そのまま実行すればよい。

---

## 判定状況の確認方法

```bash
python3 -c "
import json
from collections import Counter
from pathlib import Path

fp = Path('/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl')
judgments = [json.loads(l)['judgment'] for l in fp.read_text().splitlines() if l.strip()]
print(Counter(judgments))
print('合計:', len(judgments))
"
```

---

## 関連ドキュメント

- [pipeline.md](pipeline.md) — パイプライン全体
- [analysis.md](analysis.md) — vector/analysis/ スクリプト群
- [compute_ranks.md](compute_ranks.md) — Step 4: ベクトルランク検索