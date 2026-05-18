# ランク検索結果の統計分析・可視化 (`rank_analysis.py`)

ベクトルランク検索結果（`compute_ranks.py` 出力）と LLM 類似判定（`qwen_similarity_results/`）を結合し、3 種の図を生成する。

---

## スクリプト

```
/home/sonozuka/design_similarity/vector/analysis/rank_analysis.py
```

---

## 出力ファイル

```
vector/output/{CLASS}/{sim_func}/
  rank_ccdf_{type}.png          — Figure 1: 順位の CCDF
  rank_scatter_{type}.png       — Figure 2: 順位 vs 類似度の散布図
  pair_comparison/
    {src}--{tgt}_{type}_top10.png — Figure 3: ベースペア + Top-10 近傍グリッド
```

---

## Figure 1: 順位の CCDF

**横軸**: 順位 $r$（1〜`n_candidates`）  
**縦軸**: $P(\mathrm{rank} \geq r)$（補累積分布関数）

| 系列 | 内容 |
|------|------|
| Similar (Yes) | LLM が類似と判定した引用ペア（青実線） |
| Non-similar (No) | LLM が非類似と判定した引用ペア（赤破線） |
| Random baseline | 順位が一様分布の場合の期待値（灰点線） |

**D18 perspective の観察（2026-05-18）:**

- Yes 群の中央値ランク: **4** / 456  
- No 群の中央値ランク: **29** / 456  
- 両群ともランダム期待値（斜線）を大きく下回り、ベクトル類似度が引用の視覚的関係を捉えていることを示す  
- Yes 群は No 群より急峻に降下 → LLM 判定と視覚的類似度ランクの整合性を確認

---

## Figure 2: 順位 vs 類似度の散布図

**横軸**: 順位 $r$  
**縦軸**: コサイン類似度 $r_{\rm s}$

| マーカー | 意味 |
|---------|------|
| 青●（Yes） | 期待値となる入力画像ペア（引用かつ LLM 類似判定） |
| 赤×（No） | LLM 非類似判定の引用ペア |
| 灰△（Unknown） | qwen 結果に対応なし |
| 緑☆（Selected） | 代表ペア（Yes・信頼度 5 のうち中央値ランクに最近傍） |

Yes 群は散布図の左上（低ランク・高類似度）に集中し、No 群は全域に分布する。

---

## Figure 3: ペア比較画像グリッド

**構成（3行 × 5列）:**

| 位置 | 内容 |
|------|------|
| Row 0, Col 0–1 | Query 画像 A（クエリ特許） |
| Row 0, Col 2–3 | Expected 画像 B（引用対象、LLM 判定付き） |
| Row 0, Col 4 | 統計情報テキストボックス |
| Row 1, Col 0–4 | Top-1 〜 Top-5 近傍（類似度降順） |
| Row 2, Col 0–4 | Top-6 〜 Top-10 近傍 |

引用対象 B が Top-10 に含まれる場合はオレンジ枠と `[cited target]` ラベルで強調表示する。

画像は `ImageProcessor.process_file()` で前処理済み（余白除去・長辺 768px・RGB）。

**D18 perspective の代表ペア（D0574419 → D0574421）:**

- 引用対象 B のランク: **4** / 456（Top-10 圏内に引用ペアが出現）
- コサイン類似度: **0.9591**
- LLM 判定: Yes（信頼度 5）

---

## 入力

| データ | パス |
|--------|------|
| ランク検索結果 | `/mnt/eightthdd/uspto/class/{CLASS}/rank_results/{sim_func}/{year}.jsonl` |
| LLM 判定結果 | `/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` |
| ランクインデックス | `/mnt/eightthdd/uspto/class/{CLASS}/rank_index/{type}/` |

---

## 図のスタイル

PRL（Physical Review Letters）シングルカラム準拠:

| 設定 | 値 |
|------|-----|
| フォント | Times New Roman / serif |
| フォントサイズ | 9pt（ラベル 10pt） |
| 列幅 | 3.37 inch |
| DPI | 300 |
| 目盛り方向 | 内向き（全 4 辺） |

---

## 代表ペアの選択ロジック

1. LLM 判定 Yes かつ信頼度 5 のペアを候補とする
2. そのうち順位の中央値に最も近いペアを選ぶ
3. Yes・信頼度 5 が存在しない場合は Yes 全体にフォールバック

---

## 実行方法

```bash
# D18（デフォルト）
python vector/analysis/rank_analysis.py --class D18

# 別クラス
python vector/analysis/rank_analysis.py --class D10

# 画像タイプ指定
python vector/analysis/rank_analysis.py --class D18 --type overview

# Top-k を変更
python vector/analysis/rank_analysis.py --class D18 --top-k 15
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--class` | `D18` | 対象クラスコード |
| `--sim` | `cosine_numpy` | 類似度関数 |
| `--type` | `perspective` | 画像タイプ |
| `--top-k` | `10` | ペア比較図の近傍数 |

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [compute_ranks.md](../../doc/compute_ranks.md) | `rank_analysis.py` | 論文図の使用 |
| `rank_results/{sim_func}/{year}.jsonl` | → `vector/output/{CLASS}/{sim_func}/*.png` | |
| `qwen_similarity_results/{year}.jsonl` | | |
