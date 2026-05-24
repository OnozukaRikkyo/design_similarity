# judge_cited_pairs.py が出力を更新したときの手順

`judge_cited_pairs.py` の処理が進んで
`/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` が更新されたとき、
下流データ（`all.jsonl` と分析図）を更新するための手順。

---

## 実行コマンド

```bash
cd /home/sonozuka/design_similarity
CLASS=D18

# Step 5: all.jsonl を再生成
python vector/join_judgments.py --class ${CLASS} --sim cosine_numpy --no-resume

# 分析図を再生成
python vector/analysis/rank_analysis.py --class ${CLASS}
python vector/analysis/export_yes_reasons.py --class ${CLASS}
python vector/analysis/export_non_exact_pairs.py --class ${CLASS}

# 集計 CSV を再生成
python export_diagonal_csv.py
python export_pipeline_counts.py

# ヒートマップ図を再生成
python make_two_heatmaps.py
```

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

### 処理状況（2026-05-24 更新）

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
2020.jsonl: 9461/55765  処理中
2021.jsonl: 0/46614     未処理
2022.jsonl: 0/17127     未処理
```

### all.jsonl の判定内訳（2026-05-24 更新、D18 / cosine_numpy）

| judgment | 件数 |
|----------|-----:|
| Yes      |  217 |
| No       | 1,157|
| Unknown  |  156 |
| **合計** | **1,530** |

> 2020 の D18 ペア 56 件はまだ未判定（2020.jsonl の 9,461 件に D18 分は含まれていない）。

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