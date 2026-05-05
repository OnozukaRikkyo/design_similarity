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

入力レコードの全フィールドに以下を追加して出力する。

| 追加フィールド | 内容 |
|---------------|------|
| `image_type_used` | 判定に使用した図タイプ (`front` / `overview` / `perspective`) |
| `similarity` | 判定結果 (`Yes` / `No`) |
| `confidence` | 確信度 (1〜5、5が最も確実) |
| `reason` | 判断理由（1〜2文の英語） |
| `error` | エラー発生時のみ。`similarity` 等は付与されない。 |

```json
{
  "source": "D0535736",
  "target": "D0537156",
  "source_images": {"perspective": "/mnt/.../USD0535736-...TIF"},
  "target_images": {"perspective": "/mnt/.../USD0537156-...TIF"},
  "events": [...],
  "image_type_used": "perspective",
  "similarity": "Yes",
  "confidence": 4,
  "reason": "Both designs share an identical overall silhouette and surface ornamentation pattern."
}
```

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
