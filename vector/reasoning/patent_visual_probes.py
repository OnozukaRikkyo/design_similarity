"""
patent_visual_probes.py
=======================

M5: Visual-faithfulness probe — extract perceptual claims from a VLM rationale,
verify each claim against the actual patent images, compute the
Unverified-claim Penalty Rate (UPR).

B:  VLM-direct baseline — ask the vision model whether design A ≅ design B
    from images alone, without supplying any rationale text.

Gemini API 実装は design_similarity.py および patent_rationale_pms.py のパターンに準拠:
  - RateLimiter の _limiter シングルトンを共有
  - thinking_level → thinking_budget 変換
  - response_schema TypeError fallback
  - MIN_INTERVAL_SEC 後待機

Requirements:
  pip install pydantic>=2.5 google-genai>=1.0 pandas pillow tqdm
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[2] / ".env", override=True)

import pandas as pd
from pydantic import BaseModel, Field, model_validator
from tqdm import tqdm

try:
    from google import genai
    from google.genai import types as genai_types
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False

# shared rate limiter and constants from patent_rationale_pms
from patent_rationale_pms import (
    LLMConfig,
    DEFAULT_CONFIGS,
    _limiter,
    _THINKING_BUDGET_MAP,
    MIN_INTERVAL_SEC,
    _extract_json,
    _write_error_log,
)

log = logging.getLogger("patent_visual_probes")


# ============================================================================
# Section 1: Pydantic schemas
# ============================================================================

class PerceptualClaim(BaseModel):
    """One verifiable perceptual claim extracted from a rationale."""
    claim_text: str = Field(..., min_length=10, description="The verbatim or paraphrased claim.")
    facet: str = Field(..., description="Visual facet this claim pertains to (e.g. GlobalShape).")
    polarity: Literal["similarity", "difference"] = Field(
        ..., description="Does the claim assert similarity or difference?"
    )


class ClaimExtractionResult(BaseModel):
    """M5 Step 1: structured list of perceptual claims from a rationale."""
    extraction_reasoning: str = Field(..., min_length=20)
    claims: list[PerceptualClaim] = Field(default_factory=list)


class ClaimVerdict(BaseModel):
    """M5 Step 2: verification of one claim against the images."""
    claim_text: str
    verification_reasoning: str = Field(..., min_length=20)
    verdict: Literal["supported", "contradicted", "unverifiable"] = Field(
        ...,
        description=(
            "'supported' if the images clearly back the claim, "
            "'contradicted' if the images clearly refute it, "
            "'unverifiable' if the images do not provide enough information."
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


class ImageVerificationResult(BaseModel):
    """M5 Step 2 output: verdicts for all claims in one pair."""
    overall_reasoning: str = Field(..., min_length=30)
    verdicts: list[ClaimVerdict] = Field(default_factory=list)


class VisualFaithfulnessScore(BaseModel):
    """Aggregated M5 score for one (source, target) pair."""
    source: str
    target: str
    n_claims: int
    n_supported: int
    n_contradicted: int
    n_unverifiable: int
    upr: float          # Unverified-claim Penalty Rate = (contradicted + unverifiable) / max(n_claims, 1)
    m5_score: float     # 1 - upr (higher = more faithful)
    claims_json: str    # JSON dump of ClaimExtractionResult


class BaselineResult(BaseModel):
    """B: VLM-direct baseline — judgment from images only."""
    source: str
    target: str
    baseline_reasoning: str = Field(..., min_length=30)
    baseline_judgment: Literal["Yes", "No"] = Field(
        ..., description="Are the two designs visually equivalent?"
    )
    baseline_confidence: float = Field(..., ge=0.0, le=1.0)
    baseline_rationale: str = Field(..., min_length=20, description="Brief explanation.")


# ============================================================================
# Section 2: Image loading helper
# ============================================================================

def _load_image_b64(path: str | Path) -> tuple[str, str]:
    """Return (base64_data, mime_type) for a patent image file."""
    p = Path(path)
    suffix = p.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/png")
    data = base64.b64encode(p.read_bytes()).decode("utf-8")
    return data, mime


def _build_image_parts(image_path: str | Path) -> list:
    """Build google-genai image Part for a single image."""
    data, mime = _load_image_b64(image_path)
    if _HAS_GEMINI:
        return [genai_types.Part.from_bytes(data=base64.b64decode(data), mime_type=mime)]
    return []


# ============================================================================
# Section 3: M5 — visual faithfulness probe
# ============================================================================

_M5_EXTRACT_SYSTEM = """\
You are a design-patent examiner specializing in visual analysis.
Extract every verifiable perceptual claim from the provided VLM rationale.
A perceptual claim is a statement asserting that two patent drawings share
or differ in a specific visual feature (shape, proportion, style, etc.).
Return ONLY claims that can in principle be confirmed or refuted by looking
at the images. Do NOT include legal conclusions or paraphrases of opinions."""

_M5_VERIFY_SYSTEM = """\
You are a design-patent examiner. You are given:
  1. Patent drawing A (source design)
  2. Patent drawing B (target design)
  3. A list of perceptual claims made by another AI about these drawings.

