"""
意匠類似判定クライアント

バックエンド:
  gemini … Gemini 2.5 Flash-Lite (Google AI Studio 無料ティア)
  qwen   … Qwen-VL ローカル GPU 推論

制約 (gemini):
  - 15 RPM / 250,000 TPM / 500 RPD
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

from PIL import Image

from image_processor import ImageProcessor


# ─── バックエンド選択（ここを編集して切り替える） ───────────────────────────
# BACKEND = "gemini"           # "gemini" | "qwen"
BACKEND = "qwen"           # "gemini" | "qwen"

# ─── Gemini 設定 ─────────────────────────────────────────────────────────────
MODEL         = "gemini-3.1-flash-lite-preview"
RPD_SESSION   = 0       # 本日すでに実行済みのリクエスト数（手動で更新）
RPM_LIMIT     = 15
TPM_LIMIT     = 250_000
RPD_DAILY     = 500     # API の1日の絶対上限（変更しない）
RPD_REMAINING = RPD_DAILY - RPD_SESSION
QUOTA_RESET_TIME = "17:01"  # クォータリセット時刻（HH:MM）
THINKING_BUDGET  = 8192     # 思考トークン上限（0 で無効化）
MIN_INTERVAL_SEC = 1.0      # RPM 制約：15RPM → 最低1秒/リクエスト

# ─── Qwen 設定 ───────────────────────────────────────────────────────────────
QWEN_MODEL_ID       = "Qwen/Qwen3-VL-4B-Instruct"  # "Qwen/Qwen2-VL-7B-Instruct" など
QWEN_MAX_NEW_TOKENS = 512
QWEN_MAX_IMAGE_SIZE = 1024   # ロングエッジ上限（px）

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


# ─── レート制限（Gemini 専用） ───────────────────────────────────────────────

class RateLimiter:
    """スライディングウィンドウ方式のレート制限器"""

    def __init__(self):
        self._req_times: deque[float] = deque()
        self._token_times: deque[tuple[float, int]] = deque()
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

    @staticmethod
    def _next_reset_dt() -> datetime:
        h, m = map(int, QUOTA_RESET_TIME.split(":"))
        now = datetime.now()
        reset = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if reset <= now:
            reset += timedelta(days=1)
        return reset

    def wait_for_slot(self, n_images: int = 2) -> None:
        self._reset_day_if_needed()

        if self._day_count > RPD_REMAINING:
            reset_dt = self._next_reset_dt()
            print(
                f"\n[完了] 本日の残り上限 {RPD_REMAINING} リクエストを使い切りました。\n"
                f"  リセット予定: {reset_dt.strftime('%Y-%m-%d %H:%M')} ({QUOTA_RESET_TIME})",
                flush=True,
            )
            sys.exit(0)

        while True:
            now = time.time()
            self._purge_old(self._req_times)

            req_ok = len(self._req_times) < RPM_LIMIT
            tpm_ok = self._recent_tokens() < TPM_LIMIT

            if req_ok and tpm_ok:
                break

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


def _load_pil_image(path: str, max_size: int | None = None) -> Image.Image:
    """前処理済み PIL Image を返す（余白削除・縮小）。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"画像ファイルが見つかりません: {path}")
    if p.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise ValueError(f"非対応の画像形式: {p.suffix}")

    with Image.open(p) as raw:
        img = ImageProcessor.process(raw.copy()).convert("RGB")

    if max_size:
        w, h = img.size
        if max(w, h) > max_size:
            scale = max_size / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    if DEBUG:
        _DEBUG_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        img.save(_DEBUG_IMAGE_DIR / (p.stem + ".png"))

    return img


def _load_gemini_part(path: str):
    """画像を Gemini API の Part 形式に変換する。"""
    import io
    from google.genai import types

    img = _load_pil_image(path)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/png")


def _get_image_size(path: str) -> tuple[int, int]:
    return ImageProcessor.process_file(path).size


# ─── エラーログ ──────────────────────────────────────────────────────────────

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


def _clean_json(text: str) -> str:
    import re
    # 整数キー行を除去 (例: `  1: 3,`)
    text = re.sub(r'^\s*\d+\s*:.*\n?', '', text, flags=re.MULTILINE)
    # 末尾カンマを除去 (例: `"key": "val",}`)
    text = re.sub(r',\s*([}\]])', r'\1', text)
    return text


def _parse_json_result(raw: str, image1: str, image2: str) -> dict:
    """raw テキストから JSON を抽出してパースする。失敗時は sys.exit。"""
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        json_text = raw[start:end]
        try:
            result = json.loads(json_text)
        except json.JSONDecodeError:
            result = json.loads(_clean_json(json_text))
    except (ValueError, json.JSONDecodeError):
        log_dir = Path(__file__).parent / "log"
        log_dir.mkdir(exist_ok=True)
        log_path = log_dir / f"parse_error_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        log_path.write_text(f"raw output:\n{raw}\n\n{traceback.format_exc()}", encoding="utf-8")
        print(f"[ERROR] JSONパースに失敗しました。詳細: {log_path}", flush=True)
        sys.exit(1)
    result["raw"] = raw
    return result


