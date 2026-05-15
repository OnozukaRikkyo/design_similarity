# クラス間引用ヒートマップ可視化スクリプト (`visualize_ergm_network.py`)

USPTO 意匠特許類似ペアの JSONL データから、クラス間引用頻度ヒートマップ（Figure E）を生成する。

---

## スクリプト

```
/home/sonozuka/design_similarity/visualize_ergm_network.py
```

---

## 改訂履歴

| 時期 | 内容 |
|------|------|
| 初期実装 | Chakraborty et al. (2020) 全方程式 ERGM 可視化（8 図 + LaTeX） |
| 2025-05 第1改訂 | データソースを JSONL に変更、ネットワーク描画（Fig1）のみに絞り込み |
| 2025-05 第2改訂 | ネットワーク描画を廃止、クラス間引用ヒートマップ（Figure E）に変更 |

---

## 現在の動作モード

**クラス間引用頻度ヒートマップのみ**を生成する。

| 項目 | 内容 |
|------|------|
| 入力 | `/mnt/eightthdd/uspto/yes_pair/qwen/` 以下の `*.jsonl` を再帰的に読み込み |
| 集計 | `source_class`・`target_class` のペア件数をカウント |
| 表示 | 件数上位 `--top-n` クラスの N×N 行列（log スケール） |
| 出力 | `output/network/figE_class_heatmap.png` |

---

## ヒートマップの見方

| 視覚要素 | 意味 |
|---------|------|
| 行（y 軸） | Source class：引用する側（citing patent）の Locarno クラス |
| 列（x 軸） | Target class：引用される側（cited patent）の Locarno クラス |
| セルの色 | `log(引用件数 + 1)`（YlOrRd カラーマップ） |
| ティール枠（対角） | Within-class 引用（同一クラス内ペア） |
| セル内の数値 | 最大値の 4% 以上のセルに実件数を表示 |

### 指標の解釈

1. **対角の明るさ** → Class Homophily の強さ
2. **off-diagonal の明るいセル** → 技術的に隣接するクラス間の引用集中
3. **行全体の明るさの偏り** → 特定クラスが広範囲に引用している（汎用技術）

---

## 入出力

| 項目 | パス | 形式 |
|------|------|------|
| 入力 | `/mnt/eightthdd/uspto/yes_pair/qwen/**/*.jsonl` | JSONL（1行1ペア） |
| 出力 | `output/network/figE_class_heatmap.png` | 300 DPI PNG |

### 使用する JSONL フィールド

| フィールド | 用途 |
|-----------|------|
| `source_class` | 引用する側の D-class（例: `"D14 38"` → `"D14"`） |
| `target_class` | 引用される側の D-class |

### ディレクトリ構造

```
/mnt/eightthdd/uspto/yes_pair/qwen/
├── exact_match/jsonl/2007.jsonl … 2012.jsonl
├── high_similar/jsonl/2007.jsonl … 2012.jsonl
└── similar/jsonl/2007.jsonl … 2012.jsonl
```

---

## 主要関数

| 関数 | 役割 |
|------|------|
| `parse_class_padded(raw)` | `"D14 38"` → `"D14"`、`"D 6480"` → `"D06"`（ゼロ埋め2桁） |
| `load_class_pairs(root)` | JSONL を再帰的に読み込み、クラスペア件数・クラス別件数を返す |
| `fig_class_heatmap(class_pair_cnt, all_cls_cnt, out_path, top_n)` | ヒートマップを描画・保存 |

---

## 実行方法

```bash
# デフォルト（上位 14 クラス、output/network/ に出力）
python visualize_ergm_network.py

# 表示クラス数を変更
python visualize_ergm_network.py --top-n 20

# 入力・出力先を明示指定
python visualize_ergm_network.py \
  --data-dir /mnt/eightthdd/uspto/yes_pair/qwen \
  --out-dir output/network \
  --top-n 14
```

### オプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--data-dir` | `/mnt/eightthdd/uspto/yes_pair/qwen` | JSONL ファイルのルートディレクトリ |
| `--out-dir` | `output/network` | 出力先ディレクトリ |
| `--top-n` | `14` | 表示するクラス数（引用件数上位 N クラス） |

---

## 旧実装：ネットワーク描画方式（参考）

第1・第2改訂で廃止した描画方式の記録。

### Kamada-Kawai レイアウト（初期・第1改訂）

- ノード間の**グラフ距離（最短経路長）**を物理的な距離に対応させる最適化
- クラスター構造が明確、計算量 **O(n³)**
- 数百ノードまでが現実的な上限 → 上位 300 ノードのサブグラフのみ描画

### Spring レイアウト・Fruchterman-Reingold（第1改訂）

- ノードを「電荷を持った粒子」、エッジを「ばね」としてシミュレーション
- 計算量 **O(n²) × iter**（`iterations=50`）で数千ノードに対応
- ノード数 ≤ 500 は Kamada-Kawai、> 500 は Spring に自動切り替え
- 全ノード・全エッジを描画（`--top-n 0`）

### 廃止理由

6,000+ ペアのデータでは「特許番号ノード・類似ペアエッジ」のネットワークよりも、**クラス間の引用パターン**を集約したヒートマップの方が研究上の示唆を得やすいため。

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [extract_yes_pairs.md](extract_yes_pairs.md) | `visualize_ergm_network.py` | 論文・プレゼン資料への組み込み |
| `/mnt/eightthdd/uspto/yes_pair/qwen/**/*.jsonl` | → `output/network/figE_class_heatmap.png` | — |
