# 意匠類似判定モジュール (`design_similarity.py`)

Gemini 2.5 Flash-Lite を使って 2 枚の意匠画像を比較し、類似・非類似・要精査を判定するクライアント。

---

## 制約（Google AI Studio 無料ティア）

| 制限 | 値 | 備考 |
|------|----|------|
| RPM | 15 | リクエスト/分（安全マージンで 14 を使用） |
| IPM | 2 | 画像/分（1 リクエスト = 2 枚なので実質 1 req/分が律速） |
| RPD | 1,000 | リクエスト/日 |
| TPM | 250,000 | トークン/分 |

`RateLimiter` クラスが RPM / IPM / RPD をスライディングウィンドウ方式で自動管理する。
加えて `MIN_INTERVAL_SEC`（60 秒）で 1 リクエストあたりの最低間隔を保証する。

---

## 定数

| 定数 | デフォルト値 | 説明 |
|------|-------------|------|
| `MODEL` | `"gemini-2.5-flash-lite"` | 使用モデル |
| `RPM_LIMIT` | `14` | 1 分あたりリクエスト上限 |
| `IPM_LIMIT` | `2` | 1 分あたり画像送信枚数上限 |
| `RPD_LIMIT` | `1_000` | 1 日あたりリクエスト上限 |
| `THINKING_BUDGET` | `8192` | 思考トークン上限（`0` で無効化） |
| `MIN_INTERVAL_SEC` | `60.0` | リクエスト間の最低待機秒数 |
| `DEBUG` | `False` | `True` のとき前処理済み画像を `debug/image/` に保存する |

---

## モジュール構成

### `RateLimiter`

```python
class RateLimiter:
    def wait_for_slot(n_images: int = 2) -> None
    def record_request(n_images: int = 2) -> None
```

- `wait_for_slot()` — RPM / IPM / RPD のいずれかが上限に達していれば、次のスロットが空くまでスリープする。RPD 上限に達した場合は `RuntimeError` を raise して処理を中断する。
- `record_request()` — リクエスト完了後に呼び出してカウントを更新する。
- モジュールレベルのシングルトン `_limiter` として保持されるため、複数回呼び出しにわたって累積カウントが維持される。

---

### `load_image_part(path: str) -> dict`

画像ファイルに前処理を施してから Gemini API の `inline_data` 形式（base64 エンコード）に変換する。

**処理の流れ**

1. `ImageProcessor.process()` で余白削除・長辺 768px リサイズを適用
2. RGB に変換して PNG としてエンコード（全形式統一）
3. `DEBUG = True` の場合は処理済み画像を `debug/image/<元ファイル名>.png` に保存

対応形式: `.tif` / `.tiff` / `.jpg` / `.jpeg` / `.png` / `.webp` / `.gif` / `.bmp`

非対応形式の場合は `ValueError` を raise する。

---

### `_get_image_size(path: str) -> tuple[int, int]`

`ImageProcessor.process_file()` で前処理を適用した後の `(幅, 高さ)` を返す。`judge_similarity` 内でリクエストログへの表示に使用する（実際に API へ送信するサイズを反映）。

---

### `_write_error_log(image1, image2, exc) -> Path`

エラー情報をログファイルに追記し、ログファイルのパスを返す。

| 項目 | 内容 |
|------|------|
| 保存先 | `log/error/error_YYYYMMDD.log`（スクリプトと同じディレクトリ） |
| 形式 | タイムスタンプ・画像パス・例外クラス名・スタックトレース |
| 追記方式 | 同日のエラーは 1 ファイルに追記される |

---

### `judge_similarity(image_path_1, image_path_2, prompt=..., api_key=None) -> dict`

2 枚の画像を Gemini に送信して類似性を判定する中心関数。

**引数**

| 引数 | 型 | 説明 |
|------|----|------|
| `image_path_1` | str | 1 枚目の画像パス |
| `image_path_2` | str | 2 枚目の画像パス |
| `prompt` | str | モデルへの指示文（省略時は `DEFAULT_PROMPT`） |
| `api_key` | str \| None | Gemini API キー（省略時は環境変数 `GEMINI_API_KEY`） |

**処理の流れ**

1. 両画像を `load_image_part()` でエンコードし、`_get_image_size()` でサイズを取得
2. `_limiter.wait_for_slot()` で RPM / IPM / RPD を確認（必要なら待機）
3. `generate_content()` を `thinking_budget=THINKING_BUDGET` 付きで呼び出し、経過時間を計測
4. `response.usage_metadata` からトークン内訳（入力・出力・思考・合計）と処理時間を表示
5. `elapsed < MIN_INTERVAL_SEC` の場合は残り時間だけスリープ（IPM 制約の保証）
6. モデル出力から JSON を抽出してパース

**標準出力の例**

```
  [request] USD0535736-...TIF(800×600) × USD0537156-...TIF(800×600)
  [tokens] 入力:2618 出力:15 思考:4096 合計:6729  [12.3秒]
  [wait] 47.7秒 待機中...
```

**戻り値**