# ─── Gemini バックエンド ─────────────────────────────────────────────────────

_limiter = RateLimiter()


def _judge_similarity_gemini(
    image_path_1: str,
    image_path_2: str,
    prompt: str,
    api_key: str | None = None,
) -> dict:
    from google import genai
    from google.genai import types

    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise EnvironmentError(
            "GEMINI_API_KEY 環境変数を設定してください。\n"
            "  export GEMINI_API_KEY='your-api-key'"
        )

    client = genai.Client(api_key=key)
    img1 = _load_gemini_part(image_path_1)
    img2 = _load_gemini_part(image_path_2)

    w1, h1 = _get_image_size(image_path_1)
    w2, h2 = _get_image_size(image_path_2)

    _limiter.wait_for_slot(n_images=2)

    contents = [img1, img2, types.Part.from_text(text=prompt)]
    print(
        f"  [gemini] {Path(image_path_1).name}({w1}×{h1})"
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

    remaining = MIN_INTERVAL_SEC - elapsed
    if remaining > 0:
        print(f"  [wait] {remaining:.1f}秒 待機中...", flush=True)
        time.sleep(remaining)
    else:
        time.sleep(2)

    return _parse_json_result(response.text.strip(), image_path_1, image_path_2)


# ─── Qwen バックエンド ───────────────────────────────────────────────────────

def _tqdm_write(msg: str) -> None:
    try:
        from tqdm import tqdm as _tqdm
        _tqdm.write(msg)
    except ImportError:
        print(msg, flush=True)


_qwen_model = None
_qwen_processor = None


def _get_qwen_model():
    global _qwen_model, _qwen_processor
    if _qwen_model is None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        _tqdm_write(f"  [qwen] Loading {QWEN_MODEL_ID} …")
        _qwen_model = AutoModelForImageTextToText.from_pretrained(
            QWEN_MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="cuda",
        )
        _qwen_model.eval()
        _qwen_processor = AutoProcessor.from_pretrained(QWEN_MODEL_ID)
        vram_gb = torch.cuda.memory_allocated() / 1e9
        _tqdm_write(f"  [qwen] Model loaded. VRAM used: {vram_gb:.1f} GB")
    return _qwen_model, _qwen_processor


def _judge_similarity_qwen(
    image_path_1: str,
    image_path_2: str,
    prompt: str,
) -> dict:
    import torch
    from qwen_vl_utils import process_vision_info

    model, processor = _get_qwen_model()

    img1 = _load_pil_image(image_path_1, max_size=QWEN_MAX_IMAGE_SIZE)
    img2 = _load_pil_image(image_path_2, max_size=QWEN_MAX_IMAGE_SIZE)

    w1, h1 = img1.size
    w2, h2 = img2.size
    _tqdm_write(
        f"  [qwen] {Path(image_path_1).name}({w1}×{h1})"
        f" × {Path(image_path_2).name}({w2}×{h2})"
    )

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image", "image": img1},
                {"type": "image", "image": img2},
                {"type": "text", "text": prompt},
            ],
        }
    ]

    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    img_inputs, _ = process_vision_info(messages)
    inputs = processor(
        text=[text],
        images=img_inputs if img_inputs else None,
        return_tensors="pt",
    ).to("cuda")

    t_start = time.time()
    with torch.no_grad():
        generated_ids = model.generate(**inputs, max_new_tokens=QWEN_MAX_NEW_TOKENS)
    elapsed = time.time() - t_start

    trimmed = generated_ids[0][len(inputs.input_ids[0]):]
    raw = processor.decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)
    _tqdm_write(f"  [qwen] {elapsed:.1f}秒")

    return _parse_json_result(raw.strip(), image_path_1, image_path_2)


# ─── 統合判定関数 ────────────────────────────────────────────────────────────

def judge_similarity(
    image_path_1: str,
    image_path_2: str,
    prompt: str = DEFAULT_PROMPT,
    api_key: str | None = None,
) -> dict:
    """
    2枚の画像の意匠類似性を判定する。BACKEND により Gemini / Qwen を切り替える。

    Returns:
        {
            "similarity": "Yes" | "No",
            "confidence": int (1–5),
            "reason": str,
            "raw": str
        }
    """
    if BACKEND == "qwen":
        return _judge_similarity_qwen(image_path_1, image_path_2, prompt)
    else:
        return _judge_similarity_gemini(image_path_1, image_path_2, prompt, api_key)


# ─── バッチ処理 ──────────────────────────────────────────────────────────────

def batch_judge(pairs: list[tuple[str, str]], prompt: str = DEFAULT_PROMPT) -> list[dict]:
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
    parser = argparse.ArgumentParser(description="意匠類似判定")
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