# パイプライン全体像

USPTO 意匠特許の引用データから共引用ネットワークを構築し、Gemini による視覚的類似判定を実行するまでの処理フロー。

---

## スクリプト一覧

| スクリプト | 役割 |
|-----------|------|
| `build_edge_list.py` | 共引用エッジリスト構築（STEP 1） |
| `extract_cited_image_pairs.py` | 画像ペア抽出（STEP 2a） |
| `plot_indegree.py` | 次数分布可視化（STEP 2b、分析用） |
| `add_class_to_edge_list.py` | 意匠分類の付与（STEP 2c、分析用） |
| `build_ergm_input.py` | ERGM 分析用入力ファイル生成（STEP 2d、分析用） |
| `judge_cited_pairs.py` | Gemini 類似判定（STEP 3） |
| `extract_yes_pairs.py` | Yes 判定ペアの抽出・可視化（STEP 4） |
| `analyze_ergm.py` | ERGM 記述統計・Gemini 統合分析（STEP 5、分析用） |
| `visualize_ergm_network.py` | 共引用ネットワーク可視化（STEP 6、分析用） |
| `design_similarity.py` | Gemini 判定クライアント（ライブラリ／CLI） |
| `image_processor.py` | 画像前処理（ライブラリ／CLI） |
| `image_index.py` | 特許 ID → 画像パス インデックス（ライブラリ／CLI） |

---

## 全体フロー図

```
【生データ】
  /mnt/eightthdd/uspto/
    json/{year}.json          ← USPTO 引用データ
    data/{year}.csv           ← 意匠特許属性 (ID / title / date / class / file_names / fig_desc)
  /mnt/eightthdd/impact/images/{year}/  ← 特許画像ファイル (TIF)

         │
         │ STEP 1
         ▼
  build_edge_list.py
         │
         ▼
  edge_list/{year}.csv
  (共引用エッジリスト)
         │
         ├─── STEP 2a ─────────────────────────────────────────────┐
         │                                                       │
         ├─── STEP 2b (任意) ─────────────────────────────┐      │
         │                                                │      │
         ├─── STEP 2c (任意) ────────────────────┐        │      │
         │                                       │        │      │
         └─── STEP 2d (任意) ──────┐              │        │      │
                                   │              │        │      │
                    build_ergm_    │  add_class_  │  plot_ │  extract_cited_
                    input.py       │  to_edge_    │  indeg │  image_pairs.py
                  (data/*.csv も   │  list.py     │  ree.py│
                   参照)           │              │        │
                                   ▼              ▼        ▼      │
                    ergm_input/       edge_list_     indeg  │      │
                      arc_list.txt    with_class/    ree_*  │      │
                      attributes.txt  {year}.csv   (png ×2) │      ▼
                      *.npz                                  │  cited_image_pairs/
                      model.cfg                              │  {year}.jsonl
                                                        │      │
                                                        │      │ STEP 3
                                                        │      ▼
                                                        │  judge_cited_pairs.py
                                                        │    └─ design_similarity.py
                                                        │         └─ image_processor.py
                                                        │      │
                                                        │      ▼
                                                        │  qwen_similarity_results/{year}.jsonl
                                                        │  debug/image/*.png
                                                        │      │
                                                        │      │ STEP 4
                                                        │      ▼
                                                        │  extract_yes_pairs.py
                                                        │    └─ image_processor.py
                                                        │      │
                                                        └──────┤ (data/*.csv も参照)
                                                               │
                                                               ▼
                                                          yes_pair/qwen_yes_pairs/{year}.jsonl
                                                          yes_pair/qwen_yes_image_pair/
```

---

## STEP 1 — 共引用エッジリスト構築

