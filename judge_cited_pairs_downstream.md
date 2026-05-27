# judge_cited_pairs.py が出力を更新したときの手順

`judge_cited_pairs.py` の処理が進んで
`/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` が更新されたとき、
下流データ（集計・図・グラフ解析）を更新するための手順。

---

## 実行コマンド

```bash
cd /home/sonozuka/design_similarity
python update_downstream.py              # 全ステップ（グラフ解析含む）
python update_downstream.py --no-graph  # グラフ解析をスキップ（高速化）
python update_downstream.py --from-step G  # G 以降だけ再実行
```

詳細 → [UPDATE.md](UPDATE.md)

### ステップ一覧

実行順序は依存関係に基づく（アルファベット順ではない）:

| 実行順 | Step | スクリプト | 出力 | 重複処理 |
|--------|------|-----------|------|---------|
| 1 | A | `extract_all_pairs.py` | `all_pair/qwen_all_pairs/` | 処理済みペアをスキップ |
| 2 | B | `extract_yes_pairs.py` | `yes_pair/qwen_yes_pairs/` | 処理済みペアをスキップ |
| 3 | C | `analysis/split_by_reason.py` | `yes_pair/qwen/{exact_match,...}/` | 処理済みペアをスキップ |
| 4 | D | `export_diagonal_csv.py` | `output/diagonal_summary.csv` | 常に全件上書き |
| 5 | E | `make_two_heatmaps.py` | `output/heatmap_*.png` | 常に全件上書き |
| 6 | G | `vector/join_judgments.py --no-resume` | `rank_judgments/.../all.jsonl` | 常に全件上書き |
| 7 | H | `vector/analysis/rank_analysis.py` | `vector/output/D18/` | 常に全件上書き |
| 8 | I | `vector/analysis/export_yes_reasons.py` | `vector/output/D18/yes_sim080_reasons.csv` | 常に全件上書き |
| 9 | J | `vector/analysis/export_non_exact_pairs.py` | `rank_analysis/.../non_exact_pairs/` | 常に全件上書き |
| 10 | **F** | `export_pipeline_counts.py` | `output/pipeline_counts.csv` | 常に全件上書き |
| 11 | K | `graph/graph_analysis.py` | `graph/output/D18/summary.csv` など | 常に全件上書き |
| 12 | L | `graph/extract_high_sim_triads.py` | `graph/output/D18/high_sim_triads/` | 常に全件上書き |
| 13 | N | `graph/verify/discord_analysis.py` | `graph/output/D18/verify/{fp,fn}.csv` | 常に全件上書き |
| 14 | M | `graph/verify/wcc_scoring.py` | `graph/output/D18/verify/wcc_*_grid.png` | 常に全件上書き |

> **Step F は Step D と Step G の両方に依存する。** 必ず最後に実行する。
> **Step N は Step K に依存する。Step M は Step K と N の両方に依存する。**

---

## 現在の処理状況確認

```bash
for f in /mnt/eightthdd/uspto/qwen_similarity_results/*.jsonl; do
    total=$(wc -l < /mnt/eightthdd/uspto/cited_image_pairs/$(basename $f) 2>/dev/null || echo "?")
    done=$(wc -l < $f)
    echo "$(basename $f): ${done}/${total}"
done
```

0 件の年は `judgment=Unknown` になるが処理は正常に完了する。

### 処理状況（2026-05-27 更新）

```
2007.jsonl: 5859/5859   ✓
2008.jsonl: 6786/6786   ✓
2009.jsonl: 7630/7630   ✓
2010.jsonl: 7443/7443   ✓
2011.jsonl: 7957/7957   ✓
2012.jsonl: 9122/9122   ✓
2013.jsonl: 13577/13577 ✓
2014.jsonl: 14406/14406 ✓
2015.jsonl: 23272/23272 ✓
2016.jsonl: 40610/40610 ✓
2017.jsonl: 54278/54278 ✓
2018.jsonl: 52619/52619 ✓
2019.jsonl: 59044/59044 ✓
2020.jsonl: 55765/55765 ✓
2021.jsonl: 46614/46614 ✓
2022.jsonl: 17127/17127 ✓
```

### all.jsonl の判定内訳（2026-05-27 更新、D18 / cosine_numpy）

| judgment | 件数 |
|----------|-----:|
| Yes      |  227 |
| No       | 1,303|
| Unknown  |    0 |
| **合計** | **1,530** |

> 2022 完了・Unknown 解消済み。`python update_downstream.py` 再実行済み（2026-05-27 13:22）。

---

## 出力先（全ファイル一覧）

### 集計・ヒートマップ（Step D, E）
| ファイル | 内容 |
|----------|------|
| `output/diagonal_summary.csv` | クラス別引用ペア数・類似ペア数 |
| `output/heatmap_reference.png` | クラス間引用頻度ヒートマップ（全ペア） |
| `output/heatmap_similar.png` | クラス間引用頻度ヒートマップ（LLM 類似ペア） |
| `output/pipeline_counts.csv` | 論文テーブル用パイプライン集計 CSV |

### ベクトル検索 × 判定結合（Step G〜J）
| ファイル | 内容 |
|----------|------|
| `/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl` | 全ペアの判定結合結果 |
| `vector/output/D18/cosine_numpy/sim_histogram_perspective.png` | コサイン類似度分布 |
| `vector/output/D18/cosine_numpy/rank_ccdf_perspective.png` | CCDF 図 |
| `vector/output/D18/cosine_numpy/rank_scatter_perspective.png` | 散布図 |
| `vector/output/D18/cosine_numpy/rank_density_perspective*.png` | 2D 密度マップ |
| `vector/output/D18/cosine_numpy/high_sim_perspective_0950*.csv` | 高類似度ペア CSV |
| `vector/output/D18/cosine_numpy/yes_sim080_reasons.csv` | Yes ペア CSV |
| `/mnt/eightthdd/uspto/class/D18/rank_analysis/cosine_numpy/perspective/non_exact_pairs/` | 非完全一致画像 |

### グラフ解析（Step K〜M）
| ファイル | 内容 |
|----------|------|
| `graph/output/D18/summary.csv` | D18 グラフ基本統計（ノード数・ペア数・三角形数など） |
| `graph/output/D18/triadic_scored.jsonl` | 全三角形スコア（confidence 降順） |
| `graph/output/D18/score_distribution.png` | スコア分布図 |
| `graph/output/D18/top_triangles_network.png` | 上位三角形ネットワーク図 |
| `graph/output/D18/high_sim_triads/` | 高信頼三角形の画像（triad_001.png 〜） |
| `graph/output/D18/verify/fp.csv` / `fn.csv` | FP/FN 判定リスト |
| `graph/output/D18/verify/wcc_threshold_grid.png` | WCC 閾値グリッド図 |
| `graph/output/D18/verify/wcc_fp_grid.png` | FP WCC グリッド図 |
| `graph/output/D18/verify/wcc_fn_grid.png` | FN WCC グリッド図 |
| `graph/output/D18/verify/wcc_distribution.png` | WCC 分布図 |
| `graph/output/D18/verify/wcc_scored.jsonl` | WCC スコア付き全三角形 |

---

## 詳細ドキュメント

- パイプライン全体: [doc/architecture.md](doc/architecture.md)
- ステップ詳細: [UPDATE.md](UPDATE.md)
- ベクトル検索: [vector/doc/pipeline.md](vector/doc/pipeline.md)
- グラフ解析: [graph/triadic_scoring.md](graph/triadic_scoring.md)
- Step G の仕様: [vector/doc/join_judgments.md](vector/doc/join_judgments.md)
