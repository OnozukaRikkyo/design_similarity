#!/usr/bin/env python3
"""
Yes 判定かつ類似度閾値以上のペアのうち、reason に「完全一致」を示す
キーワードを含まないペアの画像を出力する。

判定基準:
    Qwen3-VL-4B-Instruct にreasonリストを渡し、
    完全一致を示すキーワードと非完全一致を示すキーワードを取得する。
    取得したキーワードで reason をフィルタリングする。
    LLM問い合わせ失敗時は identical / exact / same にフォールバック。

入力:
    class/{CLASS}/rank_judgments/{sim_func}/all.jsonl

出力:
    /mnt/eightthdd/uspto/class/{CLASS}/rank_analysis/{sim_func}/{type}/non_exact_pairs/
      {src}--{tgt}_rank{r:03d}.png   — ソース / ターゲット 2 枚 + reason テキスト

実行:
    python vector/analysis/export_non_exact_pairs.py --class D18
    python vector/analysis/export_non_exact_pairs.py --class D18 --min-sim 0.9
    python vector/analysis/export_non_exact_pairs.py --class D18 --use-llm   # Qwen 有効
"""

import argparse
import json
import re
import sys
import textwrap
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from image_processor import ImageProcessor

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
CLASS_BASE = Path("/mnt/eightthdd/uspto/class")

QWEN_MODEL_ID       = "Qwen/Qwen3-VL-4B-Instruct"
QWEN_MAX_NEW_TOKENS = 512

FALLBACK_EXACT_KEYWORDS     = ["identical", "exact", "same"]
FALLBACK_NON_EXACT_KEYWORDS = ["similar", "minor difference", "comparable",
                                "visually indistinguishable", "visually consistent"]

# ---------------------------------------------------------------------------
# LLM プロンプト（英語）
# ---------------------------------------------------------------------------
KEYWORD_PROMPT = """\
You are analyzing reason texts from a design patent similarity judgment system.
Each reason below explains why two design patent images were judged as visually similar (Yes).

Some reasons describe a COMPLETE / IDENTICAL match — they use strong words such as
"identical", "exact", or "same" to state that both designs are the same.
Others describe a SIMILAR but NOT perfectly identical match — they use words such as
"similar", "minor differences", or "comparable" to indicate partial resemblance.

Reason texts ({n} total):
{reasons_text}

Task:
1. Identify English keywords or short phrases that indicate a COMPLETE / IDENTICAL match
   (exact_keywords).
2. Identify English keywords or short phrases that indicate SIMILARITY WITHOUT perfect
   identity (non_exact_keywords).

Respond with ONLY a valid JSON object — no markdown, no code fences, no extra text:
{{
  "exact_keywords": ["word1", "word2"],
  "non_exact_keywords": ["word1", "word2"]
}}
"""


# ---------------------------------------------------------------------------
# Qwen モデル（シングルトン、テキストのみ）
# ---------------------------------------------------------------------------
_qwen_model     = None
_qwen_processor = None


def _get_qwen_model():
    global _qwen_model, _qwen_processor
    if _qwen_model is None:
        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        print(f"  [qwen] Loading {QWEN_MODEL_ID} ...")
        _qwen_model = AutoModelForImageTextToText.from_pretrained(
            QWEN_MODEL_ID,
            torch_dtype=torch.bfloat16,
            device_map="cuda",
        )
        _qwen_model.eval()
        _qwen_processor = AutoProcessor.from_pretrained(QWEN_MODEL_ID)
        vram_gb = torch.cuda.memory_allocated() / 1e9
        print(f"  [qwen] Model loaded. VRAM used: {vram_gb:.1f} GB")
    return _qwen_model, _qwen_processor


def _qwen_text_generate(prompt: str) -> str:
    import torch

    model, processor = _get_qwen_model()
    messages = [{"role": "user", "content": [{"type": "text", "text": prompt}]}]
    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = processor(text=[text], return_tensors="pt").to("cuda")

    t0 = time.time()
    with torch.no_grad():
        generated_ids = model.generate(
            **inputs, max_new_tokens=QWEN_MAX_NEW_TOKENS, do_sample=False
        )
    elapsed = time.time() - t0

    trimmed = generated_ids[0][len(inputs.input_ids[0]):]
    raw = processor.decode(trimmed, skip_special_tokens=True,
                           clean_up_tokenization_spaces=False)
    print(f"  [qwen] {elapsed:.1f}s")
    return raw.strip()


