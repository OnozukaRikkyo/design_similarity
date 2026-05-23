"""
patent_rationale_pms.py
=======================

Perfect-Match Score (PMS) pipeline for design-patent VLM rationales.

A rationale-centric, LLM-based estimator of visual equivalence between
patent line drawings, grounded in 2025-2026 NLP literature.

Design choices documented inline with citations:
  - Reasoning-first Pydantic field ordering (Castillo 2024; techsy.io 2026)
  - Two-step fallback for high-stakes cases (DICE: Pan et al. 2025;
    "The Format Tax": Shorten et al. arXiv 2604.03616, 2026)
  - Paraphrase self-consistency via Self-Harmony (ICLR 2026, arXiv 2511.01191)
  - Position-bias mitigation via (A,B)/(B,A) swap (Shi et al. IJCNLP 2025)
  - Krippendorff's alpha for cross-LLM IRR
    (Rating Roulette, EMNLP 2025; Guerdan et al. 2025)
  - Hierarchical CoT (Hi-CoT, Huang et al. arXiv 2604.00130, 2026)
  - WIPO-grounded ontology, following PatentScore (Yoo et al. EMNLP 2025)

Gemini API 実装は design_similarity.py のパターンに準拠:
  - RateLimiter: RPM/TPM/RPD スライディングウィンドウ（スレッドセーフ）
  - thinking_level -> thinking_budget 変換マップ
  - response_schema TypeError fallback
  - MIN_INTERVAL_SEC 後待機 + 429 リトライ
  - 日付別エラーログファイル

Requirements:
  pip install pydantic>=2.5 google-genai>=1.0 pandas tqdm scipy
  (instructor / krippendorff / anthropic / openai は任意)

Author: Soichi
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
import statistics
import sys
import time
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).parents[2] / ".env")

import pandas as pd
from pydantic import BaseModel, Field, ValidationError, model_validator
from tqdm import tqdm

# Optional imports — graceful degradation if not installed.
try:
    from google import genai
    from google.genai import types as genai_types
    _HAS_GEMINI = True
except ImportError:
    _HAS_GEMINI = False

try:
    import instructor
    _HAS_INSTRUCTOR = True
except ImportError:
    _HAS_INSTRUCTOR = False

try:
    import krippendorff
    _HAS_KRIPPENDORFF = True
except ImportError:
    _HAS_KRIPPENDORFF = False


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
log = logging.getLogger("patent_rationale_pms")


# ============================================================================
# API 制限定数 (Gemini 無料ティア / design_similarity.py 準拠)
# ============================================================================

RPM_LIMIT        = 15
TPM_LIMIT        = 250_000
RPD_DAILY        = 500
MIN_INTERVAL_SEC = 1.0
QUOTA_RESET_TIME = "17:01"

# thinking_level エイリアス → thinking_budget 変換マップ
_THINKING_BUDGET_MAP: dict[str, int] = {
    "minimal": 512,
    "low":    1024,
    "medium": 2048,
    "high":   8192,
}


# ============================================================================
# Section 1: WIPO-grounded facet ontology
# ============================================================================

class Facet(str, Enum):
    """Visual facets a rationale may discuss about a design pair.

    Categories chosen to span the dimensions known to matter under the
    "ordinary observer test" (Egyptian Goddess v. Swisa, 543 F.3d 665
    (Fed. Cir. 2008)) and to be discriminable by VLM rationale text and
    human design examiners.
    """
    GLOBAL_SHAPE   = "GlobalShape"
    PROPORTIONS    = "Proportions"
    PART_LAYOUT    = "PartLayout"
    LOCAL_JUNCTION = "LocalJunction"
    LINE_STYLE     = "LineStyle"
    TEXTURE        = "Texture"
    ORNAMENTATION  = "Ornamentation"
    ORIENTATION    = "Orientation"
    UNCATEGORIZED  = "Uncategorized"


class FacetState(str, Enum):
    """Equivalence state per facet (graded, following Deshpande et al. 2023)."""
    IDENTICAL              = "Identical"
    MINOR_DIFFERENCE       = "Minor_Difference"
    SIGNIFICANT_DIFFERENCE = "Significant_Difference"
    NOT_DISCUSSED          = "Not_Discussed"


# ============================================================================
# Section 2: Pydantic schemas (reasoning-first ordering)
# ============================================================================

class FacetEvaluation(BaseModel):
    """One facet's evaluation extracted from a single rationale.

    Field order matters: reasoning -> state -> evidence -> confidence.
    Puts reasoning first so the LLM is forced to commit to reasoning
    before producing the answer (Castillo 2024; "The Format Tax" 2026).
    """
    facet_reasoning: str = Field(
        ...,
        min_length=20,
        description=(
            "Step-by-step reasoning analyzing what the rationale says about "
            "this specific visual facet. Quote phrases from the rationale, "
            "discuss whether it implies identity or difference, and flag "
            "ambiguity. Do NOT conclude yet — just analyze."
        ),
    )
    facet: Facet = Field(..., description="Which visual facet this evaluation concerns.")
    state: FacetState = Field(
        ...,
        description=(
            "Equivalence verdict for this facet. Use NOT_DISCUSSED if the "
            "rationale does not mention this facet — do NOT guess."
        ),
    )
    evidence_span: str = Field(
        default="",
        description=(
            "The exact contiguous substring of the original rationale that "
            "directly supports the state. Empty string only if state == NOT_DISCUSSED."
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in this state.")

    @model_validator(mode="after")
    def _check_evidence_when_discussed(self) -> "FacetEvaluation":
        if self.state != FacetState.NOT_DISCUSSED and not self.evidence_span.strip():
            raise ValueError(
                f"evidence_span must be non-empty when state={self.state}"
            )
        return self


class RationaleGraph(BaseModel):
    """M1 output: structured aspect-triple decomposition of one rationale."""
    overall_reasoning: str = Field(
        ...,
        min_length=50,
        description=(
            "Step-by-step analysis of the rationale as a whole, BEFORE "
            "extracting per-facet evaluations. Identify (1) which facets "
            "the rationale discusses, (2) whether it is internally consistent, "
            "(3) any contextual qualifiers like 'mirror', 'rotated', 'except for'."
        ),
    )
    consistency_flag: Literal[
        "consistent", "internally_contradictory", "ambiguous"
    ] = Field(..., description="Does the rationale contradict itself?")
    aspects: list[FacetEvaluation] = Field(
        default_factory=list,
        description=(
            "Per-facet evaluations. Only include facets actually discussed; "
            "do NOT add NOT_DISCUSSED placeholders for missing facets."
        ),
    )


class PerfectMatchScore(BaseModel):
    """M2 output: NLI-style score that rationale entails visual identity."""
    nli_reasoning: str = Field(
        ...,
        min_length=40,
        description=(
            "Step-by-step NLI reasoning. Treat the rationale as PREMISE "
            "and the claim 'the two images depict visually identical line "
            "drawings of the same design with no discernible differences' "
            "as HYPOTHESIS. Cite supporting or contradicting parts."
        ),
    )
    nli_label: Literal[
        "strong_entailment",
        "weak_entailment",
        "neutral",
        "weak_contradiction",
        "strong_contradiction",
    ] = Field(..., description="Five-class NLI verdict.")
    match_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Probability the two images are visually identical, calibrated: "
            "strong_entailment>=0.85; weak_entailment=0.55-0.85; "
            "neutral=0.40-0.55; weak_contradiction=0.15-0.40; "
            "strong_contradiction<=0.15."
        ),
    )


class Paraphrase(BaseModel):
    """M3 helper: one semantically-equivalent rephrase (Self-Harmony ICLR 2026)."""
    paraphrase_reasoning: str = Field(
        ...,
        description="Brief reasoning about what to preserve and what to vary.",
    )
    paraphrased_text: str = Field(
        ...,
        min_length=20,
        description=(
            "A paraphrase of the original rationale that preserves all "
            "factual claims but changes wording and structure substantially."
        ),
    )


# ============================================================================
# Section 3: Prompts
# ============================================================================

M1_SYSTEM = """\
You are a senior US design-patent examiner with 15 years of experience \
adjudicating the "ordinary observer" test under Egyptian Goddess v. Swisa \
(543 F.3d 665, Fed. Cir. 2008). You are NOT generating new opinions about \
the images — you are PARSING an existing VLM rationale into a structured \
graph. Treat the rationale as the ONLY source of truth.

