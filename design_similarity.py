"""
意匠類似判定クライアント
Gemini 2.5 Flash-Lite (Google AI Studio 無料ティア) を使用

制約:
  - 15 RPM (requests per minute)
  - 2 IPM (images per minute) ← 1リクエストで画像2枚なので実質 1 req/分
  - 1,000 RPD (requests per day)
  - 250K TPM (tokens per minute)
"""

import base64
import time
import os
import sys
import json
import argparse
import traceback
from pathlib import Path
from datetime import datetime, timedelta
from collections import deque

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import google.generativeai as genai
from PIL import Image

from image_processor import ImageProcessor


# ─── 定数 ───────────────────────────────────────────────────────────────────

MODEL = "gemini-2.5-flash-lite"

# 無料ティア上限（安全マージン付き）
RPM_LIMIT = 14 # 15
IPM_LIMIT = 2   # 1リクエスト = 画像2枚 → 実質 1 req/min が画像の律速
RPD_LIMIT = 1_000
THINKING_BUDGET = 8192  # 思考トークン上限（0 で無効化）
MIN_INTERVAL_SEC = 60.0  # IPM制約：1リクエストあたり最低60秒確保
DEBUG = False  # True のとき前処理済み画像を debug/image/ に保存する

DEFAULT_PROMPT = """\
以下の2つの意匠（デザイン）の類似性を判定してください。

判定観点:
1. 全体的な印象・形態
2. 模様・装飾
3. 色彩（参考）

出力形式（JSON のみ、余分なテキスト不要）:
{
  "similarity": "類似" | "非類似" | "要精査",
  "score": 0〜100の数値（100が完全一致）,
  "reason": "判断理由（100字以内）"
}
"""


# ─── レート制限 ──────────────────────────────────────────────────────────────

class RateLimiter:
    """スライディングウィンドウ方式のレート制限器"""

    def __init__(self):
        self._req_times: deque[float] = deque()   # 過去1分のリクエスト時刻
        self._img_times: deque[float] = deque()   # 過去1分の画像送信時刻（枚数）
        self._day_count: int = 0
        self._day_start: float = time.time()

    def _purge_old(self, q: deque, window: float = 60.0) -> None:
        now = time.time()
        while q and now - q[0] > window:
            q.popleft()

    def _reset_day_if_needed(self) -> None:
        if time.time() - self._day_start >= 86400:
            self._day_count = 0
            self._day_start = time.time()

    def wait_for_slot(self, n_images: int = 2) -> None:
        """レート上限に達していれば必要な時間だけ待機する"""
        self._reset_day_if_needed()

        if self._day_count >= RPD_LIMIT:
            raise RuntimeError(
                f"1日の上限 {RPD_LIMIT} リクエストに達しました。"
                f"リセット予定: {datetime.fromtimestamp(self._day_start + 86400)}"
            )

        while True:
            now = time.time()
            self._purge_old(self._req_times)
            self._purge_old(self._img_times)

            req_ok = len(self._req_times) < RPM_LIMIT
            img_ok = len(self._img_times) + n_images <= IPM_LIMIT

            if req_ok and img_ok:
                break

            # 次にスロットが空く時刻を計算
            waits = []
            if not req_ok:
                waits.append(60.0 - (now - self._req_times[0]))
            if not img_ok:
                needed = (len(self._img_times) + n_images) - IPM_LIMIT
                waits.append(60.0 - (now - self._img_times[needed - 1]))

            wait_sec = max(0.1, max(waits))
            print(f"  [rate-limit] {wait_sec:.1f}秒 待機中...", flush=True)
            time.sleep(wait_sec)

    def record_request(self, n_images: int = 2) -> None:
        now = time.time()
        self._req_times.append(now)
        for _ in range(n_images):
            self._img_times.append(now)
        self._day_count += 1


# ─── 画像読み込み ────────────────────────────────────────────────────────────

_SUPPORTED_SUFFIXES = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_DEBUG_IMAGE_DIR = Path(__file__).parent / "debug" / "image"


def load_image_part(path: str) -> dict:
    """画像ファイルを余白削除・縮小してから Gemini API の inline_data 形式に変換する"""
    import io

    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"画像ファイルが見つかりません: {path}")
    if p.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"非対応の画像形式: {p.suffix}")

    with Image.open(p) as raw:
        img = ImageProcessor.process(raw.copy()).convert("RGB")

    if DEBUG:
        _DEBUG_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        img.save(_DEBUG_IMAGE_DIR / (p.stem + ".png"))

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}}


def _get_image_size(path: str) -> tuple[int, int]:
    """前処理後の画像の (幅, 高さ) を返す"""
    return ImageProcessor.process_file(path).size


# ─── 判定関数 ────────────────────────────────────────────────────────────────

_limiter = RateLimiter()

