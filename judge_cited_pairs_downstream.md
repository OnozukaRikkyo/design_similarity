# judge_cited_pairs.py が出力を更新したときの手順

`judge_cited_pairs.py` の処理が進んで
`/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` が更新されたとき、
下流データ（`all.jsonl` と分析図）を更新するための手順。

---

## 実行コマンド

```bash
cd /home/sonozuka/design_similarity

# 全下流を一括更新（毎回このコマンドだけでよい）
python update_downstream.py

# 特定ステップ以降のみ実行（例: Step D 以降）
python update_downstream.py --from-step D

# 別クラス指定
python update_downstream.py --class D10
```

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

> **Step F は Step D と Step G の両方に依存する。** `pipeline_counts.csv` には `diagonal_summary.csv`（Step D）と `all.jsonl`（Step G）の両方のデータが含まれるため、必ず最後に実行する。

> Step 1〜4（ペア抽出・ベクトル生成・インデックス・ランク検索）は `qwen_similarity_results/` と無関係なので不要。

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

### 処理状況（2026-05-25 更新）

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
2021.jsonl: 4258/46614  処理中（D18分: 1/35 判定済み）
2022.jsonl: 0/17127     未処理（D18分: 0/66）
```

### all.jsonl の判定内訳（2026-05-25 更新、D18 / cosine_numpy）

| judgment | 件数 |
|----------|-----:|
| Yes      |  222 |
| No       | 1,208|
| Unknown  |  100 |
| **合計** | **1,530** |

> 2021 の D18 ペア 35 件は 1 件のみ判定済み。2022 の D18 ペア 66 件は未処理。

---

## 出力先

| ファイル | 内容 |
|----------|------|
| `/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl` | 全ペアの判定結合結果 |
| `vector/output/D18/cosine_numpy/rank_ccdf_perspective.png` | CCDF 図 |
| `vector/output/D18/cosine_numpy/rank_scatter_perspective.png` | 散布図 |
| `vector/output/D18/cosine_numpy/yes_sim080_reasons.csv` | Yes ペア CSV |
| `/mnt/eightthdd/uspto/class/D18/rank_analysis/cosine_numpy/perspective/non_exact_pairs/` | 非完全一致画像 |
| `output/diagonal_summary.csv` | クラス別引用ペア数・類似ペア数 |
| `output/pipeline_counts.csv` | 論文テーブル用パイプライン集計 CSV |
| `output/heatmap_reference.png` | クラス間引用頻度ヒートマップ（全ペア） |
| `output/heatmap_similar.png` | クラス間引用頻度ヒートマップ（LLM 類似ペア） |

---

## 詳細ドキュメント

- パイプライン全体: [vector/doc/pipeline.md](vector/doc/pipeline.md)
- Step 5 の仕様: [vector/doc/join_judgments.md](vector/doc/join_judgments.md)