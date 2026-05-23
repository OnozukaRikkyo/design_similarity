#!/usr/bin/env bash
# run_pipeline.sh
# ================
# PMS パイプラインのフルランナー
#
# 使い方:
#   bash run_pipeline.sh [オプション]
#
# 環境変数:
#   GEMINI_API_KEY  — Gemini API キー（必須）
#
# オプション（環境変数で上書き可）:
#   INPUT_CSV   — 入力 CSV（デフォルト: 下記参照）
#   WORKDIR     — 出力ルートディレクトリ（デフォルト: 下記参照）
#   MODEL       — モデルエイリアス（gemini-flash / gemini-pro / gemini-flash-lite）
#   CONCURRENCY — 並列リクエスト数
#   PILOT_SEED  — パイロットサンプリング乱数シード
#   PILOT_ONLY  — 1 にすると PMS/M5/B をパイロット行のみ実行
#   MODULE_PMS      — 0 でスキップ
#   MODULE_M5       — 0 でスキップ
#   MODULE_BASELINE — 0 でスキップ
#   MODULE_MERGE    — 0 でスキップ
#   MODULE_ANALYZE  — 0 でスキップ

set -euo pipefail

# ── デフォルト設定 ─────────────────────────────────────────────────────────

: "${INPUT_CSV:=/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv}"
: "${WORKDIR:=/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/reasoning}"
: "${MODEL:=gemini-flash}"
: "${PILOT_SEED:=42}"
: "${PILOT_ONLY:=0}"

: "${MODULE_PMS:=1}"
: "${MODULE_M5:=1}"
: "${MODULE_BASELINE:=1}"
: "${MODULE_MERGE:=1}"
: "${MODULE_ANALYZE:=1}"

# ── パス設定 ───────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PILOT_CSV="${WORKDIR}/pilot_24.csv"
PILOT_STRATA="${WORKDIR}/pilot_strata.csv"
PMS_OUT="${WORKDIR}/pms_results.csv"
M5_OUT="${WORKDIR}/m5_scores.csv"
BASELINE_OUT="${WORKDIR}/baseline_b.csv"
UNIFIED_OUT="${WORKDIR}/unified_results.csv"
ANNOTATION_PACKAGE="${WORKDIR}/annotation_package"
ANALYSIS_DIR="${WORKDIR}/analysis"

mkdir -p "${WORKDIR}"

# ── 前提チェック ───────────────────────────────────────────────────────────

if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    echo "[ERROR] GEMINI_API_KEY が未設定です。"
    exit 1
fi

if [[ ! -f "${INPUT_CSV}" ]]; then
    echo "[ERROR] 入力 CSV が見つかりません: ${INPUT_CSV}"
    exit 1
fi

echo "============================================"
echo " PMS Pipeline"
echo "  INPUT_CSV   : ${INPUT_CSV}"
echo "  WORKDIR     : ${WORKDIR}"
echo "  MODEL       : ${MODEL}"
echo "  PILOT_ONLY  : ${PILOT_ONLY}"
echo "============================================"

# ── Step 0: パイロットサンプリング ─────────────────────────────────────────

echo ""
echo "[Step 0] パイロットサンプリング ..."
cd "${SCRIPT_DIR}"
python3 extract_pilot.py \
    "${INPUT_CSV}" \
    --out        "${PILOT_CSV}" \
    --strata-out "${PILOT_STRATA}" \
    --seed       "${PILOT_SEED}"
echo "  → ${PILOT_CSV}"

# ── パイロットフラグ処理 ───────────────────────────────────────────────────

PILOT_FLAG=""
if [[ "${PILOT_ONLY}" == "1" ]]; then
    PILOT_FLAG="--pilot-only"
fi

# ── Step 1: PMS（M1/M2/M3）────────────────────────────────────────────────

if [[ "${MODULE_PMS}" == "1" ]]; then
    echo ""
    echo "[Step 1] PMS (M1/M2/M3) ..."
    PILOT_ARG=""
    if [[ "${PILOT_ONLY}" == "1" ]]; then
        PILOT_ARG="--pilot-csv ${PILOT_CSV}"
    fi
    python3 patent_rationale_pms.py \
        --model      "${MODEL}" \
        ${PILOT_ARG}
    echo "  → ${PMS_OUT}"