# ---------------------------------------------------------------------------
# LLM によるキーワード取得
# ---------------------------------------------------------------------------
def ask_llm_for_keywords(reasons: list[str]) -> tuple[list[str], list[str]]:
    """
    Qwen3-VL-4B-Instruct にreason一覧を渡し、
    完全一致キーワードと非完全一致キーワードを取得する。

    Returns: (exact_keywords, non_exact_keywords)
    """
    reasons_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(reasons))
    prompt = KEYWORD_PROMPT.format(n=len(reasons), reasons_text=reasons_text)

    try:
        raw = _qwen_text_generate(prompt)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("JSON not found in response")
        data = json.loads(raw[start:end])
        exact_kws     = [str(k).lower() for k in data.get("exact_keywords",     [])]
        non_exact_kws = [str(k).lower() for k in data.get("non_exact_keywords", [])]
        if not exact_kws:
            raise ValueError("empty exact_keywords")
        return exact_kws, non_exact_kws

    except Exception as e:
        print(f"  [warn] LLM parse failed ({e}). Using fallback keywords.",
              file=sys.stderr)
        return FALLBACK_EXACT_KEYWORDS, FALLBACK_NON_EXACT_KEYWORDS


# ---------------------------------------------------------------------------
# フィルタリング
# ---------------------------------------------------------------------------
def build_exact_pattern(exact_keywords: list[str]) -> re.Pattern:
    terms = "|".join(re.escape(k) for k in exact_keywords)
    return re.compile(rf"\b({terms})\b", re.IGNORECASE)


def is_non_exact(reason: str, exact_pattern: re.Pattern) -> bool:
    return not exact_pattern.search(reason)


def load_yes_records(
    target_class: str, sim_func: str, img_type: str, min_sim: float
) -> list[dict]:
    fp = CLASS_BASE / target_class / "rank_judgments" / sim_func / "all.jsonl"
    if not fp.exists():
        raise FileNotFoundError(
            f"{fp} が見つかりません。先に join_judgments.py を実行してください。"
        )
    return [
        json.loads(l) for l in fp.read_text().splitlines()
        if l.strip()
        and json.loads(l).get("type")     == img_type
        and json.loads(l).get("judgment") == "Yes"
        and json.loads(l).get("similarity", 0) >= min_sim
    ]


