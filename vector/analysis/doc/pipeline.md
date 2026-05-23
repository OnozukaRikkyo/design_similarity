# 分析パイプライン処理順序

`rank_analysis.py` および `export_non_exact_pairs.py` が依存するデータは、以下の順序で生成される。
**各ステップは前ステップの出力を入力とするため、順序通りに実行しなければならない。**

---

## 全体フロー

```
[Step 1] compute_ranks.py
         ↓ rank_results/{sim_func}/{year}.jsonl

[Step 2] Qwen 類似判定（外部バッチ処理）
         ↓ qwen_similarity_results/{year}.jsonl

[Step 3] join_judgments.py
         ↓ rank_judgments/{sim_func}/all.jsonl

[Step 4a] rank_analysis.py           ← 統計図・散布図（exact/non-exact 分類込み）
[Step 4b] export_yes_reasons.py      ← Yes ペア CSV（調査用）
[Step 4c] export_non_exact_pairs.py  ← Non-exact ペア画像出力（調査用）
```

Step 4a〜4c は同じ `all.jsonl` を入力とするため、順序不問で並列実行可能。

---

## 各ステップの詳細

### Step 1: ランク検索（`compute_ranks.py`）

**入力:**
```
class/{CLASS}/rank_index/{type}/
  patent_ids.npy
  vectors_l2norm.npy
  file_paths.txt
```

**出力:**
```
class/{CLASS}/rank_results/{sim_func}/{year}.jsonl
```

各行 = 1 引用ペア。`source` がクエリ、`target` が引用対象。コサイン類似度と順位を付与。

---

### Step 2: Qwen 類似判定（外部バッチ）

画像ペアを Qwen3-VL に投げ、`Yes` / `No` と信頼度・理由テキスト（`reason`）を取得する外部バッチ処理。

**出力:**
```
/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl
```

各行フィールド: `source`, `target`, `judgment`, `confidence`, `reason`

---

### Step 3: 結合（`join_judgments.py`）

Step 1 のランク結果と Step 2 の LLM 判定を `(source, target)` キーで結合。
画像パスは `rank_results` の `source_image`/`target_image` フィールドからそのまま引き継ぐ。

**入力:**
```
class/{CLASS}/rank_results/{sim_func}/{year}.jsonl   ← rank・similarity・画像パスを含む
/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl
```

**出力:**
```
class/{CLASS}/rank_judgments/{sim_func}/all.jsonl
```

1行 = 1 (ペア × 画像タイプ) レコード。全年・全タイプを1ファイルに結合。

| フィールド | 内容 |
|-----------|------|
| `source` | クエリ特許番号 |
| `target` | 引用対象特許番号 |
| `type` | 画像タイプ（perspective / front / overview）|
| `rank` | ランク順位 |
| `similarity` | コサイン類似度 |
| `judgment` | `Yes` / `No` / `Unknown` |
| `confidence` | 1〜5（Unknown 時は 0）|
| `reason` | LLM の判定根拠テキスト |
| `source_image` | ソース画像パス |
| `target_image` | ターゲット画像パス |

実行:
```bash
python vector/join_judgments.py --class D18 --sim cosine_numpy
```

---

### Step 4a: 統計分析・散布図（`rank_analysis.py`）

`all.jsonl` を読み込み、`reason` フィールドのキーワードマッチで Yes ペアを `Yes_exact` / `Yes_nonexact` に分類してから図を生成する。

→ 詳細は [rank_analysis.md](rank_analysis.md) 参照

---

### Step 4b: Yes ペア CSV 出力（`export_yes_reasons.py`）

`judgment=Yes` かつ類似度閾値以上のレコードを CSV に書き出す。手動レビュー用。

**出力:**
```
vector/output/{CLASS}/{sim_func}/yes_sim{threshold}_reasons.csv
```

実行:
```bash
python vector/analysis/export_yes_reasons.py --class D18 --min-sim 0.8
```

---

### Step 4c: Non-exact ペア画像出力（`export_non_exact_pairs.py`）

`judgment=Yes` のうち `reason` が完全一致キーワードを含まないペアの画像を出力する。

→ 詳細は [export_non_exact_pairs.md](export_non_exact_pairs.md) 参照

---

## Exact / Non-exact 分類ロジック（Step 4a・4c 共通）

`judgment=Yes` のレコードを `reason` フィールドのキーワードマッチでさらに 2 種に分類する。

### デフォルト（フォールバックキーワード）

```python
FALLBACK_EXACT_KEYWORDS = ["identical", "exact", "same"]
```

`reason` テキストにこれらのいずれかが単語境界（`\b`）でマッチすれば `Yes_exact`、しなければ `Yes_nonexact`。

### LLM キーワード取得（`--use-llm` 指定時）

Qwen3-VL-4B-Instruct に全 Yes レコードの `reason` 一覧を渡し、完全一致を示すキーワードと非完全一致を示すキーワードを JSON で返させる。LLM 応答の解析失敗時はフォールバックキーワードを使用する。

**LLM を使う場合の実行例:**
```bash
python vector/analysis/rank_analysis.py --class D18 --use-llm
python vector/analysis/export_non_exact_pairs.py --class D18 --use-llm
```

### D18 perspective の分類結果（2026-05-19）

| カテゴリ | 件数 | 割合 |
|---------|------|------|
| Yes_exact | 102 | 94% |
| Yes_nonexact | 7 | 6% |
| No | 459 | — |
| Unknown | 16 | — |

---

## データの所在

| データ | パス |
|--------|------|
| ランクインデックス | `/mnt/eightthdd/uspto/class/{CLASS}/rank_index/{type}/` |
| ランク検索結果 | `/mnt/eightthdd/uspto/class/{CLASS}/rank_results/{sim_func}/{year}.jsonl` |
| 引用画像ペア | `/mnt/eightthdd/uspto/class/{CLASS}/cited_image_pairs/{year}.jsonl` |
| Qwen 判定結果 | `/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` |
| 結合済み判定 | `/mnt/eightthdd/uspto/class/{CLASS}/rank_judgments/{sim_func}/all.jsonl` |
| 統計図 | `vector/output/{CLASS}/{sim_func}/*.png` |
| Non-exact ペア画像 | `/mnt/eightthdd/uspto/class/{CLASS}/rank_analysis/{sim_func}/{type}/non_exact_pairs/` |