Strict rules:
1. Do not invent facets the rationale does not mention.
2. For each discussed facet, find the exact substring evidence.
3. Treat qualifiers carefully:
   - "despite identical X" — identity for X, but the rationale is setting up a contradiction.
   - "mirror image" — ORIENTATION is Significant_Difference.
   - "rotated" — ORIENTATION is Minor_Difference unless rotation is trivial.
   - "appears" / "seems" / "likely" — lower confidence.
4. Output strictly the requested JSON. Never include prose outside the JSON.
"""

M2_SYSTEM = """\
You are an NLP annotator performing five-class natural language inference (NLI). \
Treat the VLM rationale as PREMISE and the claim \
"The two images depict visually identical line drawings of the same design with \
no discernible differences in shape, layout, line style, texture, or ornamentation" \
as HYPOTHESIS.

Important calibration anchors:
- "identical line drawings with no discernible differences" — strong_entailment.
- "same overall shape but differ in dashed lines / control panel / surface texture" \
  — weak_contradiction or strong_contradiction.
- "mirror image" — strong_contradiction (mirror ≠ identical).
- "appears similar but..." — weak_contradiction.
- Pure description without verdict — neutral.

Output strictly the requested JSON.
"""

M3_PARAPHRASE_SYSTEM = """\
You are a faithful paraphraser. Given a VLM rationale about two design \
patent line drawings, produce a paraphrase that:
  - PRESERVES every factual claim about identity, difference, and the \
    visual facets discussed,
  - VARIES sentence structure, lexical choices, ordering of points, and \
    voice (active/passive),
  - DOES NOT add new claims or omit existing ones.