else
    echo "[Step 1] PMS スキップ (MODULE_PMS=0)"
fi

# ── Step 2: M5 visual faithfulness probe ──────────────────────────────────

if [[ "${MODULE_M5}" == "1" ]]; then
    echo ""
    echo "[Step 2] M5 visual faithfulness probe ..."
    python3 patent_visual_probes.py \
        --module     m5 \
        --model      "${MODEL}" \
        ${PILOT_FLAG}
    echo "  → ${M5_OUT}"
else
    echo "[Step 2] M5 スキップ (MODULE_M5=0)"
fi

# ── Step 3: Baseline B ────────────────────────────────────────────────────

if [[ "${MODULE_BASELINE}" == "1" ]]; then
    echo ""
    echo "[Step 3] Baseline B ..."
    python3 patent_visual_probes.py \
        --module     baseline \
        --model      "${MODEL}" \
        ${PILOT_FLAG}
    echo "  → ${BASELINE_OUT}"
else
    echo "[Step 3] Baseline B スキップ (MODULE_BASELINE=0)"
fi

# ── Step 4: アノテーションパッケージ作成 ──────────────────────────────────

echo ""
echo "[Step 4] 人手アノテーションパッケージ作成 ..."
python3 prepare_human_annotation.py \
    "${PILOT_CSV}" \
    --out-dir "${ANNOTATION_PACKAGE}"
echo "  → ${ANNOTATION_PACKAGE}/"

# ── Step 5: 結合 ──────────────────────────────────────────────────────────

if [[ "${MODULE_MERGE}" == "1" ]]; then
    echo ""
    echo "[Step 5] 結合 (merge_results.py) ..."
    PMS_ARG=""
    M5_ARG=""
    BL_ARG=""
    [[ -f "${PMS_OUT}"      ]] && PMS_ARG="--pms ${PMS_OUT}"
    [[ -f "${M5_OUT}"       ]] && M5_ARG="--m5 ${M5_OUT}"
    [[ -f "${BASELINE_OUT}" ]] && BL_ARG="--baseline ${BASELINE_OUT}"

    python3 merge_results.py \
        --input   "${INPUT_CSV}" \
        ${PMS_ARG} \
        ${M5_ARG} \
        ${BL_ARG} \
        --strata  "${PILOT_CSV}" \
        --out     "${UNIFIED_OUT}"
    echo "  → ${UNIFIED_OUT}"
else
    echo "[Step 5] 結合スキップ (MODULE_MERGE=0)"
fi

# ── Step 6: 統計分析・図生成 ──────────────────────────────────────────────

if [[ "${MODULE_ANALYZE}" == "1" ]]; then
    if [[ -f "${UNIFIED_OUT}" ]]; then
        echo ""
        echo "[Step 6] 統計分析 (analyze_results.py) ..."
        python3 analyze_results.py \
            "${UNIFIED_OUT}" \
            --out-dir "${ANALYSIS_DIR}"
        echo "  → ${ANALYSIS_DIR}/"
    else
        echo "[Step 6] ${UNIFIED_OUT} が存在しないため分析スキップ"
    fi
else
    echo "[Step 6] 分析スキップ (MODULE_ANALYZE=0)"
fi

# ── 完了 ──────────────────────────────────────────────────────────────────

echo ""
echo "============================================"
echo " Pipeline complete"
echo "  Pilot CSV      : ${PILOT_CSV}"
echo "  PMS results    : ${PMS_OUT}"
echo "  M5 scores      : ${M5_OUT}"
echo "  Baseline B     : ${BASELINE_OUT}"
echo "  Unified        : ${UNIFIED_OUT}"
echo "  Annotation pkg : ${ANNOTATION_PACKAGE}/"
echo "  Analysis       : ${ANALYSIS_DIR}/"
echo "============================================"