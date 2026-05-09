# ネットワーク可視化スクリプト (`visualize_ergm_network.py`)

`build_ergm_input.py` の出力をもとに、意匠特許共引用ネットワークを論文品質 PNG として可視化する。

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
        ▼
build_nx_graph()  ─── NetworkX グラフ構築（ノード属性: primary_class, date, patent_id）
        │
        ▼
compute_node_metrics()  ─── degree + betweenness（N>500 は k-sample 近似）
        │
        ├── extract_focus_subgraph()  ─── 上位 top_n + BFS hops のサブグラフ
        │         │
        │         ▼  plot_patent_network()
        │         output/network_patent_graph.png
        │         （yes_pairs 指定時は Gemini Yes エッジを橙色で重ね描き）
        │
        ├── build_class_graph()  ─── D-class 単位に集約
        │         │
        │         ▼  plot_class_network()
        │         output/network_class_graph.png
        │
        ├── plot_degree_distribution()
        │         output/network_degree_dist.png
        │
        └── save_summary()
                  output/network_summary.csv
```

---

## 入出力

| 項目 | パス | 形式 |
|------|------|------|
| 入力 | `ergm_input/arc_list.txt` | テキスト（`u v` の行列） |
| 入力 | `ergm_input/attributes.txt` | タブ区切り CSV |
| 入力 | `ergm_input/_patent_attr_cache.pkl` | pickle（任意・patent_id マッピング用） |
| 入力 | `similarity_results/*.jsonl` | JSONL（`--sim-dir` 指定時のみ） |
| 出力 | `output/network_patent_graph.png` | 300 DPI PNG |
| 出力 | `output/network_class_graph.png` | 300 DPI PNG |
| 出力 | `output/network_degree_dist.png` | 300 DPI PNG |
| 出力 | `output/network_summary.csv` | グラフ要約統計 |

---

## 出力詳細

### `network_patent_graph.png` — 特許レベルの共引用ネットワーク（サブグラフ）

| 視覚要素 | 対応するデータ特徴 | エンコード方法 |
|---------|-----------------|--------------|
| ノード色 | primary D-class（カテゴリ） | tab20 + tab20b 由来の 35 色 |
| ノードサイズ | degree または betweenness（連続） | log1p スケールで 15〜450 pt² に正規化 |
| エッジ色（グレー） | 共引用関係（通常） | 固定色・透明度 0.22 |
| エッジ色（橙） | Gemini 類似 Yes ペア（`--sim-dir` 指定時） | `#ff7f0e`・透明度 0.72 |

凡例 3 種を付与:
- **Design Class**: D-class 別カラーパッチ（件数降順、最大 20 件）
- **Node size**: 参照 degree 値と対応するサイズ（散布プロキシ）
- **Visually similar**: Gemini Yes エッジ（`--sim-dir` 指定時のみ）

### `network_class_graph.png` — D-class 集約ネットワーク

| 視覚要素 | 対応するデータ特徴 | エンコード方法 |
|---------|-----------------|--------------|
| ノードサイズ | 特許件数 | log1p スケールで 200〜3500 pt² に正規化 |
| ノード色 | D-class（カテゴリ） | 特許グラフと共通パレット |
| エッジ太さ | クラス間共引用本数 | log1p スケールで 0.3〜6.0 pt に正規化 |
| エッジ濃度（alpha） | クラス間共引用本数 | 0.20〜0.85 で連続変化 |
| ラベル | D-class コード | ノード直上にオフセット配置 |

凡例 2 種を付与:
- **Node size**: 参照件数と対応するサイズ
- **Edge width**: 参照共引用本数と対応するエッジ太さ

### `network_degree_dist.png` — 次数分布（log-log）

| 要素 | 内容 |
|------|------|
| 散布点 | 各 degree $k$ の確率 $P(k)$ |
| 破線 | べき乗則フィット（tail: $k \geq \langle k \rangle$）、指数 $\gamma$ を表示 |
| 点線 | 平均次数 $\langle k \rangle$ |

### `network_summary.csv`

出力指標: `full_nodes`, `full_edges`, `focus_nodes`, `focus_edges`, `class_nodes`, `class_edges`, `full_mean_degree`, `full_density`, `focus_density`, `focus_transitivity`

---

## 主要関数

| 関数 | 役割 |
|------|------|
| `load_arc_list(arc_path)` | `arc_list.txt` を `(u, v)` タプルのリストとして読み込む |
| `arcs_to_undirected_edges(arcs)` | 双方向アーク → 無向エッジリスト（重複除去） |
| `build_nx_graph(n_nodes, edges, attrs, patent_cache_keys)` | NetworkX グラフを構築しノード属性を付与 |
| `compute_node_metrics(G, betweenness_k, seed)` | degree と betweenness を計算してノード属性に追加 |
| `extract_focus_subgraph(G, top_n, hops, metric)` | 指定メトリクス上位 `top_n` + BFS `hops` hop のサブグラフを抽出 |
| `load_gemini_yes_pairs(sim_dir, patent_cache_keys)` | similarity_results から Yes ペアを `(i, j)` の集合として返す |
| `build_class_graph(G)` | 特許グラフを D-class 単位に集約した `nx.Graph` を返す |
| `_log_scale(values, v_min, v_max)` | 配列を log1p スケールで `[v_min, v_max]` に正規化 |
| `_ref_val(x, all_vals, v_min, v_max)` | `_log_scale` と同じ変換を単一参照値に適用（凡例サイズ計算用） |
| `plot_patent_network(SG, out_path, yes_pairs, metric)` | 特許グラフ PNG を生成（凡例: D-class / サイズ / Gemini Yes） |
| `plot_class_network(H, out_path)` | D-class グラフ PNG を生成（凡例: ノードサイズ / エッジ太さ） |
| `plot_degree_distribution(G, out_path)` | 次数分布 log-log PNG を生成（凡例: P(k) / べき乗則 / 平均次数） |
| `save_summary(G, SG, H, out_csv)` | グラフ要約統計を CSV に保存 |

---

## 実行方法

```bash
# デフォルト（degree 上位 250 件 + 1-hop）
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
| `--betweenness-k` | `300` | betweenness 近似 BFS ソース数（N > 500 のとき有効） |

---

## 図品質仕様

| 項目 | 設定値 |
|------|--------|
| 出力 DPI | 300（`savefig.dpi`） |
| フォント | Helvetica / Arial / DejaVu Sans |
| カラーパレット | tab20 (20色) + tab20b[:15] (15色) = 35色 |
| レイアウト（特許グラフ） | Spring layout（`seed=42`, iter = max(30, min(100, 10000//N))） |
| レイアウト（クラスグラフ） | Spring layout with edge weights（`seed=42`, iter=300） |
| レイアウト（次数分布） | log-log 散布図 + power-law fit line |

---

## 注意事項

- `attributes.txt` のノード行順が `_patent_attr_cache.pkl` のソート済みキー順と対応していることを前提とする
- `N > 500` の場合は `nx.betweenness_centrality(k=betweenness_k)` による近似を使用するため、実行のたびに値が変わりうる（`seed=42` で固定）
- HTML 出力は生成しない（すべて PNG のみ）

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [ergm_input.md](ergm_input.md) | `visualize_ergm_network.py` | 論文・プレゼン資料への組み込み |
| `ergm_input/arc_list.txt` 等 | → `output/network_*.png` | — |