**スクリプト**: [`build_edge_list.py`](../build_edge_list.py)  
**詳細**: [citation_graph.md](citation_graph.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/json/{year}.json` | JSON |
| 入力 | `/mnt/eightthdd/uspto/data/{year}.csv` | CSV |
| 出力 | `/mnt/eightthdd/uspto/edge_list/{year}.csv` | CSV |

**処理内容**: 同一の出願審査 (`patentApplicationNumber`) で共に引用された 2 つの意匠特許にエッジを張る。`source < target` でアルファベット順に正規化。

**出力スキーマ（CSV カラム）**:

| カラム | 内容 |
|--------|------|
| `source` | 意匠 ID (D0XXXXXX) |
| `target` | 意匠 ID (D0XXXXXX) |
| `patentApplicationNumber` | 両特許を共引用した出願番号 |
| `officeActionDate` | OA 日付 |
| `officeActionCategory` | OA 種別 (CTNF / CTFR 等) |
| `citationCategoryCode` | 引用カテゴリ (A / X / Y 等) |
| `examinerCitedReferenceIndicator` | 審査官引用フラグ |
| `applicantCitedExaminerReferenceIndicator` | 出願人引用フラグ |
| `workGroup` / `groupArtUnitNumber` / `techCenter` | 審査部門情報 |

**規模（2007–2010）**:

| 年 | エッジ数 |
|---:|--------:|
| 2007 | 9,645 |
| 2008 | 11,233 |
| 2009 | 13,504 |
| 2010 | 10,151 |

---

## STEP 2a — 画像ペア抽出

**スクリプト**: [`extract_cited_image_pairs.py`](../extract_cited_image_pairs.py)  
**詳細**: [image_pairs.md](image_pairs.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/edge_list/{year}.csv` | CSV |
| 入力 | `/mnt/eightthdd/uspto/data/{year}.csv` | CSV（`image_index.py` 経由） |
| 出力 | `/mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl` | JSONL |
| キャッシュ | `/mnt/eightthdd/uspto/_image_index.pkl` | pickle |

**処理内容**: エッジリストの各ペアに対し、source・target 双方が共通して持つ図タイプ（`front` / `overview` / `perspective`）の画像パスを付与する。共通図タイプがないペアはスキップ。同一ペアを繋ぐ複数の出願イベントは `events` 配列に集約する。

**出力スキーマ（1行 = 1ペア）**:

```json
{
  "source": "D0535736",
  "target": "D0537156",
  "source_images": { "perspective": "/mnt/.../USD0535736-20070123-D00000.TIF" },
  "target_images": { "perspective": "/mnt/.../USD0537156-20070220-D00000.TIF" },
  "events": [
    {
      "patentApplicationNumber": "29701893",
      "officeActionDate": "2020-10-06T00:00:00",
      "officeActionCategory": "CTNF",
      "citationCategoryCode": "A",
      "examinerCitedReferenceIndicator": "True",
      "applicantCitedExaminerReferenceIndicator": "False",
      "workGroup": "2900-WG",
      "groupArtUnitNumber": "2914",
      "techCenter": "2900"
    }
  ]
}
```

**規模（2007–2010）**:

| 年 | ペア数 |
|---:|------:|
| 2007 | 5,859 |
| 2008 | 6,786 |
| 2009 | 7,630 |
| 2010 | 5,191 |

---

## STEP 2b — 次数分布可視化（分析用サイドブランチ）

**スクリプト**: [`plot_indegree.py`](../plot_indegree.py)  
**詳細**: [degree_distribution.md](degree_distribution.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/edge_list/{year}.csv` | CSV |
| 出力 | `indegree_pdf.png` | PNG |
| 出力 | `indegree_ccdf.png` | PNG |

**処理内容**: エッジリストから無向グラフの次数を集計し、P(k)（PDF）と P(K ≥ k)（CCDF）を log-log スケールで描画。べき乗則フィット（OLS）を重ねて表示する。STEP 1 の出力のみに依存し、STEP 2a・3・4 とは独立して実行可能。

---

## STEP 2c — 意匠分類の付与（分析用サイドブランチ）

**スクリプト**: [`add_class_to_edge_list.py`](../add_class_to_edge_list.py)  
**詳細**: [edge_list_with_class.md](edge_list_with_class.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/edge_list/{year}.csv` | CSV |
| 入力 | `/mnt/eightthdd/uspto/data/{year}.csv` | CSV |
| 出力 | `/mnt/eightthdd/uspto/edge_list_with_class/{year}.csv` | CSV |
| キャッシュ | `/mnt/eightthdd/uspto/edge_list_with_class/_class_index.pkl` | pickle |

**処理内容**: `data/*.csv` から `patent_id → 意匠分類` の dict を構築（pickle キャッシュ）し、エッジリストの各行に `source_class`, `source_class_name`, `target_class`, `target_class_name` の 4 列を付与する。STEP 1 の出力のみに依存し、STEP 2a・3・4 とは独立して実行可能。

**追加カラム**:

| カラム | 例 | 内容 |
|--------|-----|------|
| `source_class` | `D14` | source のメイン意匠分類コード |
| `source_class_name` | `Recording/Communication/Info` | source の分類名 |
| `target_class` | `D23` | target のメイン意匠分類コード |
| `target_class_name` | `Environmental Heating/Cooling` | target の分類名 |

---

## STEP 2d — ERGM 分析用入力ファイル生成（分析用サイドブランチ）

**スクリプト**: [`build_ergm_input.py`](../build_ergm_input.py)  
**詳細**: [ergm_input.md](ergm_input.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/edge_list/{year}.csv` | CSV |
| 入力 | `/mnt/eightthdd/uspto/data/{year}.csv` | CSV |
| 出力 | `ergm_input/arc_list.txt` | テキスト |
| 出力 | `ergm_input/attributes.txt` | タブ区切り CSV |
| 出力 | `ergm_input/class_sim_binary.npy` | 密行列 bool |
| 出力 | `ergm_input/class_sim_jaccard.npy` | 密行列 float32 |
| 出力 | `ergm_input/model.cfg` | EstimNetDirected 設定ひな型 |
| キャッシュ | `ergm_input/_patent_attr_cache.pkl` | pickle |

**処理内容**: 意匠分類（D1–D99）をノード属性として付与し、EstimNetDirected による ERGM 推定の入力ファイルを生成する。D-class ごとのバイナリフラグ（35 変数）・多様性スコア・Jaccard 類似度行列を含む。STEP 1 の出力のみに依存し、STEP 2a・3・4 とは独立して実行可能。

**STEP 2c との違い**:

| | STEP 2c (`add_class_to_edge_list.py`) | STEP 2d (`build_ergm_input.py`) |
|-|---------------------------------------|----------------------------------|
| 対象単位 | エッジ（行ごとにクラスを付与） | ノード（ノード属性として付与） |
| クラス取得 | メインクラス 1件のみ | 全クラスをセットとして取得 |
| 出力用途 | クラス別エッジ集計・可視化 | EstimNetDirected ERGM 推定 |
| 類似度行列 | なし | Jaccard / バイナリの npz |

---

## STEP 3 — Gemini による類似判定

**スクリプト**: [`judge_cited_pairs.py`](../judge_cited_pairs.py) ／ コアライブラリ: [`design_similarity.py`](../design_similarity.py)  
**詳細**: [judge_cited_pairs.md](judge_cited_pairs.md) ／ [design_similarity.md](design_similarity.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl` | JSONL |
| 出力 | `/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` | JSONL |
| デバッグ画像 | `debug/image/{source}__{target}__{type}.png` | PNG |
| エラーログ | `log/error/error_YYYYMMDD.log` | テキスト |

**処理内容**: 入力レコードの全フィールドを引き継ぎ、判定結果フィールドを追記して出力する。中断後は `--resume`（デフォルト有効）で続きから再開できる。

**図タイプ選択優先順**: `front` > `overview` > `perspective`（`--type` で固定可）

**出力スキーマ（入力フィールドに追加されるフィールド）**:

| フィールド | 内容 |
|-----------|------|
| `image_type_used` | 判定に使用した図タイプ |
| `similarity` | `"Yes"` または `"No"` |
| `confidence` | 確信度 1〜5（5 が最も確実） |
| `reason` | 判断理由（英語 1〜2 文） |
| `error` | エラー発生時のみ（`similarity` 等は付与されない） |

**判定基準**: 米国・EU 統合基準（先行意匠を認知している注意深い購買者が全体的な視覚的印象を実質的に同一とみなすか）。詳細は [design_similarity.md](design_similarity.md) のデフォルトプロンプト節を参照。

**レート制限**（Google AI Studio 無料ティア）:

| 制限 | 値 | 実質的な律速 |
|------|----|-------------|
| RPM | 15 | 安全マージンで 14 を使用 |
| IPM | 2 | 1 リクエスト = 画像 2 枚 → 実質 1 req/分 |
| RPD | 500 | 1日あたり上限 |

---

## STEP 5 — ERGM 記述統計・Gemini 統合分析（分析用サイドブランチ）

**スクリプト**: [`analyze_ergm.py`](../analyze_ergm.py)  
**詳細**: [ergm_input.md](ergm_input.md#分析スクリプト-analyze_ergmpy)

| | パス | 形式 |
|---|---|---|
| 入力 | `ergm_input/arc_list.txt` | テキスト |
| 入力 | `ergm_input/attributes.txt` | タブ区切り CSV |
| 入力 | `ergm_input/class_sim_jaccard.npy` | 密行列 float32 |
| 入力 | `ergm_input/_patent_attr_cache.pkl` | pickle（P4 クラス照合に使用） |
| 入力 | `/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` | JSONL（P4 のみ） |
| 入力 | `ergm_input/*theta*.csv` | CSV（P3、EstimNetDirected 実行後） |
| 出力 | `output/priority1_*.png` | クラス分布・ヒートマップ |
| 出力 | `output/priority2_*.png` / `.csv` | 記述統計・次数分布 |
| 出力 | `output/priority3_ergm_coefs.png` | ERGM 係数フォレストプロット |
| 出力 | `output/priority4_*.png` | Gemini 突合グラフ |
| 出力 | `output/analysis_summary.csv` | 数値サマリ |

**処理内容**: `build_ergm_input.py` の出力（STEP 2d）と `judge_cited_pairs.py` の出力（STEP 3）を統合し、クラス分布・次数分布・ERGM 係数・Gemini 類似判定のクロス集計を一括実行する。`--skip-p3` / `--skip-p4` で EstimNetDirected 実行前でも部分実行可能。

```bash
# 基本実行（優先度1–4 すべて）
python analyze_ergm.py

# EstimNetDirected 実行前（優先度3はスキップ）
python analyze_ergm.py --skip-p3

# Gemini 結果なし（優先度4はスキップ）
python analyze_ergm.py --skip-p4
```

---

## STEP 6 — 共引用ネットワーク可視化（分析用サイドブランチ）

**スクリプト**: [`visualize_ergm_network.py`](../visualize_ergm_network.py)  
**詳細**: [visualize_ergm_network.md](visualize_ergm_network.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `ergm_input/arc_list.txt` | テキスト |
| 入力 | `ergm_input/attributes.txt` | タブ区切り CSV |
| 入力 | `ergm_input/_patent_attr_cache.pkl` | pickle（任意） |
| 入力 | `/mnt/eightthdd/uspto/yes_pair/qwen/*.jsonl` | JSONL（`--sim-dir` 時のみ） |
| 出力 | `output/fig1_network_topology.png` | 300 DPI PNG（Eq.9/10 ネットワーク構造） |
| 出力 | `output/fig2_ergm_statistics.png` | 300 DPI PNG（Eq.1-8 ERGM 統計量） |
| 出力 | `output/fig3_degree_distribution.png` | 300 DPI PNG（Eq.10/11 次数・betweenness） |
| 出力 | `output/fig4_homophily_heatmap.png` | 300 DPI PNG（Eq.6 35×35 行列） |
| 出力 | `output/fig5_sender_receiver.png` | 300 DPI PNG（Eq.4/5 per-class） |
| 出力 | `output/fig6_gw_statistics.png` | 300 DPI PNG（GW 統計量） |
| 出力 | `output/fig7_date_guard.png` | 300 DPI PNG（Eq.7/8 時間バイアス） |
| 出力 | `output/ergm_statistics.csv` | 全統計量 CSV |

**処理内容**: Chakraborty et al. (2020) の全方程式（Eq.1-11）および GW 統計量（GWIDegree・GWESP・GWDSP）を実装し、7 枚の論文品質 PNG を生成する。ノード色は D-class（35 色）、サイズは degree、エッジ太さはクラス間共引用本数。STEP 2d の出力のみに依存し、独立して実行可能。

```bash
# デフォルト（degree 上位 250 件 + 1-hop）
python visualize_ergm_network.py

# Yes ペアを重ね描き
python visualize_ergm_network.py --sim-dir /mnt/eightthdd/uspto/yes_pair/qwen
```

---

## STEP 4 — Yes 判定ペアの抽出・可視化

**スクリプト**: [`extract_yes_pairs.py`](../extract_yes_pairs.py)  
**詳細**: [extract_yes_pairs.md](extract_yes_pairs.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/qwen_similarity_results/*.jsonl` | JSONL |
| 入力 | `/mnt/eightthdd/uspto/data/*.csv` | CSV |
| 出力 | `/mnt/eightthdd/uspto/yes_pair/qwen_yes_pairs/{year}.jsonl` | JSONL |
| 出力 | `/mnt/eightthdd/uspto/yes_pair/qwen_yes_image_pair/` | PNG |
| キャッシュ | `/mnt/eightthdd/uspto/yes_pair/_patent_index.pkl` | pickle |

**処理内容**: `similarity=Yes` のレコードを全 JSONL から抽出し、JSON ファイルと横並び画像（タイトル・分類・confidence・reason 付き）を出力する。目視確認・レビュー用の最終出力。

---

## ライブラリモジュール（パイプラインステップではない）

### `design_similarity.py`

Gemini API クライアント。`judge_cited_pairs.py` から `import` して使用する。
CLI として 2 枚の画像を直接渡して単体判定することも可能。

```bash
python design_similarity.py image1.tif image2.tif
python design_similarity.py image1.tif image2.tif --json
```

### `image_processor.py`

画像前処理（白余白除去・長辺 768px リサイズ）。`design_similarity.py`・`judge_cited_pairs.py`・`extract_yes_pairs.py` から `import` して使用する。
CLI として単体ファイルの前処理・保存も可能。

```bash
python image_processor.py src.tif dst.png
```

---

## ストレージ構成

```
/mnt/eightthdd/uspto/
  json/                           ← 生データ（引用 JSON）
  data/                           ← 生データ（特許属性 CSV・画像インデックスの正規ソース）
  _image_index.pkl                ← image_index.py キャッシュ（data/ から構築）
  edge_list/                      ← STEP 1 出力
  cited_image_pairs/              ← STEP 2a 出力
  edge_list_with_class/           ← STEP 2c 出力
  qwen_similarity_results/        ← STEP 3 出力（BACKEND="qwen" 時）
  similarity_results/             ← STEP 3 出力（BACKEND="gemini" 時）
  yes_pair/
    qwen_yes_pairs/               ← STEP 4 出力（年別 JSONL）
    qwen_yes_image_pair/          ← STEP 4 出力（横並び画像）
    _patent_index.pkl             ← STEP 4 キャッシュ
/mnt/eightthdd/impact/images/     ← 生データ（特許画像 TIF、2007〜2022）
```

```
（スクリプトと同ディレクトリ）
  ergm_input/                  ← STEP 2d 出力
  output/                      ← STEP 5 出力（分析グラフ・CSV）
  debug/image/                 ← STEP 3 デバッグ画像
  log/error/                   ← STEP 3 エラーログ
  indegree_pdf.png             ← STEP 2b 出力
  indegree_ccdf.png            ← STEP 2b 出力
```

---

## 実行順序

```bash
# 【前提】画像インデックスの初期構築（初回のみ、または data/*.csv 更新時）
# STEP 2a を初めて実行するとき自動構築されるが、事前に確認したい場合は明示実行する
python image_index.py           # 初回構築
python image_index.py --rebuild # data/*.csv 更新後の再構築

# STEP 1（必須）
python build_edge_list.py

# STEP 2a（STEP 1 完了後、必須）
python extract_cited_image_pairs.py

# STEP 2b（STEP 1 完了後、任意）
python plot_indegree.py

# STEP 2c（STEP 1 完了後、任意）
python add_class_to_edge_list.py

# STEP 2d（STEP 1 完了後、任意）
python build_ergm_input.py

# STEP 3（STEP 2a 完了後、必須）
python judge_cited_pairs.py

# STEP 4（STEP 3 完了後）
python extract_yes_pairs.py

# STEP 5（STEP 2d 完了後、STEP 3 完了後に全分析）
python analyze_ergm.py          # 全分析（STEP 3 未完了なら --skip-p3）

# STEP 6（STEP 2d 完了後、任意）
python visualize_ergm_network.py                                               # デフォルト
python visualize_ergm_network.py --sim-dir /mnt/eightthdd/uspto/yes_pair/qwen  # Yes ペア重ね描き
```

各スクリプトは年単位で指定年のみ処理することも可能（`extract_yes_pairs.py` を除く）。詳細は各 .md ファイルの「実行方法」節を参照。