# パイプライン全体像

USPTO 意匠特許の引用データから共引用ネットワークを構築し、Gemini による視覚的類似判定を実行するまでの処理フロー。

---

## 全体フロー図

```
【生データ】
  /mnt/eightthdd/uspto/
    json/{year}.json          ← USPTO 引用データ
    data/{year}.csv           ← 意匠特許属性 (ID / title / date / class)
    image_numpy_data_no_text/ ← 特許画像の numpy インデックス

         │
         │ STEP 1
         ▼
  build_edge_list.py
         │
         ▼
  edge_list/{year}.csv
  (共引用エッジリスト)
         │
         ├─── STEP 2a ─────────────────────────────────┐
         │                                              │
         ▼                                              ▼
  extract_cited_image_pairs.py              plot_indegree.py
         │                                              │
         ▼                                              ▼
  cited_image_pairs/{year}.jsonl      indegree_pdf.png
  (画像パス付きペアリスト)            indegree_ccdf.png
         │
         │ STEP 3
         ▼
  judge_cited_pairs.py
    └─ design_similarity.py  (Gemini API)
         │
         ▼
  similarity_results/{year}.jsonl
  (類似判定結果)
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
| 入力 | `/mnt/eightthdd/uspto/image_numpy_data_no_text/` | numpy / txt |
| 出力 | `/mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl` | JSONL |
| キャッシュ | `/mnt/eightthdd/uspto/cited_image_pairs/_image_index.pkl` | pickle |

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

**処理内容**: エッジリストから無向グラフの次数を集計し、P(k)（PDF）と P(K ≥ k)（CCDF）を log-log スケールで描画。べき乗則フィット（OLS）を重ねて表示する。類似判定パイプラインとは独立して実行可能。

---

## STEP 3 — Gemini による類似判定

**スクリプト**: [`judge_cited_pairs.py`](../judge_cited_pairs.py) ／ コアライブラリ: [`design_similarity.py`](../design_similarity.py)  
**詳細**: [judge_cited_pairs.md](judge_cited_pairs.md) ／ [design_similarity.md](design_similarity.md)

| | パス | 形式 |
|---|---|---|
| 入力 | `/mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl` | JSONL |
| 出力 | `/mnt/eightthdd/uspto/similarity_results/{year}.jsonl` | JSONL |
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

**正常時の出力例**:

```json
{
  "source": "D0535736",
  "target": "D0537156",
  "source_images": { "perspective": "/mnt/.../USD0535736-...TIF" },
  "target_images": { "perspective": "/mnt/.../USD0537156-...TIF" },
  "events": [...],
  "image_type_used": "perspective",
  "similarity": "Yes",
  "confidence": 4,
  "reason": "Both designs share an identical overall silhouette and surface ornamentation pattern."
}
```

**判定基準**: 米国・EU 統合基準（先行意匠を認知している注意深い購買者が全体的な視覚的印象を実質的に同一とみなすか）。詳細は [design_similarity.md](design_similarity.md) のデフォルトプロンプト節を参照。

**レート制限**（Google AI Studio 無料ティア）:

| 制限 | 値 | 実質的な律速 |
|------|----|-------------|
| RPM | 15 | 安全マージンで 14 を使用 |
| IPM | 2 | 1 リクエスト = 画像 2 枚 → 実質 1 req/分 |
| RPD | 1,000 | 1日あたり上限 |

---

## ストレージ構成

```
/mnt/eightthdd/uspto/
  json/                        ← 生データ（引用 JSON）
  data/                        ← 生データ（特許属性 CSV）
  image_numpy_data_no_text/    ← 生データ（画像 numpy インデックス）
  edge_list/                   ← STEP 1 出力
  cited_image_pairs/           ← STEP 2a 出力
  similarity_results/          ← STEP 3 出力
```

```
（スクリプトと同ディレクトリ）
  debug/image/                 ← STEP 3 デバッグ画像
  log/error/                   ← STEP 3 エラーログ
  indegree_pdf.png             ← STEP 2b 出力
  indegree_ccdf.png            ← STEP 2b 出力
```

---

## 実行順序

```bash
# STEP 1
python build_edge_list.py

# STEP 2a（STEP 1 完了後）
python extract_cited_image_pairs.py

# STEP 2b（STEP 1 完了後、任意）
python plot_indegree.py

# STEP 3（STEP 2a 完了後）
python judge_cited_pairs.py
```

各スクリプトは年単位で指定年のみ処理することも可能。詳細は各 .md ファイルの「実行方法」節を参照。
