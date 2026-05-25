# 下流データ更新ガイド

`judge_cited_pairs.py` の実行が進んだとき、このファイルを最初に読む。

---

## 1. まず現状を確認する

```bash
cd /home/sonozuka/design_similarity

# qwen_similarity_results の進捗確認
for f in /mnt/eightthdd/uspto/qwen_similarity_results/*.jsonl; do
    total=$(wc -l < /mnt/eightthdd/uspto/cited_image_pairs/$(basename $f) 2>/dev/null || echo "?")
    done=$(wc -l < $f)
    echo "$(basename $f .jsonl): ${done}/${total}"
done
```

前回の記録との差分が「更新すべき量」。差分があれば次の手順を実行する。

---

## 2. 下流を一括更新する（通常）

```bash
cd /home/sonozuka/design_similarity
python update_downstream.py
```

**これだけでよい。** 年の指定は不要。新しい年のデータは自動で検出される。

処理時間の目安（2021/2022 が追加された場合）:
- Step A〜C: 5〜10 分（resume あり、処理済みはスキップ）
- Step D〜J: 1 分以内

---

## 3. ステップ詳細

実行順序は依存関係に基づいて決まる（アルファベット順ではない）:

| 実行順 | Step | スクリプト | 出力先 | 依存 | 動作 |
|--------|------|-----------|--------|------|------|
| 1 | A | `extract_all_pairs.py` | `all_pair/qwen_all_pairs/` | — | 新規ペアのみ追記 |
| 2 | B | `extract_yes_pairs.py` | `yes_pair/qwen_yes_pairs/` | — | 新規 Yes ペアのみ追記 |
| 3 | C | `analysis/split_by_reason.py` | `yes_pair/qwen/{exact_match,high_similar,similar}/` | B | 新規のみ追記 |
| 4 | D | `export_diagonal_csv.py` | `output/diagonal_summary.csv` | A/B/C | 全件上書き |
| 5 | E | `make_two_heatmaps.py` | `output/heatmap_*.png` | A/B/C | 全件上書き |
| 6 | G | `vector/join_judgments.py --no-resume` | `class/D18/rank_judgments/cosine_numpy/all.jsonl` | — | 全件上書き |
| 7 | H | `vector/analysis/rank_analysis.py` | `vector/output/D18/` | G | 全件上書き |
| 8 | I | `vector/analysis/export_yes_reasons.py` | `vector/output/D18/yes_sim080_reasons.csv` | G | 全件上書き |
| 9 | J | `vector/analysis/export_non_exact_pairs.py` | `rank_analysis/D18/.../non_exact_pairs/` | G | 全件上書き |
| 10 | **F** | `export_pipeline_counts.py` | `output/pipeline_counts.csv` | **D・G** | 全件上書き |

> **注意:** Step F は `diagonal_summary.csv`（Step D）と `all.jsonl`（Step G）の両方を読む。
> 必ず Step D と Step G の後に実行する必要がある。

グラフ解析（通常は手動で判断して実行）:

| Step | スクリプト | 出力先 | 動作 |
|------|-----------|--------|------|
| K | `graph/graph_analysis.py` | `graph/output/D18/triadic_scored.jsonl` | 全件上書き |
| L | `graph/extract_high_sim_triads.py` | `graph/output/D18/high_sim_triads/` | 全件上書き |
| M | `graph/verify/wcc_scoring.py` | `graph/output/D18/verify/` | 全件上書き |

グラフ解析も含めて更新するには:

```bash
python update_downstream.py --with-graph
```

---

## 4. 一部のステップだけ再実行する

```bash
# D 以降（集計・可視化系）だけ再実行
python update_downstream.py --from-step D

# G 以降（ベクトル結合・分析）だけ再実行
python update_downstream.py --from-step G

# 特定ステップだけ
python update_downstream.py --steps F G
```

---

## 5. 年の自動検出について（重要）

`qwen_similarity_results/` に新しい年（例: 2022.jsonl）のデータが増えても、
追加設定は不要。全スクリプトは glob で年を自動検出する。

**ただし、以下のケースでは手動対応が必要:**

