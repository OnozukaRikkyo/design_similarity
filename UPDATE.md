# design_similarity パイプライン 更新ガイド

データが更新されたとき、**最初にこのファイルを読む。**

---

## 実行コマンド（これだけ）

### qwen_similarity_results/ が進んだとき（通常の更新）

```bash
cd /home/sonozuka/design_similarity
python update_downstream.py          # グラフ解析を含む全ステップ
python update_downstream.py --no-graph  # グラフ解析をスキップ（高速化）
```

### wcc グリッド図だけ更新したいとき

```bash
python update_downstream.py --wcc
```

`wcc_fp_grid.png` / `wcc_fn_grid.png` / `wcc_threshold_grid.png` の3図を再生成します。

### 新クラス・新年のベクトルインデックスから再構築するとき

```bash
python update_downstream.py --with-vector --no-gpu --class D18
```

---

## 現状確認

```bash
for f in /mnt/eightthdd/uspto/qwen_similarity_results/*.jsonl; do
    total=$(wc -l < /mnt/eightthdd/uspto/cited_image_pairs/$(basename $f) 2>/dev/null || echo "?")
    done=$(wc -l < $f)
    echo "$(basename $f .jsonl): ${done}/${total}"
done
```

前回の記録 → [judge_cited_pairs_downstream.md](judge_cited_pairs_downstream.md)

---

## パイプライン全体図

```
judge_cited_pairs.py（別サーバーで実行中）
    ↓ qwen_similarity_results/{year}.jsonl

    ╔══════════════════════════════════════════════════════════════╗
    ║  python update_downstream.py                                 ║
    ║                                                              ║
    ║  [--with-vector 時のみ]                                      ║
    ║  V1 filter_pairs_by_class  → class/D18/cited_image_pairs/   ║
    ║  V2 build_class_vectors    → class/D18/cited_image_vectors/  ║
    ║  V3 build_rank_index       → class/D18/rank_index/           ║
    ║  V4 compute_ranks          → class/D18/rank_results/         ║
    ║                                                              ║
    ║  [デフォルト]                                                ║
    ║  A  extract_all_pairs      → all_pair/qwen_all_pairs/        ║
    ║  B  extract_yes_pairs      → yes_pair/qwen_yes_pairs/        ║
    ║  C  split_by_reason        → yes_pair/qwen/{3分類}/          ║
    ║  D  export_diagonal_csv    → output/diagonal_summary.csv     ║
    ║  E  make_two_heatmaps      → output/heatmap_*.png            ║
    ║  G  join_judgments         → class/D18/rank_judgments/       ║
    ║                               cosine_numpy/all.jsonl         ║
    ║  H  rank_analysis          → vector/output/D18/cosine_numpy/ ║
    ║       sim_histogram_perspective.png                          ║
    ║       rank_ccdf_perspective.png                              ║
    ║       rank_scatter_perspective.png                           ║
    ║       rank_density_perspective*.png                          ║
    ║       high_sim_perspective_0950*.csv                         ║
    ║  I  export_yes_reasons     → yes_sim080_reasons.csv          ║
    ║  J  export_non_exact_pairs → rank_analysis/.../non_exact/    ║
    ║  F  export_pipeline_counts → output/pipeline_counts.csv      ║
    ║       ※ D と G 両方完了後に実行（依存あり）                  ║
    ║                                                              ║
    ║  [デフォルト実行、--no-graph でスキップ]                       ║
    ║  K  graph_analysis         → graph/output/D18/               ║
    ║                               triadic_scored.jsonl           ║
    ║  L  extract_high_sim_triads→ graph/output/D18/high_sim/      ║
    ║  N  discord_analysis       → graph/output/D18/verify/        ║
    ║                               fp.csv / fn.csv  ← K に依存    ║
    ║  M  wcc_scoring            → graph/output/D18/verify/        ║
    ║                               wcc_*_grid.png  ← K,N に依存   ║
    ╚══════════════════════════════════════════════════════════════╝
```

---

## ステップ詳細

| 実行順 | Step | スクリプト | 依存 | 重複処理 |
|--------|------|-----------|------|---------|
| — | V1 | `vector/filter_pairs_by_class.py` | — | resume |
| — | V2 | `vector/build_class_vectors.py` | V1 | resume |
| — | V3 | `vector/build_rank_index.py` | V2 | resume |
| — | V4 | `vector/compute_ranks.py` | V3 | resume |
| 1 | A | `extract_all_pairs.py` | — | resume |
| 2 | B | `extract_yes_pairs.py` | — | resume |
| 3 | C | `analysis/split_by_reason.py` | B | resume |
| 4 | D | `export_diagonal_csv.py` | A,B,C | 全件上書き |
| 5 | E | `make_two_heatmaps.py` | A,C | 全件上書き |
| 6 | G | `vector/join_judgments.py` | V4 or 既存 | 全件上書き |
| 7 | H | `vector/analysis/rank_analysis.py` | G | 全件上書き |
| 8 | I | `vector/analysis/export_yes_reasons.py` | G | 全件上書き |
| 9 | J | `vector/analysis/export_non_exact_pairs.py` | G | 全件上書き |
| 10 | **F** | `export_pipeline_counts.py` | **D, G** | 全件上書き |
| — | K | `graph/graph_analysis.py` | G | 全件上書き |
| — | L | `graph/extract_high_sim_triads.py` | K | 全件上書き |
| — | N | `graph/verify/discord_analysis.py` | K,G | 全件上書き |
| — | M | `graph/verify/wcc_scoring.py` | K,N | 全件上書き |

V1〜V4 は `--with-vector` 時のみ実行。K〜M はデフォルトで実行（`--no-graph` でスキップ）。

---

## 部分実行オプション

```bash
# G 以降だけ再実行（all.jsonl から分析まで）
python update_downstream.py --from-step G

# 特定ステップだけ
python update_downstream.py --steps G H F

# D18 以外のクラスで G〜J を実行
python update_downstream.py --class D10

# ヘルプ
python update_downstream.py --help
```

---

## 処理状況の記録

→ [judge_cited_pairs_downstream.md](judge_cited_pairs_downstream.md)（更新のたびに手動で更新）

---

## 関連ドキュメント

- [doc/architecture.md](doc/architecture.md) — 全パイプラインの設計図
- [vector/doc/pipeline.md](vector/doc/pipeline.md) — ベクトル検索パイプライン詳細