The paraphrase must be semantically equivalent (Self-Harmony, ICLR 2026) \
— a downstream NLI judge should reach the same verdict on it.
"""


def m1_user_prompt(rationale: str) -> str:
    return (
        "Parse this VLM rationale into a structured aspect-triple graph.\n\n"
        f"[Rationale]\n{rationale}\n\n"
        "Follow the schema strictly. Start with overall_reasoning, then "
        "consistency_flag, then aspects (only facets actually discussed)."
    )


def m2_user_prompt(rationale: str) -> str:
    return (
        "Apply five-class NLI.\n\n"
        f"PREMISE (VLM rationale):\n{rationale}\n\n"
        "HYPOTHESIS:\n"
        "The two images depict visually identical line drawings of the same "
        "design with no discernible differences in shape, layout, line style, "
        "texture, or ornamentation.\n\n"
        "Produce nli_reasoning first, then nli_label, then match_probability."
    )


def m3_paraphrase_user_prompt(rationale: str) -> str:
    return (
        "Paraphrase the following rationale faithfully (preserving all "
        "factual claims, varying only surface form).\n\n"
        f"[Rationale]\n{rationale}"
    )


# ============================================================================
# Rate limiter (design_similarity.py パターン)
# ============================================================================

class RateLimiter:
    """スライディングウィンドウ方式のレート制限器。"""

    def __init__(
        self,
        rpm: int = RPM_LIMIT,
        tpm: int = TPM_LIMIT,
        rpd: int = RPD_DAILY,
    ):
        self._rpm       = rpm
        self._tpm       = tpm
        self._rpd       = rpd
        self._req_times: deque[float]             = deque()
        self._tok_times: deque[tuple[float, int]] = deque()
        self._day_count = 0
        self._day_start = time.time()

    def _purge_old(self, window: float = 60.0) -> None:
        now = time.time()
        while self._req_times and now - self._req_times[0] > window:
            self._req_times.popleft()
        while self._tok_times and now - self._tok_times[0][0] > window:
            self._tok_times.popleft()

    def _recent_tokens(self) -> int:
        return sum(t for _, t in self._tok_times)

    def _reset_day_if_needed(self) -> None:
        if time.time() - self._day_start >= 86400:
            self._day_count = 0
            self._day_start = time.time()

    @staticmethod
    def _next_reset_dt() -> datetime:
        h, m  = map(int, QUOTA_RESET_TIME.split(":"))
        now   = datetime.now()
        reset = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if reset <= now:
            reset += timedelta(days=1)
        return reset

    def wait_for_slot(self) -> None:
        """スロットが空くまで待機する。"""
        while True:
            self._reset_day_if_needed()
            self._purge_old()

            if self._day_count >= self._rpd:
                reset_dt = self._next_reset_dt()
                print(
                    f"\n[完了] 本日の上限 {self._rpd} リクエストに達しました。\n"
                    f"  リセット予定: {reset_dt.strftime('%Y-%m-%d %H:%M')} ({QUOTA_RESET_TIME})",
                    flush=True,
                )
                sys.exit(0)

            rpm_ok = len(self._req_times) < self._rpm
            tpm_ok = self._recent_tokens() < self._tpm

            if rpm_ok and tpm_ok:
                now = time.time()
                self._req_times.append(now)
                self._tok_times.append((now, 0))
                self._day_count += 1
                return

            now   = time.time()
            waits = []
            if not rpm_ok:
                waits.append(60.0 - (now - self._req_times[0]))
            if not tpm_ok:
                waits.append(60.0 - (now - self._tok_times[0][0]))
            wait_sec = max(0.1, max(waits))
            print(f"  [rate-limit] {wait_sec:.1f}秒 待機中...", flush=True)
            time.sleep(wait_sec)

    def record_request(self, total_tokens: int = 0) -> None:
        """API 呼び出し後にトークン数を確定する。"""
        if self._tok_times:
            t, _ = self._tok_times[-1]
            self._tok_times[-1] = (t, total_tokens)

    update_tokens = record_request


_limiter = RateLimiter()


# ============================================================================
# エラーログ (design_similarity.py パターン)
# ============================================================================

_ERROR_LOG_DIR = Path(__file__).parent / "log" / "error"


def _write_error_log(context: str, exc: BaseException) -> Path:
    """日付別エラーログファイルに追記する。"""
    _ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = _ERROR_LOG_DIR / f"error_{datetime.now().strftime('%Y%m%d')}.log"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"\n[{datetime.now().isoformat()}]\n")
        f.write(f"context: {context}\n")
        f.write(f"error  : {type(exc).__name__}: {exc}\n")
        f.write(traceback.format_exc())
        f.write("-" * 60 + "\n")
    return log_file


# ============================================================================
# JSON 抽出ヘルパー
# ============================================================================

def _extract_json(raw: str) -> dict:
    """生テキストから JSON オブジェクトを抽出する（マークダウンコードフェンス対応）。"""
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    try:
        start = raw.index("{")
        end   = raw.rindex("}") + 1
        return json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return {}


# ============================================================================
# Section 4: Client abstraction
# ============================================================================

@dataclass
class LLMConfig:
    """Configuration for one LLM judge."""
    name: str
    provider: Literal["gemini", "instructor"]
    model: str
    api_key_env: str
    thinking_level: Literal["minimal", "low", "medium", "high"] = "medium"
    temperature: float = 0.0


# 推奨デフォルト。モデル名が合わない場合は --judge で直接指定可。
DEFAULT_CONFIGS: dict[str, LLMConfig] = {
    "gemini-flash": LLMConfig(
        name="gemini-flash",
        provider="gemini",
        model="gemini-3.1-pro-preview",
        api_key_env="GEMINI_API_KEY",
        thinking_level="medium",
    ),
}


class LLMClient:
    """LLM プロバイダーの差異を隠す薄いラッパー。"""

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._client = self._build_client()

    def _build_client(self):
        if self.cfg.provider == "gemini":
            if not _HAS_GEMINI:
                raise ImportError("google-genai not installed: pip install google-genai")
            api_key = os.environ.get(self.cfg.api_key_env)
            if not api_key:
                raise EnvironmentError(
                    f"{self.cfg.api_key_env} が設定されていません。\n"
                    f"  export {self.cfg.api_key_env}='your-api-key'"
                )
            masked = api_key[:4] + "****" + api_key[-4:] if len(api_key) > 8 else "****"
            print(f"[client] {self.cfg.api_key_env}={masked}  model={self.cfg.model}", flush=True)
            return genai.Client(api_key=api_key)
        elif self.cfg.provider == "instructor":
            if not _HAS_INSTRUCTOR:
                raise ImportError("instructor not installed: pip install instructor")
            return instructor.from_provider(self.cfg.model, async_client=False)
        else:
            raise ValueError(f"Unknown provider: {self.cfg.provider}")

    def parse(
        self,
        *,
        system: str,
        user: str,
        response_model: type[BaseModel],
        max_retries: int = 3,
    ) -> BaseModel:
        """LLM を呼び出して検証済み Pydantic インスタンスを返す。"""
        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                if self.cfg.provider == "gemini":
                    return self._parse_gemini(system, user, response_model)
                else:
                    return self._parse_instructor(system, user, response_model)
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                _write_error_log(
                    f"{self.cfg.name}/{response_model.__name__} attempt {attempt+1}", e
                )
                print(
                    f"  [WARN] {self.cfg.name} parse attempt {attempt+1}/{max_retries} failed: {e}",
                    flush=True,
                )
                time.sleep(2 ** attempt)
            except Exception as e:
                last_err = e
                is_quota = "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e).upper()
                wait = (30 * (2 ** attempt)) if is_quota else (2 ** attempt + random.uniform(0, 1))
                _write_error_log(
                    f"{self.cfg.name}/{response_model.__name__} API error attempt {attempt+1}", e
                )
                print(
                    f"  [WARN] {self.cfg.name} API error attempt {attempt+1}/{max_retries}"
                    f" (wait {wait:.0f}s): {e}",
                    flush=True,
                )
                time.sleep(wait)
        raise RuntimeError(
            f"{self.cfg.name} failed after {max_retries} retries: {last_err}"
        )

    def _parse_gemini(
        self, system: str, user: str, response_model: type[BaseModel]
    ) -> BaseModel:
        """Gemini API 呼び出し（design_similarity.py パターン適用）。

        - thinking_budget 変換 (thinking_level -> int)
        - response_schema: 非対応版への TypeError fallback
        - RateLimiter.wait_for_slot() → API call → record_request()
        - MIN_INTERVAL_SEC 後待機（design_similarity.py 準拠）
        """
        budget = _THINKING_BUDGET_MAP.get(self.cfg.thinking_level, 2048)

        def _call():
            # ① スロット確保（blocking, thread-safe）
            _limiter.wait_for_slot()

            t_start = time.time()

            # ② response_schema 付き設定（非対応版への TypeError fallback あり）
            try:
                cfg = genai_types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=response_model,
                    thinking_config=genai_types.ThinkingConfig(
                        thinking_budget=budget,
                    ),
                )
            except TypeError:
                cfg = genai_types.GenerateContentConfig(
                    system_instruction=system,
                    thinking_config=genai_types.ThinkingConfig(
                        thinking_budget=budget,
                    ),
                )

            resp = self._client.models.generate_content(
                model=self.cfg.model,
                contents=user,
                config=cfg,
            )

            elapsed = time.time() - t_start

            # ③ トークン数を確定（design_similarity.py の record_request 相当）
            usage = resp.usage_metadata
            total = usage.total_token_count if usage else 0
            _limiter.record_request(total)

            # ④ トークンログ（design_similarity.py 準拠）
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

            # ⑤ 待機（design_similarity.py 準拠）
            remaining = MIN_INTERVAL_SEC - elapsed
            if remaining > 0:
                print(f"  [wait] {remaining:.1f}秒 待機中...", flush=True)
                time.sleep(remaining)
            else:
                time.sleep(2)

            return resp

        resp = _call()

        # JSON 抽出・検証
        try:
            parsed = json.loads(resp.text)
        except json.JSONDecodeError:
            parsed = _extract_json(resp.text)

        if not parsed:
            raise ValueError(
                f"JSON の抽出に失敗しました (model={self.cfg.model}): "
                f"{resp.text[:300]}"
            )

        return response_model.model_validate(parsed)

    def _parse_instructor(
        self, system: str, user: str, response_model: type[BaseModel]
    ) -> BaseModel:
        """Instructor 経由の汎用呼び出し（Anthropic / OpenAI 等）。"""
        return self._client.chat.completions.create(
            response_model=response_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            max_retries=1,
            temperature=0.0,
        )


# ============================================================================
# Section 5: Module implementations (M1–M3)
# ============================================================================

def m1_extract_aspects(
    rationale: str, client: LLMClient
) -> RationaleGraph:
    """M1: 構造化側面グラフ抽出（PatentScore / TriSum 準拠）。"""
    return client.parse(
        system=M1_SYSTEM,
        user=m1_user_prompt(rationale),
        response_model=RationaleGraph,
    )


def m2_score_perfect_match(
    rationale: str, client: LLMClient
) -> PerfectMatchScore:
    """M2: ラショナル → 完全一致確率 via NLI（Conditional STS 準拠）。"""
    return client.parse(
        system=M2_SYSTEM,
        user=m2_user_prompt(rationale),
        response_model=PerfectMatchScore,
    )


def m3_paraphrase_consistency(
    rationale: str,
    judge_client: LLMClient,
    paraphraser_client: Optional[LLMClient] = None,
    k: int = 5,
) -> dict:
    """M3: 言い換え誘起 PMS 分散（Self-Harmony ICLR 2026）。

    Returns dict: scores, mean, std, ci_low, ci_high, jsd_signal,
                  n_paraphrases
    """
    paraphraser_client = paraphraser_client or judge_client

    # k 個の言い換えを逐次生成
    paraphrases: list[str] = []
    for _ in range(k):
        try:
            result = paraphraser_client.parse(
                system=M3_PARAPHRASE_SYSTEM,
                user=m3_paraphrase_user_prompt(rationale),
                response_model=Paraphrase,
            )
            paraphrases.append(result.paraphrased_text)
        except Exception as e:
            print(f"  [WARN] 言い換え生成失敗: {e}", flush=True)

    if not paraphrases:
        return {
            "scores": [], "mean": float("nan"), "std": float("nan"),
            "ci_low": float("nan"), "ci_high": float("nan"),
            "jsd_signal": float("nan"), "n_paraphrases": 0,
        }

    # 元のラショナル + 言い換えを M2 でスコアリング（逐次）
    scored: list[float] = []
    for text in [rationale] + paraphrases:
        try:
            r = m2_score_perfect_match(text, judge_client)
            scored.append(r.match_probability)
        except Exception as e:
            print(f"  [WARN] 言い換えスコアリング失敗: {e}", flush=True)

    if len(scored) < 2:
        return {
            "scores": scored,
            "mean": scored[0] if scored else float("nan"),
            "std": float("nan"), "ci_low": float("nan"),
            "ci_high": float("nan"), "jsd_signal": float("nan"),
            "n_paraphrases": len(paraphrases),
        }

    mean = statistics.mean(scored)
    std  = statistics.stdev(scored)

    # 95% ブートストラップ CI
    boot_means = sorted(
        statistics.mean(random.choices(scored, k=len(scored)))
        for _ in range(1000)
    )
    ci_low  = boot_means[24]
    ci_high = boot_means[974]

    return {
        "scores": scored, "mean": mean, "std": std,
        "ci_low": ci_low, "ci_high": ci_high,
        "jsd_signal": std,
        "n_paraphrases": len(paraphrases),
    }


# ============================================================================
# Two-step pattern (DICE, Pan et al. 2025) — ハードケース向け
# ============================================================================

TWOSTEP_FREE_SYSTEM = """\
You are a senior design-patent examiner. Read the VLM rationale and \
write a detailed, careful, NATURAL-LANGUAGE analysis (NOT JSON) of \
whether it implies the two images are visually identical. Discuss:
  1. What identity claims (if any) the rationale makes.
  2. What difference claims (if any) it makes.
  3. Any contextual qualifiers ('mirror', 'rotated', 'despite', 'except').
  4. Whether the rationale is internally consistent.
  5. Your final judgment on a 0–100 'perfect match' scale.

