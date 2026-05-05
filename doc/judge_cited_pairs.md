# 類似判定バッチ処理 (`judge_cited_pairs.py`)

共引用画像ペアに対して Gemini で意匠類似判定を実行し、結果を JSONL に追記する。

---

## 処理フロー

```
cited_image_pairs/{year}.jsonl
        │
        │  1行ずつ読み込み
        ▼
pick_common_type()  ─── 共通図タイプを選択（front > overview > perspective）
        │
        ▼
judge_similarity()  ─── Gemini 2.5 Flash-Lite で類似判定
        │
        ├─ DEBUG=True ─→ save_debug_image()  ─→ debug/image/{source}__{target}__{type}.png
        │
        ▼
similarity_results/{year}.jsonl  ─── 元レコード + 判定結果を追記
```

---

## 入出力

| 項目 | パス |
|------|------|
| 入力 | `/mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl` |
| 出力 | `/mnt/eightthdd/uspto/similarity_results/{year}.jsonl` |
| デバッグ画像 | `debug/image/{source}__{target}__{type}.png` |

---

## 出力フォーマット（JSONL）

入力レコード（`cited_image_pairs/{year}.jsonl`）の全フィールドをそのまま引き継ぎ、判定結果フィールドを追加して出力する。

### 完全なレコード例

```json
{
  "source": "D0535736",
  "target": "D0537156",
  "source_images": {
    "perspective": "/mnt/eightthdd/impact/images/2007/USD0535736-20070123-D00000.TIF"
  },
  "target_images": {
    "perspective": "/mnt/eightthdd/impact/images/2007/USD0537156-20070220-D00000.TIF"
  },
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
  ],
  "image_type_used": "perspective",
  "similarity": "No",
  "confidence": 5,
  "reason": "The overall shapes are markedly different, with Image A resembling an open, U-shaped bracket and Image B a tall, slender casing."
}
```

### フィールド一覧

#### 入力から引き継ぐフィールド

| フィールド | 型 | 内容 |
|-----------|-----|------|
| `source` | string | source 意匠の ID（例: `"D0535736"`） |
| `target` | string | target 意匠の ID（`source < target` でアルファベット順に正規化済み） |
| `source_images` | object | source が持つ図タイプ → 画像パスの対応表（例: `{"front": "...", "perspective": "..."}` ） |
| `target_images` | object | target が持つ図タイプ → 画像パスの対応表 |
| `events` | array | このペアを共引用した出願のレコード一覧（詳細は下表） |

`source_images` / `target_images` のキーは `front` / `overview` / `perspective` の組み合わせ。各特許が持つタイプのみ含まれる（全タイプを必ず持つとは限らない）。

**`events` の各要素**

| フィールド | 内容 |
|-----------|------|
| `patentApplicationNumber` | 出願番号 |
| `officeActionDate` | 拒絶理由通知日（ISO 8601 形式） |
| `officeActionCategory` | 通知カテゴリ（例: `CTNF` = Non-Final Rejection） |
| `citationCategoryCode` | 引用カテゴリコード（例: `A` = 先行技術） |
| `examinerCitedReferenceIndicator` | 審査官による引用か (`"True"` / `"False"`) |
| `applicantCitedExaminerReferenceIndicator` | 出願人が審査官引用を引用したか (`"True"` / `"False"`) |
| `workGroup` | ワークグループ |
| `groupArtUnitNumber` | アートユニット番号 |
| `techCenter` | テクノロジーセンター番号 |

#### 本スクリプトが追加するフィールド

| フィールド | 型 | 内容 |
|-----------|-----|------|
| `image_type_used` | string | 実際の比較に使用した図タイプ（`"front"` / `"overview"` / `"perspective"`）。`source_images` と `target_images` の**両方に存在する共通タイプ**の中から `front > overview > perspective` の優先順で選択される。 |
| `similarity` | string | 類似判定結果（`"Yes"` / `"No"`） |
| `confidence` | integer | 確信度（1〜5、5 が最も確実） |
| `reason` | string | 判断理由（英語 1〜2 文） |
| `error` | string | エラー発生時のみ付与。このフィールドが存在する場合、`image_type_used` / `similarity` / `confidence` / `reason` は付与されない。 |

---

## 主要関数

| 関数 | 役割 |
|------|------|
| `pick_common_type(record, prefer)` | source・target に共通する図タイプを選択。`prefer` で優先タイプを指定可能。 |
| `save_debug_image(...)` | 2枚の画像を左右並べた PNG を `debug/image/` に保存。判定結果も描画。 |
| `process_year(year, img_type, resume)` | 1年分の JSONL を1行ずつ処理し結果を出力。 |

---

## デバッグモード

スクリプト冒頭の定数を切り替えるだけで有効になる。

```python
DEBUG = True   # debug/image/ に画像ペアを PNG で保存する
DEBUG = False  # 通常モード（デフォルト）
```

**デバッグ画像の内容:**

```
┌─────────────────────────────────────────┐
│ D0535736              D0537156          │
│  ┌───────────┐  │  ┌───────────┐       │
│  │  source   │  │  │  target   │       │
│  │  image    │  │  │  image    │       │
│  └───────────┘  │  └───────────┘       │
│ Yes  confidence=4  Both designs share...│
└─────────────────────────────────────────┘
```

- 高さ 400px に揃えてリサイズ
- 下部テキストの色: Yes=緑 / No=赤
- 判定前エラー時は画像のみ（テキストなし）で保存

---

## 実行方法

```bash
# 全年処理（2007〜2010）
python judge_cited_pairs.py

# 指定年のみ
python judge_cited_pairs.py 2007 2008

# 図タイプを固定して処理
python judge_cited_pairs.py --type perspective

# 最初から処理し直す
python judge_cited_pairs.py 2007 --no-resume
```

### 再開（resume）

デフォルトで有効。出力 JSONL に書き込み済みのペア (`source`, `target`) はスキップされる。
中断後に同じコマンドを再実行するだけで続きから再開できる。

---

## 注意事項

- TIF 画像は Gemini 非対応のため `design_similarity.load_image_part()` 内で PNG に変換して送信する
- レート制限 (15 RPM / 2 IPM / 1,000 RPD) は `design_similarity.RateLimiter` が自動管理する
- 出力は1件ごとに `flush()` されるため、途中終了してもデータは失われない

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [image_pairs.md](image_pairs.md) | `judge_cited_pairs.py` | — |
| `cited_image_pairs/{year}.jsonl` | → `similarity_results/{year}.jsonl` | 分析・可視化 |
