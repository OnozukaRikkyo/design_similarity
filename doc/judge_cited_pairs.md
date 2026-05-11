# 類似判定バッチ処理 (`judge_cited_pairs.py`)

共引用画像ペアに対して意匠類似判定を実行し、結果を JSONL に追記する。推論バックエンドは `design_similarity.py` 先頭の `BACKEND` 変数で切り替える。

---

## スクリプト

```
/home/sonozuka/design_similarity/judge_cited_pairs.py
```

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
judge_similarity()  ─── design_similarity.BACKEND に従って推論
        │  ├─ "gemini" → Gemini 2.5 Flash (Cloud API)
        │  └─ "qwen"   → Qwen-VL (ローカル GPU)
        │
        │  ├─ 429/503 エラー → 指数的待機でリトライ（最大4回）
        │  └─ 成功 → time.sleep(5)
        │
        ├─ DEBUG=True ─→ save_debug_image()  ─→ debug/image/{source}__{target}__{type}.png
        │
        ▼
{出力ディレクトリ}/{year}.jsonl  ─── 元レコード + 判定結果をフラッシュ書き込み
```

---

## 入出力

| 項目 | パス | 形式 |
|------|------|------|
| 入力 | `/mnt/eightthdd/uspto/cited_image_pairs/{year}.jsonl` | JSONL |
| 出力 (`gemini`) | `/mnt/eightthdd/uspto/similarity_results/{year}.jsonl` | JSONL |
| 出力 (`qwen`) | `/mnt/eightthdd/uspto/qwen_similarity_results/{year}.jsonl` | JSONL |
| デバッグ画像 | `debug/image/{source}__{target}__{type}.png` | PNG |

出力ディレクトリは起動時に `design_similarity.BACKEND` を読んで自動決定される。

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
| `image_type_used` | string | 実際の比較に使用した図タイプ（`"front"` / `"overview"` / `"perspective"`）。source・target 両方に存在する共通タイプの中から `front > overview > perspective` の優先順で選択される。 |
| `similarity` | string | 類似判定結果（`"Yes"` / `"No"`） |
| `confidence` | integer | 確信度（1〜5、5 が最も確実） |
| `reason` | string | 判断理由（英語 1〜2 文） |
| `error` | string | エラー発生時のみ付与。このフィールドが存在する場合、`image_type_used` / `similarity` / `confidence` / `reason` は付与されない。 |

---

## 主要関数

| 関数 | 役割 |
|------|------|
| `pick_common_type(record, prefer)` | source・target に共通する図タイプを選択。`prefer` で優先タイプを指定可能。 |
| `save_debug_image(...)` | 2枚の画像を左右並べた PNG を `debug/image/` に保存。判定結果（similarity・confidence・reason）を画像下部に描画。 |
| `process_year(year, img_type, resume)` | 1年分の JSONL を1行ずつ処理し結果を出力。 |
| `reannotate_debug(year)` | 新規判定は行わず、既存の `similarity_results/{year}.jsonl` から debug 画像を confidence/reason 付きで再生成する。 |

---

## デバッグモード

スクリプト冒頭の定数で制御する。

```python
DEBUG = True   # debug/image/ に画像ペアを PNG で保存する（デフォルト）
DEBUG = False  # 通常モード
```

**デバッグ画像のレイアウト:**

```
┌──────────────────────────────────────────────────┐
│ D0535736                    D0537156             │
│  ┌──────────────┐  │  ┌──────────────┐          │
│  │   source     │  │  │   target     │          │
│  │   image      │  │  │   image      │          │
│  │  (400px 高)  │  │  │  (400px 高)  │          │
│  └──────────────┘  │  └──────────────┘          │
│ similarity: No  confidence: 5                    │  ← 太字・判定色（Yes=緑 / No=赤）
│ The overall shapes are markedly different...     │  ← reason（折り返し）
└──────────────────────────────────────────────────┘
```

---

## エラーハンドリングとリトライ

`judge_similarity()` 呼び出しが失敗した場合、エラー種別に応じて待機してリトライする。

| エラー | 待機時間 | 最大リトライ | 超過時の挙動 |
|--------|---------|------------|------------|
| 429 RESOURCE_EXHAUSTED | `(base * (attempt+1)) * 10` 秒<br>（`base` はエラーメッセージ内 `retry in Xs` から抽出、なければ 305 秒） | 4 回 | `sys.exit(1)` |
| 503 UNAVAILABLE | `300 * (attempt+1)` 秒 | 4 回 | `sys.exit(1)` |
| その他エラー | なし | 0 回 | `sys.exit(1)` |

**成功後スリープ**: API 呼び出し成功ごとに `time.sleep(5)` を挿入（Google AI Studio の IPM 制限対策）。

---

## レート制限（`design_similarity.RateLimiter`）

`judge_similarity()` 内部の `RateLimiter` クラスが自動管理する。

| 制限 | 設定値 | 詳細 |
|------|--------|------|
| RPM | 15 | `MIN_INTERVAL_SEC = 1.0` で最低1秒/リクエストを保証 |
| RPD | 500（`RPD_DAILY`） | セッション開始時の `RPD_SESSION` を手動設定して残量を調整 |

RPD 上限に達した場合は `RateLimiter` が警告を出力して停止する。  
前回セッションの実行済みリクエスト数は `design_similarity.py` 冒頭の `RPD_SESSION` を手動で更新する。

---

## 実行方法

```bash
# 全年処理（JSONL_DIR 内の全 *.jsonl）
python judge_cited_pairs.py