Aim for 200–400 words. Do not output JSON.
"""

TWOSTEP_STRUCT_SYSTEM = """\
You are converting an examiner's natural-language analysis into a \
strict JSON record. Preserve the examiner's judgment exactly. Do not re-judge.
"""


def m2_score_twostep(
    rationale: str, client: LLMClient
) -> PerfectMatchScore:
    """2-step M2: 自由記述 → 構造化（フォーマット税を回避）。"""
    budget = _THINKING_BUDGET_MAP.get(client.cfg.thinking_level, 2048)

    if client.cfg.provider == "gemini":
        def _call_free():
            _limiter.wait_for_slot()
            t_start = time.time()
            cfg = genai_types.GenerateContentConfig(
                system_instruction=TWOSTEP_FREE_SYSTEM,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
            resp = client._client.models.generate_content(
                model=client.cfg.model,
                contents=f"[Rationale]\n{rationale}",
                config=cfg,
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
            return resp.text

        free_text = _call_free()
    else:
        free_resp = client._client.chat.completions.create(
            response_model=None,
            messages=[
                {"role": "system", "content": TWOSTEP_FREE_SYSTEM},
                {"role": "user",   "content": f"[Rationale]\n{rationale}"},
            ],
            temperature=0.0,
        )
        free_text = free_resp.choices[0].message.content

    return client.parse(
        system=TWOSTEP_STRUCT_SYSTEM,
        user=(
            "Examiner's analysis:\n\n" + free_text
            + "\n\nNow output the PerfectMatchScore JSON.\n"
            "Set nli_reasoning to a faithful summary of the analysis "
            "above (do not invent new reasoning)."
        ),
        response_model=PerfectMatchScore,
    )


# ============================================================================
# Position-bias check (Shi et al. IJCNLP 2025)
# ============================================================================

SWAP_SYSTEM = """\
Rewrite the rationale so that wherever it says 'Image A and Image B', \
it says 'Image B and Image A'; wherever it says 'the first/second', \
swap them; wherever it lists differences in order, reverse the order. \
Preserve all factual claims. Return only the rewritten rationale as plain text.
"""


def m2_with_position_bias_check(
    rationale: str, client: LLMClient
) -> dict:
    """M2 + 位置バイアスチェック（swap テスト）。"""
    budget = _THINKING_BUDGET_MAP.get("low", 1024)

    if client.cfg.provider == "gemini":
        def _swap():
            _limiter.wait_for_slot()
            t_start = time.time()
            cfg = genai_types.GenerateContentConfig(
                system_instruction=SWAP_SYSTEM,
                thinking_config=genai_types.ThinkingConfig(thinking_budget=budget),
            )
            resp = client._client.models.generate_content(
                model=client.cfg.model, contents=rationale, config=cfg,
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
            return resp.text

        swapped = _swap()
    else:
        swap_resp = client._client.chat.completions.create(
            response_model=None,
            messages=[
                {"role": "system", "content": SWAP_SYSTEM},
                {"role": "user",   "content": rationale},
            ],
            temperature=0.0,
        )
        swapped = swap_resp.choices[0].message.content

    s_orig = m2_score_perfect_match(rationale, client)
    s_swap = m2_score_perfect_match(swapped, client)

    consistent = (
        s_orig.nli_label == s_swap.nli_label
        and abs(s_orig.match_probability - s_swap.match_probability) < 0.15
    )

    return {
        "original_score":     s_orig.match_probability,
        "original_label":     s_orig.nli_label,
        "swapped_score":      s_swap.match_probability,
        "swapped_label":      s_swap.nli_label,
        "position_consistent": consistent,
        "averaged_score": (
            (s_orig.match_probability + s_swap.match_probability) / 2
            if consistent else float("nan")
        ),
    }


# ============================================================================
# Section 6: PMS aggregation
# ============================================================================

@dataclass
class PMSResult:
    pair_id: str
    pms: float
    confidence: float
    m1_graph: dict
    m2_score: dict
    m3_consistency: dict
    cot_traces: dict
    flags: list[str] = field(default_factory=list)


def _isnan(x) -> bool:
    return x != x


def compute_pms(
    m2: PerfectMatchScore,
    m3: dict,
    m1: RationaleGraph,
) -> tuple[float, float, list[str]]:
    """M1/M2/M3 から PMS を集計する（事前登録済み数式）。

    PMS = clip(mean_p * (1 - std_penalty) * (1 - consistency_penalty), 0, 1)

    - mean_p          = M3 mean (M2 score にフォールバック)
    - std_penalty     = min(1, M3 std * 2)
    - consistency_penalty: M1 internally_contradictory → 0.4; ambiguous → 0.2
    """
    flags: list[str] = []

    mean_p = (
        m3.get("mean")
        if not _isnan(m3.get("mean", float("nan")))
        else m2.match_probability
    )

    std = m3.get("std", 0.0)
    if _isnan(std):
        std = 0.0
        flags.append("M3_unavailable")
    std_penalty = min(1.0, std * 2.0)
    if std > 0.20:
        flags.append("M3_high_variance")

    if m1.consistency_flag == "internally_contradictory":
        consistency_penalty = 0.4
        flags.append("M1_internally_contradictory")
    elif m1.consistency_flag == "ambiguous":
        consistency_penalty = 0.2
        flags.append("M1_ambiguous")
    else:
        consistency_penalty = 0.0

    pms        = max(0.0, min(1.0, mean_p * (1 - std_penalty) * (1 - consistency_penalty)))
    confidence = max(0.0, 1.0 - std_penalty - consistency_penalty)

    return pms, confidence, flags


# ============================================================================
# Section 7: Pipeline orchestration
# ============================================================================

def process_single_pair(
    pair_id: str,
    rationale: str,
    judge: LLMClient,
    paraphraser: Optional[LLMClient] = None,
    *,
    use_twostep: bool = False,
    paraphrase_k: int = 5,
    do_position_check: bool = False,
) -> PMSResult:
    """1 ペアに M1-M3 を実行して PMSResult を返す。"""
    paraphraser = paraphraser or judge

    m1 = m1_extract_aspects(rationale, judge)
    m2 = (
        m2_score_twostep(rationale, judge)
        if use_twostep
        else m2_score_perfect_match(rationale, judge)
    )

    m3 = m3_paraphrase_consistency(
        rationale, judge, paraphraser, k=paraphrase_k
    )

    position_info: dict = {}
    if do_position_check:
        position_info = m2_with_position_bias_check(rationale, judge)
        if not position_info.get("position_consistent", True):
            print(f"  位置不整合: {pair_id}", flush=True)

    pms, confidence, flags = compute_pms(m2, m3, m1)
    if position_info and not position_info.get("position_consistent", True):
        flags.append("position_inconsistent")

    cot_traces = {
        "m1_overall_reasoning": m1.overall_reasoning,
        "m1_per_facet_reasoning": [
            {"facet": a.facet.value, "reasoning": a.facet_reasoning}
            for a in m1.aspects
        ],
        "m2_nli_reasoning": m2.nli_reasoning,
        "position_info": position_info,
    }

    return PMSResult(
        pair_id=pair_id,
        pms=pms,
        confidence=confidence,
        m1_graph=m1.model_dump(),
        m2_score=m2.model_dump(),
        m3_consistency=m3,
        cot_traces=cot_traces,
        flags=flags,
    )


def run_batch(
    df: pd.DataFrame,
    judge: LLMClient,
    paraphraser: Optional[LLMClient] = None,
    *,
    rationale_col: str = "reason",
    id_col_source: str = "source",
    id_col_target: str = "target",
    use_twostep: bool = False,
    paraphrase_k: int = 5,
    do_position_check: bool = False,
) -> list[PMSResult]:
    """CSV 全行を逐次処理する。"""
    results: list[PMSResult] = []
    total = len(df)
    with tqdm(total=total, desc="PMS pipeline", unit="pair") as pbar:
        for i, (_, row) in enumerate(df.iterrows(), 1):
            pair_id = f"{row[id_col_source]}__{row[id_col_target]}"
            try:
                result = process_single_pair(
                    pair_id=pair_id,
                    rationale=str(row[rationale_col]),
                    judge=judge,
                    paraphraser=paraphraser,
                    use_twostep=use_twostep,
                    paraphrase_k=paraphrase_k,
                    do_position_check=do_position_check,
                )
                results.append(result)
                nli   = result.m2_score.get("nli_label", "?")
                flags = ",".join(result.flags) if result.flags else "-"
                tqdm.write(
                    f"  [{i}/{total}] {row[id_col_source]} → {row[id_col_target]}"
                    f"  PMS:{result.pms:.3f}  NLI:{nli}  flags:{flags}"
                )
                pbar.set_postfix(PMS=f"{result.pms:.3f}", NLI=nli)
            except Exception as e:
                tqdm.write(f"  [{i}/{total}] {pair_id}  ERROR: {e}")
                results.append(PMSResult(
                    pair_id=pair_id,
                    pms=float("nan"),
                    confidence=0.0,
                    m1_graph={},
                    m2_score={},
                    m3_consistency={},
                    cot_traces={"error": str(e)},
                    flags=["processing_failed"],
                ))
            pbar.update(1)
    return results


# ============================================================================
# Section 8: M4 cross-LLM ensemble (optional)
# ============================================================================

def m4_cross_llm_pms(
    rationale: str,
    judges: list[LLMClient],
    paraphraser: Optional[LLMClient] = None,
    *,
    paraphrase_k: int = 3,
) -> dict:
    """M4: 複数 LLM アンサンブル（Guerdan et al. 2025 準拠）。"""
    results: list[PMSResult] = []
    for j in judges:
        result = process_single_pair(
            pair_id="ensemble",
            rationale=rationale,
            judge=j,
            paraphraser=paraphraser or j,
            paraphrase_k=paraphrase_k,
        )
        results.append(result)

    pms_values = [r.pms for r in results if not _isnan(r.pms)]
    if len(pms_values) < 2:
        return {"per_judge": results, "aggregated_pms": float("nan")}

    alpha = float("nan")
    if _HAS_KRIPPENDORFF:
        nli_labels = [r.m2_score.get("nli_label", "") for r in results]
        alpha = krippendorff.alpha(
            reliability_data=[nli_labels],
            level_of_measurement="nominal",
        )

    return {
        "per_judge": [
            {"judge": j.cfg.name, "pms": r.pms, "nli": r.m2_score.get("nli_label")}
            for j, r in zip(judges, results)
        ],
        "aggregated_pms": statistics.median(pms_values),
        "krippendorff_alpha_nli": alpha,
    }


# ============================================================================
# Section 9: Results -> DataFrame
# ============================================================================

def results_to_dataframe(
    df: pd.DataFrame, results: list[PMSResult]
) -> pd.DataFrame:
    """入力 DataFrame に PMS 結果カラムを付与する。"""
    enriched = df.copy()
    by_pair  = {r.pair_id: r for r in results}

    cols: dict[str, list] = {
        "pms": [], "pms_confidence": [],
        "m2_match_prob": [], "m2_nli_label": [],
        "m1_consistency_flag": [],
        "m3_paraphrase_mean": [], "m3_paraphrase_std": [],
        "cot_m1_reasoning": [], "cot_m2_nli_reasoning": [],
        "flags": [],
    }

    for _, row in enriched.iterrows():
        pair_id = f"{row['source']}__{row['target']}"
        r = by_pair.get(pair_id)
        if r is None:
            for lst in cols.values():
                lst.append(None)
            continue
        cols["pms"].append(r.pms)
        cols["pms_confidence"].append(r.confidence)
        cols["m2_match_prob"].append(r.m2_score.get("match_probability"))
        cols["m2_nli_label"].append(r.m2_score.get("nli_label"))
        cols["m1_consistency_flag"].append(r.m1_graph.get("consistency_flag"))
        cols["m3_paraphrase_mean"].append(r.m3_consistency.get("mean"))
        cols["m3_paraphrase_std"].append(r.m3_consistency.get("std"))
        cols["cot_m1_reasoning"].append(r.cot_traces.get("m1_overall_reasoning"))
        cols["cot_m2_nli_reasoning"].append(r.cot_traces.get("m2_nli_reasoning"))
        cols["flags"].append(",".join(r.flags))

    for name, lst in cols.items():
        enriched[name] = lst

    return enriched.sort_values("pms", ascending=False).reset_index(drop=True)


# ============================================================================
# Section 10: CLI entry point
# ============================================================================

def _run(
    *,
    input_csv: str,
    output_csv: str,
    judge_name: str = "gemini-flash",
    paraphraser_name: Optional[str] = None,
    use_twostep: bool = False,
    paraphrase_k: int = 5,
    do_position_check: bool = False,
    mode: str = "skip",
    debug: bool = False,
    sample_n: Optional[int] = None,
    sample_seed: int = 42,
) -> None:
    df = pd.read_csv(input_csv)
    out_path = Path(output_csv)
    done_pairs: set[tuple[str, str]] = set()

    if mode == "skip" and out_path.exists():
        done_df    = pd.read_csv(out_path)
        done_pairs = set(zip(
            done_df["source"].astype(str), done_df["target"].astype(str)
        ))
        print(f"スキップモード: {len(done_pairs)} 件処理済み → スキップ", flush=True)
    else:
        print(f"上書きモード: 全 {len(df)} 件を処理します", flush=True)

    if sample_n is not None and sample_n < len(df):
        df = df.sample(sample_n, random_state=sample_seed).reset_index(drop=True)

    pending = df[
        ~df.apply(
            lambda r: (str(r["source"]), str(r["target"])) in done_pairs, axis=1
        )
    ].reset_index(drop=True)

    if pending.empty:
        print("処理対象なし。", flush=True)
        return

    print(f"処理対象: {len(pending)} 件", flush=True)

    judge_cfg = DEFAULT_CONFIGS.get(judge_name) or LLMConfig(
        name=judge_name, provider="gemini", model=judge_name,
        api_key_env="GEMINI_API_KEY",
    )

    if debug:
        api_key = os.environ.get(judge_cfg.api_key_env, "")
        masked  = api_key[:4] + "****" + api_key[-4:] if len(api_key) > 8 else "****"
        print(f"[debug] {judge_cfg.api_key_env} : {masked}", flush=True)
        print(f"[debug] model          : {judge_cfg.model}", flush=True)
        print(f"[debug] thinking_level : {judge_cfg.thinking_level}", flush=True)

    judge      = LLMClient(judge_cfg)
    paraphraser = (
        LLMClient(DEFAULT_CONFIGS[paraphraser_name])
        if paraphraser_name and paraphraser_name in DEFAULT_CONFIGS
        else None
    )

    results = run_batch(
        pending, judge, paraphraser,
        use_twostep=use_twostep,
        paraphrase_k=paraphrase_k,
        do_position_check=do_position_check,
    )

    new_df = results_to_dataframe(pending, results)

    if mode == "skip" and out_path.exists() and done_pairs:
        old_df   = pd.read_csv(out_path)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined.to_csv(output_csv, index=False)
    print(f"保存: {output_csv} ({len(combined)} 行)", flush=True)

    json_mode = "a" if mode == "skip" else "w"
    json_path = Path(output_csv).with_suffix(".pms.jsonl")
    with json_path.open(json_mode) as f:
        for r in results:
            f.write(json.dumps({
                "pair_id":        r.pair_id,
                "pms":            r.pms,
                "confidence":     r.confidence,
                "flags":          r.flags,
                "m1_graph":       r.m1_graph,
                "m2_score":       r.m2_score,
                "m3_consistency": r.m3_consistency,
                "cot_traces":     r.cot_traces,
            }, default=str) + "\n")
    print(f"JSONL 保存: {json_path}", flush=True)


_INPUT_CSV  = Path("/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv")
_OUTPUT_DIR = _INPUT_CSV.parent / "reasoning"
_OUTPUT_CSV = _OUTPUT_DIR / "pms_results.csv"


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--judge",          default="gemini-flash",
                   help="モデルエイリアスまたは正式モデル名")
    p.add_argument("--paraphraser",    default=None,
                   help="M3 言い換え用モデル（省略時は --judge と同じ）")
    p.add_argument("--twostep",        action="store_true",
                   help="M2 を 2-step (自由記述 → 構造化) で実行")
    p.add_argument("--paraphrase-k",   type=int, default=5, help="M3 言い換え数")
    p.add_argument("--position-check", action="store_true",
                   help="位置バイアスチェック (swap テスト) を追加")
    p.add_argument("--mode",           choices=["skip", "overwrite"], default="skip",
                   help="skip: 処理済みをスキップ（デフォルト）/ overwrite: 全件上書き")
    p.add_argument("--no-debug",       action="store_true",
                   help="APIキー・モデル名の起動時表示を抑制")
    p.add_argument("--sample-n",       type=int, default=None,
                   help="先頭 N 行のみ処理 (テスト用)")
    args = p.parse_args()

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _run(
        input_csv         = str(_INPUT_CSV),
        output_csv        = str(_OUTPUT_CSV),
        judge_name        = args.judge,
        paraphraser_name  = args.paraphraser,
        use_twostep       = args.twostep,
        paraphrase_k      = args.paraphrase_k,
        do_position_check = args.position_check,
        mode              = args.mode,
        debug             = not args.no_debug,
        sample_n          = args.sample_n,
    )


if __name__ == "__main__":
    main()