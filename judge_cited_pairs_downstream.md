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

---

## 出力先

| ファイル | 内容 |
|----------|------|
| `/mnt/eightthdd/uspto/class/D18/rank_judgments/cosine_numpy/all.jsonl` | 全ペアの判定結合結果 |
| `vector/output/D18/cosine_numpy/rank_ccdf_perspective.png` | CCDF 図 |
| `vector/output/D18/cosine_numpy/rank_scatter_perspective.png` | 散布図 |
| `vector/output/D18/cosine_numpy/yes_sim080_reasons.csv` | Yes ペア CSV |
| `/mnt/eightthdd/uspto/class/D18/rank_analysis/cosine_numpy/perspective/non_exact_pairs/` | 非完全一致画像 |

---

## 詳細ドキュメント

- パイプライン全体: [vector/doc/pipeline.md](vector/doc/pipeline.md)
- Step 5 の仕様: [vector/doc/join_judgments.md](vector/doc/join_judgments.md)