For each claim, inspect the images carefully and decide:
  - "supported":     the images clearly back the claim
  - "contradicted":  the images clearly refute the claim
  - "unverifiable":  you cannot tell from these images alone

Be conservative: mark as "unverifiable" if you are not confident."""


def verify_claim_against_images(
    row: pd.Series,
    cfg: LLMConfig | None = None,
) -> VisualFaithfulnessScore:
    """M5 pipeline for one (source, target) pair.

    Step 1 — extract perceptual claims from rationale text (text-only call).
    Step 2 — verify each claim against images (multimodal call).
    """
    if cfg is None:
        cfg = DEFAULT_CONFIGS["gemini-flash"]

    if not _HAS_GEMINI:
        raise RuntimeError("google-genai not installed")

    client = genai.Client(api_key=os.environ[cfg.api_key_env])
    budget = _THINKING_BUDGET_MAP.get(cfg.thinking_level, 2048)
    rationale = str(row.get("reason", ""))
    source    = str(row["source"])
    target    = str(row["target"])

    # ── Step 1: extract claims from rationale text ────────────────────────────
    def _call_extract():
        _limiter.wait_for_slot()
        t_start = time.time()
        user_msg = (
            f"Rationale:\n\"\"\"\n{rationale}\n\"\"\"\n\n"
            "Extract all verifiable perceptual claims as a JSON list."
        )
        try:
            gcfg = genai_types.GenerateContentConfig(
                system_instruction=_M5_EXTRACT_SYSTEM,
                response_mime_type="application/json",
                response_schema=ClaimExtractionResult,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
        except TypeError:
            gcfg = genai_types.GenerateContentConfig(
                system_instruction=_M5_EXTRACT_SYSTEM,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
        resp = client.models.generate_content(
            model=cfg.model, contents=user_msg, config=gcfg,
        )
        elapsed = time.time() - t_start
        usage = resp.usage_metadata
        total = usage.total_token_count if usage else 0
        _limiter.record_request(total)
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
        return resp

    resp1 = _call_extract()
    try:
        extraction = ClaimExtractionResult.model_validate(json.loads(resp1.text))
    except Exception:
        parsed = _extract_json(resp1.text)
        extraction = ClaimExtractionResult.model_validate(parsed)

    if not extraction.claims:
        return VisualFaithfulnessScore(
            source=source, target=target,
            n_claims=0, n_supported=0, n_contradicted=0, n_unverifiable=0,
            upr=0.0, m5_score=1.0,
            claims_json=extraction.model_dump_json(),
        )

    # ── Step 2: verify claims against images ─────────────────────────────────
    src_img = row.get("source_image", "")
    tgt_img = row.get("target_image", "")

    claims_text = "\n".join(
        f"{i+1}. [{c.facet}] {c.claim_text}"
        for i, c in enumerate(extraction.claims)
    )

    def _call_verify():
        _limiter.wait_for_slot()
        t_start = time.time()

        contents: list = []
        for img_path in [src_img, tgt_img]:
            if img_path and Path(img_path).exists():
                try:
                    data, mime = _load_image_b64(img_path)
                    contents.append(
                        genai_types.Part.from_bytes(
                            data=base64.b64decode(data), mime_type=mime
                        )
                    )
                except Exception as e:
                    print(f"  [WARN] 画像読み込み失敗 {img_path}: {e}", flush=True)

        contents.append(
            f"Claims to verify:\n{claims_text}\n\n"
            "Return verdicts as JSON."
        )

        try:
            gcfg = genai_types.GenerateContentConfig(
                system_instruction=_M5_VERIFY_SYSTEM,
                response_mime_type="application/json",
                response_schema=ImageVerificationResult,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
        except TypeError:
            gcfg = genai_types.GenerateContentConfig(
                system_instruction=_M5_VERIFY_SYSTEM,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
        resp = client.models.generate_content(
            model=cfg.model, contents=contents, config=gcfg,
        )
        elapsed = time.time() - t_start
        usage = resp.usage_metadata
        total = usage.total_token_count if usage else 0
        _limiter.record_request(total)
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
        return resp

    resp2 = _call_verify()
    try:
        verification = ImageVerificationResult.model_validate(json.loads(resp2.text))
    except Exception:
        parsed = _extract_json(resp2.text)
        verification = ImageVerificationResult.model_validate(parsed)

    # ── Aggregate UPR ─────────────────────────────────────────────────────────
    n_claims       = len(extraction.claims)
    n_supported    = sum(1 for v in verification.verdicts if v.verdict == "supported")
    n_contradicted = sum(1 for v in verification.verdicts if v.verdict == "contradicted")
    n_unverifiable = sum(1 for v in verification.verdicts if v.verdict == "unverifiable")
    upr            = (n_contradicted + n_unverifiable) / max(n_claims, 1)
    m5_score       = max(0.0, 1.0 - upr)

    return VisualFaithfulnessScore(
        source=source, target=target,
        n_claims=n_claims,
        n_supported=n_supported,
        n_contradicted=n_contradicted,
        n_unverifiable=n_unverifiable,
        upr=upr,
        m5_score=m5_score,
        claims_json=extraction.model_dump_json(),
    )


# ============================================================================
# Section 4: B — VLM-direct baseline
# ============================================================================

_BASELINE_SYSTEM = """\
You are a design-patent examiner applying the "ordinary observer test"
(Egyptian Goddess v. Swisa, 543 F.3d 665 (Fed. Cir. 2008)).