# 指定年のみ
python judge_cited_pairs.py 2007 2008

# 図タイプを固定して処理
python judge_cited_pairs.py --type perspective

# 最初から処理し直す（既存出力を上書き）
python judge_cited_pairs.py 2007 --no-resume

# 既存結果から debug 画像を再生成（API 呼び出しなし）
python judge_cited_pairs.py --reannotate
python judge_cited_pairs.py 2007 --reannotate
```

| オプション | デフォルト | 説明 |
|-----------|-----------|------|
| `years` | 全年 | 処理する年（複数指定可） |
| `--type` | 自動選択 | 使用する図タイプ（`front` / `overview` / `perspective`）。省略時は共通タイプの中から優先順で選択。 |
| `--no-resume` | — | 出力ファイルが存在しても最初から処理し直す（デフォルトは resume 有効） |
| `--reannotate` | — | 新規判定なし。既存 JSONL から debug 画像を confidence/reason 付きで再生成。 |

### 再開（resume）

デフォルトで有効。出力 JSONL に書き込み済みの `(source, target)` ペアはスキップされる。
中断後は同じコマンドを再実行するだけで続きから再開できる。

---

## 注意事項

- バックエンドの切り替えは `design_similarity.py` 先頭の `BACKEND = "gemini"` を `"qwen"` に変更するだけでよい。本スクリプト内で `BACKEND` を参照している箇所は以下の 2 箇所：
  - `OUT_DIR` 定義（起動時）: `"qwen"` → `qwen_similarity_results/`、`"gemini"` → `similarity_results/`
  - リトライループ成功後: `"qwen"` のときは `time.sleep(5)` をスキップして即次ペアへ進む
- TIF 画像は Gemini 非対応のため `image_processor.ImageProcessor.process_file()` 内で PNG 変換して送信する
- 出力は1件ごとに `out_f.flush()` されるため、途中終了してもデータは失われない
- 共通図タイプを持たないペア（`pick_common_type()` が `None` を返す場合）は無条件にスキップされる

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| [image_pairs.md](image_pairs.md) | `judge_cited_pairs.py` | [extract_yes_pairs.md](extract_yes_pairs.md) |
| `cited_image_pairs/{year}.jsonl` | → `similarity_results/{year}.jsonl` | `extract_yes_pairs.py` / `analyze_ergm.py` |