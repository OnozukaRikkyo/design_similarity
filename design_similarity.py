"""
意匠類似判定クライアント
Gemini 2.5 Flash-Lite (Google AI Studio 無料ティア) を使用

制約:
  - 15 RPM (requests per minute)
  - 1,000,000 TPM (tokens per minute)
  - 1,500 RPD (requests per day)
"""

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

from google import genai
from google.genai import types
from PIL import Image

from image_processor import ImageProcessor


# ─── 定数 ───────────────────────────────────────────────────────────────────

# MODEL = "gemini-2.5-flash-lite"
# MODEL = "Gemini 2.5 FlasM"
MODEL = "gemini-3.1-flash-lite-preview"
# 
# 無料ティア上限
RPM_LIMIT = 15
TPM_LIMIT = 250_000
RPD_LIMIT = 500
THINKING_BUDGET = 8192  # 思考トークン上限（0 で無効化）
MIN_INTERVAL_SEC = 1.0  # RPM制約：15RPM → 最低1秒/リクエスト
DEBUG = False  # True のとき前処理済み画像を debug/image/ に保存する

DEFAULT_PROMPT = """\
Act as an expert AI in intellectual property law.

You are given Image A and Image B. Evaluate whether these two designs are similar \
under the following unified US/EU legal standard:
  Would an observant buyer who is familiar with prior art consider the overall visual \
impression of the two designs to be substantially the same?

Focus on: overall shape and form, surface ornamentation, and the combination of \
visual elements as a whole. Ignore non-visual features.

Respond with ONLY a valid JSON object — no markdown, no code fences, no explanatory text before or after.

Required JSON schema (use exactly these keys):
{
  "similarity": "Yes" or "No",
  "confidence": integer from 1 (very uncertain) to 5 (highly certain),
  "reason": "1-2 sentence rationale citing the dominant visual features that drove the decision"
}
"""


# ─── レート制限 ──────────────────────────────────────────────────────────────

class RateLimiter:
    """スライディングウィンドウ方式のレート制限器"""

    def __init__(self):
        self._req_times: deque[float] = deque()              # 過去1分のリクエスト時刻
        self._token_times: deque[tuple[float, int]] = deque() # 過去1分の (時刻, トークン数)
        self._day_count: int = 0
        self._day_start: float = time.time()

    def _purge_old(self, q: deque, window: float = 60.0) -> None:
        now = time.time()
        while q and now - q[0] > window:
            q.popleft()

    def _purge_old_tokens(self, window: float = 60.0) -> None:
        now = time.time()
        while self._token_times and now - self._token_times[0][0] > window:
            self._token_times.popleft()

    def _recent_tokens(self) -> int:
        self._purge_old_tokens()
        return sum(t for _, t in self._token_times)

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

            req_ok = len(self._req_times) < RPM_LIMIT
            tpm_ok = self._recent_tokens() < TPM_LIMIT

            if req_ok and tpm_ok:
                break

            # 次にスロットが空く時刻を計算
            waits = []
            if not req_ok:
                waits.append(60.0 - (now - self._req_times[0]))
            if not tpm_ok:
                waits.append(60.0 - (now - self._token_times[0][0]))

            wait_sec = max(0.1, max(waits))
            print(f"  [rate-limit] {wait_sec:.1f}秒 待機中...", flush=True)
            time.sleep(wait_sec)

    def record_request(self, n_images: int = 2, total_tokens: int = 0) -> None:
        now = time.time()
        self._req_times.append(now)
        self._token_times.append((now, total_tokens))
        self._day_count += 1


# ─── 画像読み込み ────────────────────────────────────────────────────────────

_SUPPORTED_SUFFIXES = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
_DEBUG_IMAGE_DIR = Path(__file__).parent / "debug" / "image"


def load_image_part(path: str) -> types.Part:
    """画像ファイルを余白削除・縮小してから Gemini API の Part 形式に変換する"""
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
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")


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
            "similarity": "Yes" | "No",
            "confidence": int (1–5),
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

    client = genai.Client(api_key=key)

    img1 = load_image_part(image_path_1)
    img2 = load_image_part(image_path_2)

    w1, h1 = _get_image_size(image_path_1)
    w2, h2 = _get_image_size(image_path_2)

    # レート制限チェック＆待機
    _limiter.wait_for_slot(n_images=2)

    contents = [img1, img2, types.Part.from_text(text=prompt)]

    print(
        f"  [request] {Path(image_path_1).name}({w1}×{h1})"
        f" × {Path(image_path_2).name}({w2}×{h2})",
        flush=True,
    )

    t_start = time.time()
    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=THINKING_BUDGET),
        ),
    )
    elapsed = time.time() - t_start

    # トークン使用量
    usage = response.usage_metadata
    total_tokens = usage.total_token_count if usage else 0
    _limiter.record_request(n_images=2, total_tokens=total_tokens)
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
    else:
        time.sleep(0.5)

    raw = response.text.strip()

    # JSON 部分を抽出してパース
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        result = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        log_dir = Path(__file__).parent / "log"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"parse_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        log_path.write_text(f"raw output:\n{raw}\n\n{traceback.format_exc()}", encoding="utf-8")
        print(f"[ERROR] JSONパースに失敗しました。詳細: {log_path}", flush=True)
        sys.exit(1)

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
            print(f"  -> {r['similarity']} (confidence={r['confidence']}) | {r['reason']}")
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
        print(f"Similarity  : {result.get('similarity', 'N/A')}")
        print(f"Confidence  : {result.get('confidence', 'N/A')}")
        print(f"Reason      : {result.get('reason', 'N/A')}")


if __name__ == "__main__":
    main()