_ERROR_LOG_DIR = Path(__file__).parent / "log" / "error"


def _write_error_log(image1: str, image2: str, exc: BaseException) -> Path:
    _ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _ERROR_LOG_DIR / f"error_{datetime.now().strftime('%Y%m%d')}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now().isoformat()}]\n")
        f.write(f"image1 : {image1}\n")
        f.write(f"image2 : {image2}\n")
        f.write(f"error  : {type(exc).__name__}: {exc}\n")
        f.write(traceback.format_exc())
        f.write("-" * 60 + "\n")
    return log_file


def judge_similarity(
    image_path_1: str,
    image_path_2: str,
    prompt: str = DEFAULT_PROMPT,
    api_key: str | None = None,
) -> dict:
    """
    2枚の画像の意匠類似性を Gemini で判定する。

    Returns:
        {
            "similarity": "類似" | "非類似" | "要精査",
            "score": int,
            "reason": str,
            "raw": str   # モデルの生テキスト（デバッグ用）
        }
    """
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise EnvironmentError(
            "GEMINI_API_KEY 環境変数を設定してください。\n"
            "  export GEMINI_API_KEY='your-api-key'"
        )

    genai.configure(api_key=key)
    model = genai.GenerativeModel(MODEL)

    img1 = load_image_part(image_path_1)
    img2 = load_image_part(image_path_2)

    w1, h1 = _get_image_size(image_path_1)
    w2, h2 = _get_image_size(image_path_2)

    # レート制限チェック＆待機
    _limiter.wait_for_slot(n_images=2)

    contents = [
        img1,
        img2,
        {"text": prompt},
    ]

    print(
        f"  [request] {Path(image_path_1).name}({w1}×{h1})"
        f" × {Path(image_path_2).name}({w2}×{h2})",
        flush=True,
    )

    t_start = time.time()
    response = model.generate_content(
        contents,
        generation_config={"thinking_config": {"thinking_budget": THINKING_BUDGET}},
    )
    elapsed = time.time() - t_start

    _limiter.record_request(n_images=2)

    # トークン使用量
    usage = response.usage_metadata
    if usage:
        thoughts = getattr(usage, "thoughts_token_count", "-")
        print(
            f"  [tokens] 入力:{usage.prompt_token_count}"
            f" 出力:{usage.candidates_token_count}"
            f" 思考:{thoughts}"
            f" 合計:{usage.total_token_count}"
            f"  [{elapsed:.1f}秒]",
            flush=True,
        )

    # IPM上限対応: リクエスト開始から60秒未満なら残り時間だけ待機
    remaining = MIN_INTERVAL_SEC - elapsed
    if remaining > 0:
        print(f"  [wait] {remaining:.1f}秒 待機中...", flush=True)
        time.sleep(remaining)

    raw = response.text.strip()

    # JSON 部分を抽出してパース
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        result = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        result = {"similarity": "要精査", "score": -1, "reason": "パース失敗"}

    result["raw"] = raw
    return result


# ─── バッチ処理 ──────────────────────────────────────────────────────────────

def batch_judge(pairs: list[tuple[str, str]], prompt: str = DEFAULT_PROMPT) -> list[dict]:
    """
    複数ペアを順次処理する。レート制限は judge_similarity 内で自動管理。

    Args:
        pairs: [(image1_path, image2_path), ...]

    Returns:
        判定結果のリスト
    """
    results = []
    total = len(pairs)
    for i, (p1, p2) in enumerate(pairs, 1):
        print(f"[{i}/{total}] 判定中...", flush=True)
        try:
            r = judge_similarity(p1, p2, prompt=prompt)
            r["image1"] = p1
            r["image2"] = p2
            results.append(r)
            print(f"  -> {r['similarity']} (score={r['score']}) | {r['reason']}")
        except Exception as e:
            log_file = _write_error_log(p1, p2, e)
            print(f"  -> ERROR: {e}", file=sys.stderr)
            print(f"  [ログ保存] {log_file}", file=sys.stderr)
            raise
    return results


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="意匠類似判定 (Gemini 2.5 Flash Lite)"
    )
    parser.add_argument("image1", help="画像1のパス")
    parser.add_argument("image2", help="画像2のパス")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="カスタムプロンプト")
    parser.add_argument("--api-key", default=None, help="Gemini API キー（省略時は環境変数）")
    parser.add_argument("--json", action="store_true", help="結果を JSON で出力")
    args = parser.parse_args()

    result = judge_similarity(args.image1, args.image2, prompt=args.prompt, api_key=args.api_key)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== 判定結果 ===")
        print(f"類似性  : {result.get('similarity', 'N/A')}")
        print(f"スコア  : {result.get('score', 'N/A')}")
        print(f"理由    : {result.get('reason', 'N/A')}")


if __name__ == "__main__":
    main()