# ---------------------------------------------------------------------------
# 画像ロード
# ---------------------------------------------------------------------------
def load_image(path: str | None) -> np.ndarray | None:
    if not path:
        return None
    try:
        return np.array(ImageProcessor.process_file(path).convert("RGB"))
    except Exception as e:
        print(f"  [warn] {path}: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# スタイル
# ---------------------------------------------------------------------------
def _set_style() -> None:
    plt.rcParams.update({
        "font.family":      "serif",
        "font.serif":       ["Times New Roman", "DejaVu Serif", "Palatino"],
        "mathtext.fontset": "stix",
        "font.size":        12,
        "axes.titlesize":   12,
        "figure.dpi":       200,
        "savefig.dpi":      200,
        "savefig.bbox":     "tight",
        "pdf.fonttype":     42,
    })


# ---------------------------------------------------------------------------
# 1 ペアの可視化
# ---------------------------------------------------------------------------
def plot_non_exact_pair(rec: dict, out_path: Path) -> None:
    """
    レイアウト（2 行 × 5 列）:
      Row 0, Col 0-1 : Query（ソース）画像
      Row 0, Col 2-3 : Expected（ターゲット）画像 + rank / 類似度
      Row 0, Col 4   : 統計情報テキスト
      Row 1, Col 0-4 : Reason テキスト（全幅）
    """
    CELL_W     = 1.65
    CELL_H     = 2.1
    N_COLS     = 5
    TITLE_FS   = 11
    CAPTION_FS = 10
    INFO_FS    = 10
    REASON_FS  = 11

    fig = plt.figure(figsize=(CELL_W * N_COLS, CELL_H * 2))
    gs = gridspec.GridSpec(
        2, N_COLS,
        figure=fig,
        height_ratios=[3, 1.2],
        hspace=0.55, wspace=0.10,
        top=0.88, bottom=0.02, left=0.01, right=0.99,
    )

    def _panel(ax, img_path, title, caption, border=None, border_lw=3.0):
        arr = load_image(img_path)
        ax.set_xticks([]); ax.set_yticks([])
        if arr is not None:
            ax.imshow(arr, aspect="equal", interpolation="lanczos")
        else:
            ax.set_facecolor("#e8e8e8")
            ax.text(0.5, 0.5, "N/A", ha="center", va="center",
                    transform=ax.transAxes, fontsize=CAPTION_FS)
        ax.set_title(title, fontsize=TITLE_FS, pad=3, fontweight="bold")
        ax.set_xlabel(caption, fontsize=CAPTION_FS, labelpad=4)
        for sp in ax.spines.values():
            if border:
                sp.set_edgecolor(border); sp.set_linewidth(border_lw)
            else:
                sp.set_linewidth(0.6)

    ax_a = fig.add_subplot(gs[0, :2])
    _panel(ax_a, rec["source_image"], f"Query: {rec['source']}", "")

    ax_b = fig.add_subplot(gs[0, 2:4])
    _panel(ax_b, rec["target_image"],
           f"Expected (cited): {rec['target']}",
           (f"rank = {rec['rank']} / {rec['n_candidates']}"
            f"   $r_{{\\rm s}}$ = {rec['similarity']:.4f}\n"
            f"LLM: {rec['judgment']}   conf = {rec['confidence']}"),
           border="#1f77b4")

    ax_info = fig.add_subplot(gs[0, 4])
    ax_info.axis("off")
    info = (
        f"Rank   : {rec['rank']}\n"
        f"Sim    : {rec['similarity']:.4f}\n"
        f"Conf   : {rec['confidence']}\n"
        f"Type   : {rec['type']}"
    )
    ax_info.text(0.06, 0.95, info, va="top", ha="left",
                 transform=ax_info.transAxes,
                 fontsize=INFO_FS, family="monospace",
                 bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#999", alpha=0.9))

    ax_reason = fig.add_subplot(gs[1, :])
    ax_reason.axis("off")
    wrapped = "\n".join(textwrap.wrap(rec.get("reason", ""), width=110))
    ax_reason.text(
        0.5, 0.85,
        f"Reason: {wrapped}",
        va="top", ha="center",
        transform=ax_reason.transAxes,
        fontsize=REASON_FS,
        style="italic",
        bbox=dict(boxstyle="round,pad=0.5", fc="#fff8e7", ec="#e0b040", alpha=0.9),
    )

    fig.suptitle(
        f"Non-exact similar pair: {rec['source']} → {rec['target']}",
        fontsize=12, y=0.995,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="完全一致でない Yes 判定ペアの画像を出力する"
    )
    parser.add_argument("--class",   dest="target_class", default="D18", metavar="CLASS")
    parser.add_argument("--sim",     default="cosine_numpy",
                        choices=["cosine_numpy", "cosine_faiss"])
    parser.add_argument("--type",    dest="img_type", default="perspective",
                        choices=["perspective", "front", "overview"])
    parser.add_argument("--min-sim", type=float, default=0.8,
                        help="コサイン類似度の下限（デフォルト: 0.8）")
    parser.add_argument("--use-llm", action="store_true",
                        help="Qwen LLM によるキーワード取得を有効にする（デフォルト: 無効）")
    args = parser.parse_args()

    print(f"対象クラス  : {args.target_class}")
    print(f"類似度関数  : {args.sim}")
    print(f"画像タイプ  : {args.img_type}")
    print(f"類似度下限  : {args.min_sim}")
    print()

    # Step 1: Yes レコード取得
    yes_recs = load_yes_records(
        args.target_class, args.sim, args.img_type, args.min_sim
    )
    print(f"Yes ペア（similarity >= {args.min_sim}）: {len(yes_recs)} 件")

    # Step 2: キーワード取得
    if args.use_llm:
        print("\nQuerying LLM for keywords (Qwen3-VL-4B-Instruct) ...")
        reasons = [r["reason"] for r in yes_recs]
        exact_kws, non_exact_kws = ask_llm_for_keywords(reasons)
    else:
        print("\n[LLM スキップ] フォールバックキーワードを使用します（--use-llm で有効化）")
        exact_kws, non_exact_kws = FALLBACK_EXACT_KEYWORDS, FALLBACK_NON_EXACT_KEYWORDS
    print(f"  exact_keywords     : {exact_kws}")
    print(f"  non_exact_keywords : {non_exact_kws}")

    # Step 3: フィルタリング
    exact_pattern = build_exact_pattern(exact_kws)
    non_exact = [r for r in yes_recs if is_non_exact(r["reason"], exact_pattern)]
    non_exact.sort(key=lambda r: (r["rank"], -r["similarity"]))
    print(f"\n完全一致でない Yes ペア: {len(non_exact)} 件 / {len(yes_recs)} 件")

    if not non_exact:
        print("出力対象がありません。")
        return

    # Step 4: 画像出力
    out_dir = (
        CLASS_BASE / args.target_class
        / "rank_analysis" / args.sim / args.img_type
        / "non_exact_pairs"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # 既存 PNG を削除（rank 変化で同ペアの旧ファイルが残存するのを防ぐ）
    stale = list(out_dir.glob("*.png"))
    if stale:
        for f in stale:
            f.unlink()
        print(f"既存ファイル削除: {len(stale)} 件")

    print(f"出力先: {out_dir}")
    print()

    _set_style()
    for rec in tqdm(non_exact, desc="pair images", unit="件"):
        fname = f"{rec['source']}--{rec['target']}_rank{rec['rank']:03d}.png"
        plot_non_exact_pair(rec, out_dir / fname)

    print(f"\n完了: {len(non_exact)} 件 → {out_dir}")


if __name__ == "__main__":
    main()
