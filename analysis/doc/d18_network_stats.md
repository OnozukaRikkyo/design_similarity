# D18 共引用ネットワーク統計 (`analysis/d18_network_stats.py`)

D18 within-class 共引用ネットワークのノード数・エッジ数・次数統計を出力するスクリプト。

---

## スクリプト

```
/home/sonozuka/design_similarity/analysis/d18_network_stats.py
```

---

## 入出力

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/all_pair/qwen_all_pairs/*.jsonl` | JSONL（論文の 55,794 ペアと同一集合） |
| 出力 | 標準出力 | テキスト |

---

## データソース

論文記載の 55,794 ペアと同じ `qwen_all_pairs/*.jsonl` + `parse_class` フィルタ（D01〜D34）を使用し、
さらに source・target の両方が `D18` であるペアのみを抽出する。

---

## 実測値（2026-05-27 時点）

| 統計量 | 値 |
|--------|---|
| ノード数（ユニーク特許） | 1,054 |
| エッジ数（ユニークペア） | 1,610 |
| 平均次数 | 3.0550 |
| 最大次数 | 21（D0832343） |
| 最小次数 | 1（D0638051） |

---

## 実行方法

```bash
# デフォルト実行
python analysis/d18_network_stats.py

# エッジディレクトリを指定
python analysis/d18_network_stats.py --edge-dir /mnt/eightthdd/uspto/all_pair/qwen_all_pairs
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--edge-dir` | `/mnt/eightthdd/uspto/all_pair/qwen_all_pairs` | 共引用ペア JSONL のディレクトリ |

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `build_edge_list.py`（STEP 1） | `analysis/d18_network_stats.py` | 論文・発表スライドへの組み込み |
| `qwen_all_pairs/*.jsonl` | → 標準出力 | — |
