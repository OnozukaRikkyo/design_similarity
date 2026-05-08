# ネットワーク可視化スクリプト (`visualize_ergm_network.py`)

`build_ergm_input.py` の出力をもとに、意匠特許共引用ネットワークをインタラクティブに可視化する。

---

## スクリプト

```
/home/sonozuka/design_similarity/visualize_ergm_network.py
```

---

## 処理フロー

```
ergm_input/arc_list.txt
ergm_input/attributes.txt
ergm_input/_patent_attr_cache.pkl  (任意)
        │
        │  load_arc_list() / arcs_to_undirected_edges()
        ▼
build_nx_graph()  ─── NetworkX グラフ構築（ノード属性: primary_class, date, patent_id）
        │
        ▼
compute_node_metrics()  ─── degree + betweenness 計算（N>500 は k-sample 近似）
        │
        ├─── extract_focus_subgraph()  ─── 上位 top_n + BFS hops のサブグラフ
        │         │
        │         ▼
        │   make_patent_network_html()  ─── output/network_patent_graph.html
        │         (yes_pairs 指定時は Gemini Yes エッジを橙色で重ね描き)
        │
        ├─── build_class_graph()  ─── D-class 単位に集約
        │         │
        │         ▼
        │   make_class_network_plots()  ─── output/network_class_graph.html
        │                                   output/network_class_graph.png
        │
        └─── save_summary()  ─── output/network_summary.csv
```

---

## 入出力

| 項目 | パス | 形式 |
|------|------|------|
| 入力 | `ergm_input/arc_list.txt` | テキスト（`u v` の行列） |
| 入力 | `ergm_input/attributes.txt` | タブ区切り CSV |
| 入力 | `ergm_input/_patent_attr_cache.pkl` | pickle（任意・patent_id マッピング用） |
| 入力 | `similarity_results/*.jsonl` | JSONL（`--sim-dir` 指定時のみ） |
| 出力 | `output/network_patent_graph.html` | Plotly インタラクティブ HTML |
| 出力 | `output/network_class_graph.html` | Plotly インタラクティブ HTML |
| 出力 | `output/network_class_graph.png` | 静止画 PNG |
| 出力 | `output/network_summary.csv` | グラフ要約統計 |
| メタ | `output/*.meta.json` | キャプション・説明 JSON |

---

## 出力詳細

### `network_patent_graph.html`

特許ノードのインタラクティブ可視化（サブグラフ）。

| 視覚要素 | 対応する情報 |
|---------|-------------|
| ノード色 | `primary_class`（D-class 別カラー）|
| ノードサイズ | `8 + 18 * log(degree+1) / log(10)` |
| エッジ色（グレー） | 共引用エッジ（通常） |
| エッジ色（橙） | Gemini 類似 Yes ペア（`--sim-dir` 指定時） |
| ホバー情報 | patent_id / class / date / degree / betweenness / n_classes |

### `network_class_graph.html` / `.png`

D-class 単位に集約した共引用ネットワーク。

| 視覚要素 | 対応する情報 |
|---------|-------------|
| ノードサイズ | `20 + 30 * log(count)` |
| ノード色 | D-class カラー |
| エッジ太さ | `0.5 + 9.5 * log(weight+1) / log(weight_max+1)` |
| ホバー情報 | class / 特許数 / クラス内エッジ数 / クラス間エッジ数 |

### `network_summary.csv`

| カラム | 内容 |
|--------|------|
| `metric` | 指標名 |
| `value` | 値 |

出力される指標：`full_nodes`, `full_edges`, `focus_nodes`, `focus_edges`, `class_nodes`, `class_edges`, `full_mean_degree`, `full_density`, `focus_density`, `focus_transitivity`

---

## 主要関数

| 関数 | 役割 |
|------|------|
| `load_arc_list(arc_path)` | `arc_list.txt` を `(u, v)` タプルのリストとして読み込む |
| `arcs_to_undirected_edges(arcs)` | 双方向アーク → 無向エッジリスト（重複除去） |
| `load_patent_cache(ergm_dir)` | `_patent_attr_cache.pkl` を読み込む（なければ `None`） |
| `build_nx_graph(n_nodes, edges, attrs, patent_cache_keys)` | NetworkX グラフを構築しノード属性を付与 |
| `compute_node_metrics(G, betweenness_k, seed)` | degree と betweenness を計算してノード属性に追加 |
| `extract_focus_subgraph(G, top_n, hops, metric)` | 指定メトリクス上位 `top_n` + BFS `hops` hop のサブグラフを抽出 |
| `load_gemini_yes_pairs(sim_dir, patent_cache_keys)` | similarity_results から Yes ペアを読み込み `(i, j)` の集合を返す |
| `make_patent_network_html(SG, out_path, title, yes_pairs)` | 特許グラフの Plotly HTML を生成 |
| `build_class_graph(G)` | 特許グラフを D-class 単位に集約した `nx.Graph` を返す |
| `make_class_network_plots(H, out_html, out_png)` | D-class グラフの HTML + PNG を生成 |
| `save_summary(G, SG, H, out_csv)` | グラフ要約統計を CSV に保存 |

---

## 実行方法

```bash
# デフォルト（degree 上位 250 件 + 1-hop、Gemini overlay なし）
python visualize_ergm_network.py

# 上位 300 件 + 2-hop
python visualize_ergm_network.py --top-n 300 --hops 2

# betweenness ベースでシード抽出
python visualize_ergm_network.py --top-n 150 --metric betweenness --betweenness-k 500

# Gemini Yes ペアを橙色エッジで重ね描き
python visualize_ergm_network.py --sim-dir /mnt/eightthdd/uspto/similarity_results
```

### オプション一覧

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `--ergm-dir` | `ergm_input` | `build_ergm_input.py` 出力ディレクトリ |
| `--out-dir` | `output` | 出力先ディレクトリ |
| `--sim-dir` | なし | Gemini 類似判定 JSONL ディレクトリ（Yes ペア overlay） |
| `--top-n` | `250` | サブグラフのシードノード数 |
| `--hops` | `1` | シードから BFS 何 hop まで含めるか |
| `--metric` | `degree` | シード抽出メトリクス（`degree` / `betweenness`） |
| `--betweenness-k` | `300` | betweenness 近似 BFS ソース数（N>500 のとき有効） |

---

## レイアウトアルゴリズム

```
Spring layout iterations = max(30, min(100, 10000 // N_sg))
```

ノード数が増えると反復回数を自動削減してパフォーマンスを確保する。

---

## Gemini Yes ペア重ね描き

`--sim-dir` を指定すると `similarity_results/*.jsonl` から `similarity=Yes` のレコードを読み込む。`_patent_attr_cache.pkl` のソート済みキーをインデックスとして、`source`/`target` 特許 ID をノードインデックスに変換する。変換できたペアのみが橙色エッジとして表示される。

---

## 注意事項

- `attributes.txt` のノード行順が `_patent_attr_cache.pkl` のソート済みキー順と対応していることを前提とする
- D-class 集約グラフの PNG 出力には `kaleido` パッケージが必要（`pip install kaleido`）
- `N > 500` の場合は `nx.betweenness_centrality(k=betweenness_k)` による近似を使用するため、実行のたびに値が変わりうる（`seed=42` で固定）

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [ergm_input.md](ergm_input.md) | `visualize_ergm_network.py` | 目視確認・プレゼン資料 |
| `ergm_input/arc_list.txt` 等 | → `output/network_*.html` 等 | — |