You are given two patent drawings (Design A and Design B).
Decide whether an ordinary observer would regard the overall visual
appearances as substantially similar.

Do NOT read any prior rationale — judge from the images alone.

Answer with:
  - baseline_judgment: "Yes" (substantially similar) or "No" (not similar)
  - baseline_confidence: float 0–1
  - baseline_rationale: brief explanation (mention specific visual features)
"""


def run_baseline_b_one_pair(
    row: pd.Series,
    cfg: LLMConfig | None = None,
) -> BaselineResult:
    """B: VLM-direct baseline for one (source, target) pair."""
    if cfg is None:
        cfg = DEFAULT_CONFIGS["gemini-flash"]

    if not _HAS_GEMINI:
        raise RuntimeError("google-genai not installed")

    client = genai.Client(api_key=os.environ[cfg.api_key_env])
    budget = _THINKING_BUDGET_MAP.get(cfg.thinking_level, 2048)
    source = str(row["source"])
    target = str(row["target"])

    def _call():
        _limiter.wait_for_slot()
        t_start = time.time()

        contents: list = []
        for label, col in [("Design A", "source_image"), ("Design B", "target_image")]:
            img_path = row.get(col, "")
            if img_path and Path(img_path).exists():
                try:
                    data, mime = _load_image_b64(img_path)
                    contents.append(f"[{label}]")
                    contents.append(
                        genai_types.Part.from_bytes(
                            data=base64.b64decode(data), mime_type=mime
                        )
                    )
                except Exception as e:
                    print(f"  [WARN] 画像読み込み失敗 {img_path}: {e}", flush=True)
                    contents.append(f"[{label}: image unavailable]")
            else:
                contents.append(f"[{label}: image not found at {img_path}]")

        contents.append(
            "Compare Design A and Design B. Return your verdict as JSON."
        )

        try:
            gcfg = genai_types.GenerateContentConfig(
                system_instruction=_BASELINE_SYSTEM,
                response_mime_type="application/json",
                response_schema=BaselineResult,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
        except TypeError:
            gcfg = genai_types.GenerateContentConfig(
                system_instruction=_BASELINE_SYSTEM,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
        resp = client.models.generate_content(
            model=cfg.model, contents=contents, config=gcfg,
        )
        elapsed = time.time() - t_start
        usage = resp.usage_metadata
        total = usage.total_token_count if usage else 0
        _limiter.record_request(total)
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
        return resp

    resp = _call()
    try:
        result = BaselineResult.model_validate(
            {**json.loads(resp.text), "source": source, "target": target}
        )
    except Exception:
        parsed = _extract_json(resp.text)
        parsed.update({"source": source, "target": target})
        result = BaselineResult.model_validate(parsed)
    return result


# ============================================================================
# Section 5: batch runners
# ============================================================================

def run_m5_batch(
    df: pd.DataFrame,
    output_csv: Path,
    cfg: LLMConfig | None = None,
    *,
    mode: str = "skip",
) -> pd.DataFrame:
    """Run M5 probe on all rows of df."""
    done: set[tuple] = set()
    if mode == "skip" and output_csv.exists():
        prev = pd.read_csv(output_csv)
        done = set(zip(prev["source"], prev["target"]))
        print(f"M5 スキップモード: {len(done)} 件処理済み", flush=True)
    else:
        print(f"M5 上書きモード: 全 {len(df)} 件を処理します", flush=True)

    todo = df[~df.apply(lambda r: (r["source"], r["target"]) in done, axis=1)]
    if todo.empty:
        print("M5: 処理対象なし", flush=True)
        return pd.read_csv(output_csv) if output_csv.exists() else pd.DataFrame()

    results: list[dict] = []
    total = len(todo)
    with tqdm(total=total, desc="M5 probe", unit="pair") as pbar:
        for i, (_, row) in enumerate(todo.iterrows(), 1):
            try:
                score = verify_claim_against_images(row, cfg)
                results.append(score.model_dump())
                tqdm.write(
                    f"  [{i}/{total}] {row['source']} → {row['target']}"
                    f"  m5:{score.m5_score:.3f}  claims:{score.n_claims}"
                    f"  sup:{score.n_supported}  con:{score.n_contradicted}"
                )
                pbar.set_postfix(m5=f"{score.m5_score:.3f}", claims=score.n_claims)
            except Exception as e:
                _write_error_log(f"M5 error {row['source']}→{row['target']}: {e}")
                tqdm.write(f"  [{i}/{total}] {row['source']}→{row['target']}  ERROR: {e}")
            pbar.update(1)

    new_df = pd.DataFrame(results)
    if mode == "skip" and output_csv.exists() and not pd.read_csv(output_csv).empty:
        new_df = pd.concat([pd.read_csv(output_csv), new_df], ignore_index=True)
    new_df.to_csv(output_csv, index=False)
    print(f"M5 saved: {output_csv} ({len(new_df)} rows)", flush=True)
    return new_df


def run_baseline_batch(
    df: pd.DataFrame,
    output_csv: Path,
    cfg: LLMConfig | None = None,
    *,
    mode: str = "skip",
) -> pd.DataFrame:
    """Run baseline B on all rows of df."""
    done: set[tuple] = set()
    if mode == "skip" and output_csv.exists():
        prev = pd.read_csv(output_csv)
        done = set(zip(prev["source"], prev["target"]))
        print(f"Baseline B スキップモード: {len(done)} 件処理済み", flush=True)
    else:
        print(f"Baseline B 上書きモード: 全 {len(df)} 件を処理します", flush=True)

    todo = df[~df.apply(lambda r: (r["source"], r["target"]) in done, axis=1)]
    if todo.empty:
        print("Baseline B: 処理対象なし", flush=True)
        return pd.read_csv(output_csv) if output_csv.exists() else pd.DataFrame()

    results: list[dict] = []
    total = len(todo)
    with tqdm(total=total, desc="Baseline B", unit="pair") as pbar:
        for i, (_, row) in enumerate(todo.iterrows(), 1):
            try:
                br = run_baseline_b_one_pair(row, cfg)
                results.append(br.model_dump())
                tqdm.write(
                    f"  [{i}/{total}] {row['source']} → {row['target']}"
                    f"  判定:{br.baseline_judgment}  conf:{br.baseline_confidence:.3f}"
                )
                pbar.set_postfix(判定=br.baseline_judgment, conf=f"{br.baseline_confidence:.3f}")
            except Exception as e:
                _write_error_log(f"Baseline B error {row['source']}→{row['target']}: {e}")
                tqdm.write(f"  [{i}/{total}] {row['source']}→{row['target']}  ERROR: {e}")
            pbar.update(1)

    new_df = pd.DataFrame(results)
    if mode == "skip" and output_csv.exists() and not pd.read_csv(output_csv).empty:
        new_df = pd.concat([pd.read_csv(output_csv), new_df], ignore_index=True)
    new_df.to_csv(output_csv, index=False)
    print(f"Baseline B saved: {output_csv} ({len(new_df)} rows)", flush=True)
    return new_df


# ============================================================================
# Section 6: CLI
# ============================================================================

_INPUT_CSV  = Path("/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv")
_OUTPUT_DIR = _INPUT_CSV.parent / "reasoning"


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="M5 visual faithfulness probe + B baseline")
    parser.add_argument("--module",    choices=["m5", "baseline", "both"], default="both")
    parser.add_argument("--model",     default="gemini-flash",
                        help="Model alias: gemini-flash")
    parser.add_argument("--mode",      choices=["skip", "overwrite"], default="skip",
                        help="skip: 処理済みをスキップ（デフォルト）/ overwrite: 全件上書き")
    parser.add_argument("--no-debug",   action="store_true",
                        help="APIキー・モデル名の起動時表示を抑制")
    parser.add_argument("--pilot-only", action="store_true",
                        help="Only process rows with _stratum column set (pilot sample)")
    args = parser.parse_args()

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(_INPUT_CSV)
    if args.pilot_only and "_stratum" in df.columns:
        df = df[df["_stratum"].notna()]
        print(f"Pilot-only: {len(df)} rows", flush=True)

    cfg = DEFAULT_CONFIGS[args.model] if args.model in DEFAULT_CONFIGS else DEFAULT_CONFIGS["gemini-flash"]

    if not args.no_debug:
        api_key = os.environ.get(cfg.api_key_env, "")
        masked  = api_key[:4] + "****" + api_key[-4:] if len(api_key) > 8 else "****"
        print(f"[debug] {cfg.api_key_env} : {masked}", flush=True)
        print(f"[debug] model          : {cfg.model}", flush=True)
        print(f"[debug] thinking_level : {cfg.thinking_level}", flush=True)

    if args.module in ("m5", "both"):
        run_m5_batch(df, _OUTPUT_DIR / "m5_scores.csv", cfg, mode=args.mode)

    if args.module in ("baseline", "both"):
        run_baseline_batch(df, _OUTPUT_DIR / "baseline_b.csv", cfg, mode=args.mode)


if __name__ == "__main__":
    main()