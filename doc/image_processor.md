# 画像前処理モジュール (`image_processor.py`)

意匠画像を Gemini API に送信する前に行う前処理クラス。
余白除去とリサイズの 2 ステップを順に適用する。

---

## 処理の流れ

```
元画像
  │
  ▼
crop_margin()      ── 白余白を除去し、MARGIN px の余白を残す
  │
  ▼
resize_long_side() ── 長辺が LONG_SIDE px を超える場合のみ縮小（縦横比維持）
  │
  ▼
前処理済み画像
```

---

## クラス定数

| 定数 | デフォルト値 | 説明 |
|------|-------------|------|
| `LONG_SIDE` | `768` | 長辺の目標ピクセル数 |
| `MARGIN` | `1` | 余白除去後に残すピクセル数 |
| `TOLERANCE` | `5` | 白とみなす RGB 差の最大値（スキャンノイズ吸収用） |

---

## メソッド

### `_to_rgb(img: Image.Image) -> Image.Image` *(内部)*

画像を RGB モードに変換する。RGBA（透過付き）の場合は白背景に合成してから変換する。
`crop_margin()` から呼び出される。

---

### `crop_margin(img: Image.Image) -> Image.Image`

上下左右の白余白を除去し、`MARGIN` ピクセルだけ残して返す。

**アルゴリズム:**
1. 画像を RGB に変換（透過（RGBA）は白背景に合成してから変換）
2. 純白画像との差分 (`ImageChops.difference`) を取る
3. 差分が `TOLERANCE` 以下のチャンネル値をゼロにする（スキャンノイズ吸収）
4. `getbbox()` で非ゼロ領域のバウンディングボックスを取得
5. 各辺を `MARGIN` ピクセル分拡張してクロップ

画像が全面白の場合は元の画像をそのまま返す。

---

### `resize_long_side(img: Image.Image) -> Image.Image`

長辺が `LONG_SIDE` px を超える場合のみ縮小する。`LONG_SIDE` 以下の場合は変更しない（拡大はしない）。

| 条件 | 処理 |
|------|------|
| `max(幅, 高さ) > LONG_SIDE` | 長辺 = `LONG_SIDE` になるよう縦横比を維持して縮小 |
| `max(幅, 高さ) ≤ LONG_SIDE` | 変更なし |

リサンプルは `Image.LANCZOS`（高品質縮小）を使用する。

---

### `process(img: Image.Image) -> Image.Image`

`crop_margin()` → `resize_long_side()` の順で処理して返す。

---

### `process_file(path: str | Path) -> Image.Image`

ファイルから読み込んで処理した `Image` オブジェクトを返す。

---

### `process_and_save(src, dst, fmt=None) -> tuple[int, int]`

`src` を処理して `dst` に保存し、出力サイズ `(幅, 高さ)` を返す。

| 引数 | 型 | 説明 |
|------|----|------|
| `src` | str \| Path | 入力画像パス |
| `dst` | str \| Path | 出力画像パス |
| `fmt` | str \| None | 保存形式（`"PNG"`, `"JPEG"` など）。省略時は `dst` の拡張子から自動判定 |

`dst` の親ディレクトリが存在しない場合は自動で作成する。

---

## 使い方

### ライブラリとして使用

```python
from image_processor import ImageProcessor
from PIL import Image

# PIL Image を直接処理
with Image.open("design.tif") as img:
    result = ImageProcessor.process(img.copy())
result.save("design_processed.png")

# ファイルから読み込んで処理
result = ImageProcessor.process_file("design.tif")
result.save("design_processed.png")

# 処理して保存（出力サイズを取得）
w, h = ImageProcessor.process_and_save("design.tif", "design_processed.png")
print(f"{w}×{h}px")
```

### パラメータを変更する場合

```python
from image_processor import ImageProcessor

ImageProcessor.LONG_SIDE  = 512   # 長辺を 512px に変更
ImageProcessor.MARGIN     = 2     # 余白を 2px に変更
ImageProcessor.TOLERANCE  = 10    # 白判定の許容差を広げる

result = ImageProcessor.process_file("design.tif")
```

### `design_similarity.py` と組み合わせる場合

```python
from image_processor import ImageProcessor
from design_similarity import judge_similarity
import tempfile
from pathlib import Path

def judge_with_preprocess(path1: str, path2: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        p1 = Path(tmp) / Path(path1).name
        p2 = Path(tmp) / Path(path2).name
        ImageProcessor.process_and_save(path1, p1)
        ImageProcessor.process_and_save(path2, p2)
        return judge_similarity(str(p1), str(p2))
```

### CLI（1 枚ずつ処理）

```bash
# 基本
python image_processor.py input.tif output.png

# パラメータ指定
python image_processor.py input.tif output.png --long-side 512 --margin 2 --tolerance 10
```

出力例:

```
USD0535736-20070123-D00000.TIF  1200×900  →  output.png  768×576
```

---

## TOLERANCE の目安

| 値 | 適用場面 |
|----|---------|
| `0` | 完全な純白（255, 255, 255）のみを余白とみなす |
| `5`（デフォルト） | スキャンノイズ・わずかなグレーを余白とみなす |
| `10〜20` | 薄いグレー背景を余白とみなしたい場合 |

値を大きくすると余白とみなす範囲が広がるが、薄い線や淡い色の意匠が削られるリスクが高まる。

---

## Gemini トークンへの効果

前処理によりタイル数が減少し、入力トークンを削減できる。

| 画像サイズ | タイル数 | 入力トークン（画像分） |
|-----------|---------|----------------------|
| 4000×3000px（非圧縮） | 多数 | 数千 |
| 768×576px（前処理後） | 3 タイル | 774 |
| 768×768px（前処理後） | 5 タイル | 1,290 |

> タイル 1 枚 = 258 トークン（Gemini 2.5 の計算方式）

---

## 前後の処理との関係

| 前工程 | 本モジュール | 後工程 |
|--------|-------------|--------|
| 元の意匠画像（TIF など） | `ImageProcessor.process()` | [design_similarity.md](design_similarity.md) |
