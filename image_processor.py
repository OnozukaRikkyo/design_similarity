"""
意匠画像前処理モジュール

処理内容（この順で適用）:
  1. 上下左右の白余白を除去し、MARGIN ピクセルだけ残す
  2. 長辺を LONG_SIDE px にリサイズ（縦横比維持、縮小のみ）
"""

import argparse
from pathlib import Path

from PIL import Image, ImageChops


class ImageProcessor:
    """意匠画像の前処理（余白除去・リサイズ）"""

    LONG_SIDE: int = 768   # 長辺の目標ピクセル数
    MARGIN: int = 1        # 余白除去後に残すピクセル数
    TOLERANCE: int = 5     # 白とみなす RGB 差の最大値（スキャンノイズ吸収用）

    # ── 内部ユーティリティ ──────────────────────────────────────────────────────

    @classmethod
    def _to_rgb(cls, img: Image.Image) -> Image.Image:
        """透過・特殊モードを RGB に変換する。透過部分は白として合成。"""
        if img.mode == "RGBA":
            bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            return Image.alpha_composite(bg, img).convert("RGB")
        return img.convert("RGB")

    # ── 公開メソッド ────────────────────────────────────────────────────────────

    @classmethod
    def crop_margin(cls, img: Image.Image) -> Image.Image:
        """
        上下左右の白余白を除去し、MARGIN ピクセルだけ残して返す。

        TOLERANCE 以内の RGB 差は白とみなす（スキャンノイズ対策）。
        画像が全面白の場合は元の画像をそのまま返す。
        """
        rgb = cls._to_rgb(img)
        white = Image.new("RGB", rgb.size, (255, 255, 255))
        diff = ImageChops.difference(rgb, white)

        if cls.TOLERANCE > 0:
            diff = diff.point(lambda v: 0 if v <= cls.TOLERANCE else v)

        bbox = diff.getbbox()
        if bbox is None:
            return img  # 全面白

        left   = max(0,          bbox[0] - cls.MARGIN)
        top    = max(0,          bbox[1] - cls.MARGIN)
        right  = min(img.width,  bbox[2] + cls.MARGIN)
        bottom = min(img.height, bbox[3] + cls.MARGIN)

        return img.crop((left, top, right, bottom))

    @classmethod
    def resize_long_side(cls, img: Image.Image) -> Image.Image:
        """
        長辺が LONG_SIDE px を超える場合のみ縮小する（縦横比維持）。
        長辺が LONG_SIDE px 以下の場合は変更しない。
        """
        w, h = img.size
        long = max(w, h)
        if long <= cls.LONG_SIDE:
            return img

        scale = cls.LONG_SIDE / long
        new_w = max(1, round(w * scale))
        new_h = max(1, round(h * scale))
        return img.resize((new_w, new_h), Image.LANCZOS)

    @classmethod
    def process(cls, img: Image.Image) -> Image.Image:
        """余白除去 → リサイズ の順で処理して返す。"""
        img = cls.crop_margin(img)
        img = cls.resize_long_side(img)
        return img

    @classmethod
    def process_file(cls, path: str | Path) -> Image.Image:
        """ファイルから読み込んで処理した Image オブジェクトを返す。"""
        with Image.open(path) as img:
            return cls.process(img.copy())

    @classmethod
    def process_and_save(
        cls,
        src: str | Path,
        dst: str | Path,
        fmt: str | None = None,
    ) -> tuple[int, int]:
        """
        src を処理して dst に保存し、出力サイズ (幅, 高さ) を返す。

        fmt: 保存形式（"PNG", "JPEG" など）。省略時は dst の拡張子から自動判定。
        """
        result = cls.process_file(src)
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        result.save(dst, format=fmt)
        return result.size


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="意匠画像の前処理（白余白除去 + 長辺768pxリサイズ）"
    )
    parser.add_argument("src", help="入力画像パス")
    parser.add_argument("dst", help="出力画像パス")
    parser.add_argument(
        "--long-side", type=int, default=ImageProcessor.LONG_SIDE,
        metavar="N",
        help=f"長辺のピクセル数（デフォルト: {ImageProcessor.LONG_SIDE}）",
    )
    parser.add_argument(
        "--margin", type=int, default=ImageProcessor.MARGIN,
        metavar="N",
        help=f"残す余白ピクセル数（デフォルト: {ImageProcessor.MARGIN}）",
    )
    parser.add_argument(
        "--tolerance", type=int, default=ImageProcessor.TOLERANCE,
        metavar="N",
        help=f"白とみなすRGB差の最大値（デフォルト: {ImageProcessor.TOLERANCE}）",
    )
    args = parser.parse_args()

    ImageProcessor.LONG_SIDE  = args.long_side
    ImageProcessor.MARGIN     = args.margin
    ImageProcessor.TOLERANCE  = args.tolerance

    src = Path(args.src)
    dst = Path(args.dst)
    orig_w, orig_h = Image.open(src).size
    out_w, out_h = ImageProcessor.process_and_save(src, dst)

    print(f"{src.name}  {orig_w}×{orig_h}  →  {dst.name}  {out_w}×{out_h}")


if __name__ == "__main__":
    main()