| ケース | 必要な手動対応 |
|--------|--------------|
| 2023 年以降の新しい年が追加された | [vector/doc/pipeline.md](vector/doc/pipeline.md) の「新しい年が追加されたとき」を参照。`add_class_to_edge_list.py` → Steps 1〜4 を実行 |
| D18 以外のクラスを分析したい | `python update_downstream.py --class D10` で Step G〜J を別クラスで実行。ただし事前に Steps 1〜4 が必要 |

---

## 6. 出力ファイル一覧（更新後に変わるもの）

```
output/
  diagonal_summary.csv          ← クラス別 within/cross-class 件数
  pipeline_counts.csv           ← 論文テーブル用集計
  heatmap_reference.png         ← 全ペアのクラス間ヒートマップ
  heatmap_similar.png           ← 類似ペアのクラス間ヒートマップ

/mnt/eightthdd/uspto/
  all_pair/qwen_all_pairs/      ← 全ペア（年別 JSONL）
  yes_pair/qwen_yes_pairs/      ← Yes ペア（年別 JSONL）
  yes_pair/qwen/exact_match/    ← Yes の内 完全一致（JSONL + 画像）
  yes_pair/qwen/high_similar/   ← Yes の内 高類似（JSONL + 画像）
  yes_pair/qwen/similar/        ← Yes の内 通常類似（JSONL + 画像）
  class/D18/rank_judgments/cosine_numpy/all.jsonl  ← D18 全ペア + LLM 判定結合

vector/output/D18/cosine_numpy/
  rank_ccdf_perspective.png
  rank_scatter_perspective.png
  rank_density_perspective*.png
  yes_sim080_reasons.csv
  high_sim_perspective_0950*.csv

/mnt/eightthdd/uspto/class/D18/rank_analysis/cosine_numpy/perspective/non_exact_pairs/

graph/output/D18/              ← --with-graph 指定時のみ更新
  triadic_scored.jsonl
  high_sim_triads/
  verify/
```

---

## 7. 処理状況の記録（更新のたびに手動で更新する）

→ [judge_cited_pairs_downstream.md](judge_cited_pairs_downstream.md)

---

## 8. パイプライン全体図

```
judge_cited_pairs.py
    ↓ qwen_similarity_results/{year}.jsonl
    │
    ├─[A] extract_all_pairs    → all_pair/qwen_all_pairs/{year}.jsonl
    │         ↓
    ├─[B] extract_yes_pairs    → yes_pair/qwen_yes_pairs/{year}.jsonl
    │         ↓
    ├─[C] split_by_reason      → yes_pair/qwen/{exact_match,high_similar,similar}/
    │         ↓
    ├─[D] export_diagonal_csv  → output/diagonal_summary.csv ─────────────────────┐
    ├─[E] make_two_heatmaps    → output/heatmap_*.png                              │
    │                                                                               │
    ├─[G] join_judgments       → class/D18/rank_judgments/.../all.jsonl ──────────┤
    │         ↓                                                                    │
    ├─[H] rank_analysis        → vector/output/D18/                               │
    ├─[I] export_yes_reasons   → vector/output/D18/yes_sim080_reasons.csv          │
    ├─[J] export_non_exact     → rank_analysis/D18/.../non_exact_pairs/            │
    │                                                                               ↓
    └─[F] export_pipeline_counts ← D（diagonal_summary.csv）と G（all.jsonl）に依存
               → output/pipeline_counts.csv

    (all.jsonl を参照、--with-graph 時のみ)
    ├─[K] graph_analysis       → graph/output/D18/triadic_scored.jsonl
    ├─[L] extract_high_sim     → graph/output/D18/high_sim_triads/
    └─[M] wcc_scoring          → graph/output/D18/verify/
```

---

## 関連ドキュメント

- [judge_cited_pairs_downstream.md](judge_cited_pairs_downstream.md) — 処理状況の記録と詳細手順
- [vector/doc/pipeline.md](vector/doc/pipeline.md) — ベクトル検索パイプライン（Step 1〜5）
- [doc/architecture.md](doc/architecture.md) — 全パイプラインの設計図