# Non-exact ペア画像出力 (`export_non_exact_pairs.py`)

`judgment=Yes` のペアのうち、`reason` テキストに完全一致を示すキーワードが含まれないもの（**Non-exact similar**）を画像ファイルとして出力する。

**前提**: Step 3 の `join_judgments.py` が完了し `all.jsonl` が存在すること。
処理順序の全体像は [pipeline.md](pipeline.md) を参照。

---

## スクリプト

```
vector/analysis/export_non_exact_pairs.py
```

---

## 実行方法

```bash
# デフォルト（Qwen なし、フォールバックキーワード使用）
python vector/analysis/export_non_exact_pairs.py --class D18

# 類似度下限を変更
python vector/analysis/export_non_exact_pairs.py --class D18 --min-sim 0.9

# Qwen LLM でキーワードを動的取得
python vector/analysis/export_non_exact_pairs.py --class D18 --use-llm
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--class` | `D18` | 対象クラスコード |
| `--sim` | `cosine_numpy` | 類似度関数 |
| `--type` | `perspective` | 画像タイプ |
| `--min-sim` | `0.8` | コサイン類似度の下限 |
| `--use-llm` | False | Qwen でキーワード取得を有効化（デフォルト: 無効）|

---

## 処理ステップ

```
[1] all.jsonl 読み込み
    → judgment=Yes かつ similarity >= min_sim のレコードを抽出

[2] キーワード取得
    └─ --use-llm なし（デフォルト）: FALLBACK_EXACT_KEYWORDS を使用
    └─ --use-llm あり            : Qwen3-VL-4B-Instruct に reason 一覧を渡す

[3] フィルタリング
    → exact_pattern（正規表現）で reason をスキャン
    → パターン不一致 → Yes_nonexact（出力対象）
    → パターン一致   → Yes_exact  （除外）

[4] 画像出力
    → ソース / ターゲット 2 枚 + reason テキストを 1 PNG に合成
```

---

## Exact / Non-exact の分類ロジック

### フォールバックキーワード（デフォルト）

```python
FALLBACK_EXACT_KEYWORDS = ["identical", "exact", "same"]
```

`reason` テキストにこれらが単語境界（`\b`）でマッチすれば **Exact match**（除外）、しなければ **Non-exact similar**（出力対象）。

### LLM キーワード取得（`--use-llm`）

Qwen3-VL-4B-Instruct（テキストのみ）に全 Yes レコードの `reason` を渡し、以下の JSON を返させる:

```json
{
  "exact_keywords": ["identical", "exact", ...],
  "non_exact_keywords": ["similar", "minor difference", ...]
}
```

- LLM の応答パース失敗時はフォールバックキーワードへ自動退避
- モデルはシングルトンとしてキャッシュ（同一プロセス内で再ロードしない）
- 初回ロード時の VRAM 消費量をコンソールに表示

---

## 入力

```
class/{CLASS}/rank_judgments/{sim_func}/all.jsonl
```

`join_judgments.py`（Step 3）が生成するファイル。

---

## 出力

```
/mnt/eightthdd/uspto/class/{CLASS}/rank_analysis/{sim_func}/{type}/non_exact_pairs/
  {src}--{tgt}_rank{r:03d}.png
```

> **ディレクトリは実行前に自動クリアされる。**  
> `qwen_similarity_results/` が更新されて rank 番号が変わっても旧ファイルは残らない。

### 1 PNG のレイアウト（2行 × 5列）

| 位置 | 内容 |
|------|------|
| Row 0, Col 0–1 | Query（ソース）画像 |
| Row 0, Col 2–3 | Expected（ターゲット）画像、ランク・類似度・LLM 判定付き |
| Row 0, Col 4 | 統計情報テキスト（rank / similarity / confidence / type）|
| Row 1, Col 0–4 | reason テキスト（全幅、斜体） |

---

## rank_analysis.py との関係

`rank_analysis.py` は同じ分類ロジック（`build_exact_pattern` + `classify_records`）をスキャッタープロット生成時にインラインで実行する。

| | `export_non_exact_pairs.py` | `rank_analysis.py` |
|--|--|--|
| 目的 | Non-exact ペアの画像を出力 | 統計図（CCDF・散布図）を生成 |
| 分類結果の用途 | 出力対象のフィルタリング | スキャッタープロットの色分け |
| `--use-llm` | 対応 | 対応（`ask_llm_for_keywords` をインポート）|
| デフォルト動作 | フォールバックキーワード | フォールバックキーワード |

→ 散布図の exact/non-exact 分類は [rank_analysis.md](rank_analysis.md) 参照。