```json
{
  "similarity": "Yes" | "No",
  "confidence": 1〜5,
  "reason": "1-2 sentence rationale",
  "raw": "モデルの生テキスト（デバッグ用）"
}
```

モデルの出力が JSON としてパースできなかった場合は `{"similarity": "Unknown", "confidence": -1, "reason": "parse failed"}` を返す。

---

### `batch_judge(pairs: list[tuple[str, str]], prompt=...) -> list[dict]`

複数の画像ペアを順次処理する。

**引数**

```python
pairs = [
    ("path/to/img1a.jpg", "path/to/img1b.jpg"),
    ("path/to/img2a.png", "path/to/img2b.png"),
]
```

**エラー処理**

いかなる例外が発生しても即座に処理を中断する。エラーはスタックトレースを含めて `log/error/error_YYYYMMDD.log` に保存される。

```
  -> ERROR: <エラーメッセージ>
  [ログ保存] /path/to/log/error/error_20260505.log
```

**戻り値**

エラーが発生しなかった場合のみ、`judge_similarity` の戻り値に `image1` / `image2` キーを追加したリストを返す。エラー発生時は例外が伝播する（リストは返らない）。

---

## デフォルトプロンプト

米国・EU の意匠権判定基準（先行意匠を認知している注意深いユーザーから見て全体的な印象が実質的に同一か）を統合した英語プロンプト。

```
Act as an expert AI in intellectual property law.

You are given Image A and Image B. Evaluate whether these two designs are similar
under the following unified US/EU legal standard:
  Would an observant buyer who is familiar with prior art consider the overall visual
impression of the two designs to be substantially the same?

Focus on: overall shape and form, surface ornamentation, and the combination of
visual elements as a whole. Ignore non-visual features.

Respond with ONLY a valid JSON object — no markdown, no code fences, no extra text.

Required JSON schema (use exactly these keys):
{
  "similarity": "Yes" or "No",
  "confidence": integer from 1 (very uncertain) to 5 (highly certain),
  "reason": "1-2 sentence rationale citing the dominant visual features that drove the decision"
}
```

`--prompt` オプションまたは `prompt=` 引数でカスタマイズ可能。

---

## トークン使用量の見積もり

`thinking_budget` を設定しない場合、思考トークンが最大の不確定要素となる。

| 要素 | 計算根拠 | 目安トークン数 |
|------|---------|--------------|
| 画像 2 枚（768×768px） | 5 タイル × 258 × 2 枚 | 約 2,580 |
| 入力テキスト | 100 文字程度 | 約 25 |
| 出力テキスト | 50 文字程度 | 約 13 |
| 思考トークン | `THINKING_BUDGET=8192` で上限設定 | ≤ 8,192 |
| **合計** | | **≤ 約 10,810** |

RPM 上限（14 req/min）と掛け合わせると最大 **14 × 10,810 ≈ 151,000 TPM** となり、250,000 TPM の制限に収まる。

`THINKING_BUDGET = 0` と設定すると思考を無効化できる（高速・低コストだが推論精度が下がる場合がある）。

---

## ログ構成

```
log/
└── error/
    └── error_YYYYMMDD.log   # エラー発生日ごとに 1 ファイル

debug/                        # DEBUG = True のときのみ生成
└── image/
    └── <元ファイル名>.png    # 前処理済み画像（余白削除・縮小後）
```

ログの各エントリ形式：

```
[2026-05-05T10:23:45.123456]
image1 : /mnt/.../USD0535736-20070123-D00000.TIF
image2 : /mnt/.../USD0537156-20070220-D00000.TIF
error  : ResourceExhausted: 429 Quota exceeded
Traceback (most recent call last):
  ...
------------------------------------------------------------
```

---

## 使い方

### CLI（1 ペアを判定）

```bash
# テキスト出力
python design_similarity.py samples/design_A1.jpg samples/design_A2.jpg

# JSON 出力
python design_similarity.py samples/design_A1.jpg samples/design_A2.jpg --json

# カスタムプロンプト
python design_similarity.py img1.jpg img2.jpg --prompt "形状の類似性のみ判定してください。..."

# API キーを直接指定
python design_similarity.py img1.jpg img2.jpg --api-key "AIza..."
```

### ライブラリとして使用（1 ペア）

```python
from design_similarity import judge_similarity

result = judge_similarity("img1.jpg", "img2.jpg")
print(result["similarity"])   # Yes / No
print(result["confidence"])   # 1〜5
print(result["reason"])
```

### バッチ処理（複数ペア）

```python
import json
from design_similarity import batch_judge

pairs = [
    ("samples/design_A1.jpg", "samples/design_A2.jpg"),
    ("samples/design_B1.png", "samples/design_B2.png"),
]

results = batch_judge(pairs)  # エラー発生時は例外が raise される

with open("results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
```

---

## 環境変数

| 変数 | 必須 | 説明 |
|------|------|------|
| `GEMINI_API_KEY` | ○ | Google AI Studio の API キー |

設定方法は [setup.md](setup.md) を参照。
