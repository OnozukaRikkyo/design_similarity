"""
prepare_human_annotation.py
============================

パイロットサンプルをもとに人手アノテーション用パッケージを作成する。

処理:
  1. pilot_24.csv（extract_pilot.py 出力）を読み込む
  2. source_image / target_image を annotation_images/ にコピー
  3. アノテーターに渡す annotation_tasks.csv を生成
     （source, target, similarity, judgment, reason, _stratum + 記入欄）
  4. 記入欄: human_judgment (Yes/No), human_confidence (1-5), human_comment

使い方:
  python prepare_human_annotation.py pilot_24.csv \\
      --out-dir annotation_package/
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

import pandas as pd

log = logging.getLogger("prepare_human_annotation")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ============================================================================
# Column definitions
# ============================================================================

# Columns exported to annotation task sheet
TASK_COLS = [
    "pair_id",
    "source",
    "target",
    "similarity",
    "llm_judgment",
    "llm_confidence",
    "reason",
    "_stratum",
    "source_image_copy",
    "target_image_copy",
    # blank columns for annotators
    "human_judgment",
    "human_confidence",
    "human_comment",
]


# ============================================================================
# Main
# ============================================================================

def prepare(
    pilot_csv: str,
    out_dir: str = "annotation_package",
    copy_images: bool = True,
) -> pd.DataFrame:
    out = Path(out_dir)
    img_dir = out / "annotation_images"
    out.mkdir(parents=True, exist_ok=True)
    if copy_images:
        img_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(pilot_csv)
    log.info("Pilot CSV: %d rows", len(df))

    # Rename LLM columns to avoid confusion with human annotation
    rename_map = {}
    if "judgment"   in df.columns: rename_map["judgment"]   = "llm_judgment"
    if "confidence" in df.columns: rename_map["confidence"] = "llm_confidence"
    df = df.rename(columns=rename_map)

    # Assign pair IDs
    df.insert(0, "pair_id", [f"P{i+1:03d}" for i in range(len(df))])

    # Copy images
    src_copies = []
    tgt_copies = []
    for _, row in df.iterrows():
        pid = row["pair_id"]

        def _copy(col: str, side: str) -> str:
            raw = row.get(col, "")
            if not raw or pd.isna(raw):
                return ""
            src_path = Path(str(raw))
            if not src_path.exists():
                log.warning("Image not found: %s", src_path)
                return str(raw)
            if not copy_images:
                return str(raw)
            ext   = src_path.suffix
            dest  = img_dir / f"{pid}_{side}{ext}"
            shutil.copy2(src_path, dest)
            return str(dest.relative_to(out))

        src_copies.append(_copy("source_image", "A"))
        tgt_copies.append(_copy("target_image", "B"))

    df["source_image_copy"] = src_copies
    df["target_image_copy"] = tgt_copies

    # Blank columns for annotators
    df["human_judgment"]   = ""
    df["human_confidence"] = ""
    df["human_comment"]    = ""

    # Select and order columns
    export_cols = [c for c in TASK_COLS if c in df.columns]
    # add any remaining columns not in TASK_COLS
    extra = [c for c in df.columns if c not in export_cols
             and c not in ("source_image", "target_image")]
    out_df = df[export_cols + extra]

    task_csv = out / "annotation_tasks.csv"
    out_df.to_csv(task_csv, index=False)
    log.info("Annotation tasks saved: %s (%d rows)", task_csv, len(out_df))

    # Write README
    readme = out / "README.txt"
    readme.write_text(
        "# Human Annotation Package\n\n"
        "Files:\n"
        "  annotation_tasks.csv  — task sheet; fill in human_judgment / human_confidence / human_comment\n"
        "  annotation_images/    — patent drawing pairs (A = source, B = target)\n\n"
        "Instructions:\n"
        "  1. For each pair_id, examine the two images (source_image_copy, target_image_copy).\n"
        "  2. Decide whether the two designs are substantially similar under the\n"
        "     ordinary observer test (Egyptian Goddess v. Swisa, 543 F.3d 665).\n"
        "  3. Fill in:\n"
        "       human_judgment   : Yes / No\n"
        "       human_confidence : 1 (very uncertain) – 5 (very confident)\n"
        "       human_comment    : optional notes\n"
        "  4. Do NOT look at llm_judgment or reason while annotating.\n"
        "  5. Save the CSV when done and return it to the researcher.\n\n"
        "Strata legend:\n"
        "  L1  self-inconsistent (conf=5 & No & 'identical' in reason)\n"
        "  L2  high-sim paradox (sim≥0.99 & No)\n"
        "  L3  high-sim match (sim≥0.99 & Yes)\n"
        "  L4  low-sim match (lowest sim & Yes)\n"
        "  L5  calibration boundary (sim in [0.965, 0.975])\n"
        "  L6  design-family cluster (largest connected component)\n"
    )
    log.info("README written: %s", readme)
    return out_df


# ============================================================================
# CLI
# ============================================================================

_WORK_DIR  = Path("/home/sonozuka/design_similarity/vector/output/D18/cosine_numpy/reasoning")
_PILOT_CSV = _WORK_DIR / "pilot_24.csv"
_OUT_DIR   = _WORK_DIR / "annotation_package"


def main() -> None:
    parser = argparse.ArgumentParser(description="人手アノテーションパッケージを作成")
    parser.add_argument("--no-copy-images", action="store_true",
                        help="画像をコピーせず、パスのみ記載")
    args = parser.parse_args()

    if not _PILOT_CSV.exists():
        log.error("pilot_24.csv が存在しません。先に extract_pilot.py を実行してください: %s", _PILOT_CSV)
        return

    prepare(
        pilot_csv    = str(_PILOT_CSV),
        out_dir      = str(_OUT_DIR),
        copy_images  = not args.no_copy_images,
    )


if __name__ == "__main__":
    main()