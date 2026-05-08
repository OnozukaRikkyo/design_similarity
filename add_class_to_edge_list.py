#!/usr/bin/env python3
"""
edge_list/<year>.csv に source/target の意匠分類を付与した
edge_list_with_class/<year>.csv を生成する。

クラス情報は data/<year>.csv の class 列から取得する。
patent_id → メインクラス の辞書を pickle キャッシュして高速検索する。

出力カラム:
    source, target, (元の全属性),
    source_class, source_class_name,
    target_class, target_class_name

入力:
    /mnt/eightthdd/uspto/data/<year>.csv          (特許属性 CSV)
    /mnt/eightthdd/uspto/edge_list/<year>.csv     (build_edge_list.py の出力)

出力:
    /mnt/eightthdd/uspto/edge_list_with_class/<year>.csv
    /mnt/eightthdd/uspto/edge_list_with_class/_class_index.pkl  (キャッシュ)
"""

import csv
import pickle
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
DATA_DIR    = Path("/mnt/eightthdd/uspto/data")
EDGE_DIR    = Path("/mnt/eightthdd/uspto/edge_list")
OUT_DIR     = Path("/mnt/eightthdd/uspto/edge_list_with_class")
CLASS_CACHE = OUT_DIR / "_class_index.pkl"

EDGE_ATTRS = [
    "patentApplicationNumber",
    "officeActionDate",
    "officeActionCategory",
    "citationCategoryCode",
    "examinerCitedReferenceIndicator",
    "applicantCitedExaminerReferenceIndicator",
    "workGroup",
    "groupArtUnitNumber",
    "techCenter",
]

# ---------------------------------------------------------------------------
# 意匠分類名 (plot_class_histogram.py より)
# ---------------------------------------------------------------------------
CLASS_NAMES: dict[str, str] = {
    "D1":  "Edible Products",
    "D2":  "Apparel & Haberdashery",
    "D3":  "Travel Goods & Personal Items",
    "D4":  "Brushware",
    "D5":  "Textile/Fabric Articles",
    "D6":  "Furnishings",
    "D7":  "Equipment for Preparing Food",
    "D8":  "Tools & Hardware",
    "D9":  "Tools & Hardware (misc)",
    "D10": "Measuring/Testing Devices",
    "D11": "Jewelry/Symbolic Insignia",
    "D12": "Transportation",
    "D13": "Equipment for Production/Distribution",
    "D14": "Recording/Communication/Info",
    "D15": "Machines",
    "D16": "Photography & Optics",
    "D17": "Musical Instruments",
    "D18": "Printing & Office Machinery",
    "D19": "Office Supplies/Equipment",
    "D20": "Sales/Advertising/Signs",
    "D21": "Amusement Devices",
    "D22": "Arms/Pyrotechnics/etc.",
    "D23": "Environmental Heating/Cooling",
    "D24": "Medical/Lab Equipment",
    "D25": "Building Units & Construction",
    "D26": "Lighting",
    "D27": "Tobacco & Smoking",
    "D28": "Pharmaceuticals & Cosmetics",
    "D29": "Animal Husbandry",
    "D30": "Outdoor/Garden",
    "D31": "Articles of Manufacture",
    "D32": "Washing/Cleaning Equipment",
    "D33": "Food/Beverage Service",
    "D34": "Material/Article Handling",
    "D99": "Miscellaneous",
}


# ---------------------------------------------------------------------------
# クラス解析ユーティリティ (plot_class_histogram.py より)
# ---------------------------------------------------------------------------
def extract_main_class(class_str: str) -> str | None:
    """class フィールド文字列からメインクラス (例: 'D14') を抽出する。"""
    if not class_str or class_str.strip() == "":
        return None
    first = class_str.split(",")[0].strip()

    # "D 9" 形式 → 1桁クラス
    m = re.match(r"D (\d)", first)
    if m:
        return f"D{m.group(1)}"

    # "D14..." 形式 → 2桁優先 (D10-D34, D99)、次いで1桁
    m = re.match(r"D(\d+)", first)
    if not m:
        return None
    digits = m.group(1)
    if len(digits) >= 2:
        two = int(digits[:2])
        if (10 <= two <= 34) or two == 99:
            return f"D{two}"
    one = int(digits[:1])
    if 1 <= one <= 9:
        return f"D{one}"
    return None


# ---------------------------------------------------------------------------
# patent_id → メインクラス の辞書構築（pickle キャッシュ）
# ---------------------------------------------------------------------------
def build_class_index(data_dir: Path, use_cache: bool = True) -> dict[str, str]:
    """
    data/ 以下の全 CSV から { patent_id: main_class } を構築する。
    初回構築後は pickle にキャッシュし、2回目以降は即座にロードする。
    """
    if use_cache and CLASS_CACHE.exists():
        print(f"キャッシュからクラス索引をロード: {CLASS_CACHE}", flush=True)
        with open(CLASS_CACHE, "rb") as f:
            return pickle.load(f)

    print("クラス索引を構築中...", end=" ", flush=True)
    index: dict[str, str] = {}

    for csv_path in sorted(data_dir.glob("*.csv")):
        with open(csv_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("id", "").strip()
                cls = extract_main_class(row.get("class", ""))
                if pid and cls:
                    index[pid] = cls

    print(f"{len(index):,} 件")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CLASS_CACHE, "wb") as f:
        pickle.dump(index, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"クラス索引をキャッシュ: {CLASS_CACHE}")

    return index


# ---------------------------------------------------------------------------
# エッジリストへのクラス付与
# ---------------------------------------------------------------------------
def add_class(edge_csv: Path, class_index: dict[str, str], out_path: Path) -> None:
    print(f"処理中: {edge_csv.name}", end=" ... ", flush=True)

    fieldnames = ["source", "target"] + EDGE_ATTRS + [
        "source_class", "source_class_name",
        "target_class", "target_class_name",
    ]
    n_out = n_skip_src = n_skip_tgt = 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with (
        open(edge_csv, newline="", encoding="utf-8") as in_f,
        open(out_path, "w", newline="", encoding="utf-8") as out_f,
    ):
        reader = csv.DictReader(in_f)
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()

        for row in reader:
            src = row["source"]
            tgt = row["target"]

            src_cls = class_index.get(src)
            tgt_cls = class_index.get(tgt)

            if src_cls is None:
                n_skip_src += 1
            if tgt_cls is None:
                n_skip_tgt += 1

            out_row: dict = {k: row.get(k, "") for k in ["source", "target"] + EDGE_ATTRS}
            out_row["source_class"]      = src_cls or ""
            out_row["source_class_name"] = CLASS_NAMES.get(src_cls, "") if src_cls else ""
            out_row["target_class"]      = tgt_cls or ""
            out_row["target_class_name"] = CLASS_NAMES.get(tgt_cls, "") if tgt_cls else ""
            writer.writerow(out_row)
            n_out += 1

    print(
        f"出力: {n_out:,} 行  "
        f"クラス不明(source): {n_skip_src:,}  "
        f"クラス不明(target): {n_skip_tgt:,}  "
        f"→ {out_path}"
    )


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main(years: list[str] | None = None, rebuild_index: bool = False) -> None:
    class_index = build_class_index(DATA_DIR, use_cache=not rebuild_index)

    if years is None:
        edge_files = sorted(EDGE_DIR.glob("*.csv"))
    else:
        edge_files = [EDGE_DIR / f"{y}.csv" for y in years]

    for edge_csv in edge_files:
        if not edge_csv.exists():
            print(f"エッジリストが見つかりません: {edge_csv}", file=sys.stderr)
            continue
        out_path = OUT_DIR / edge_csv.name
        add_class(edge_csv, class_index, out_path)

    print("完了")


if __name__ == "__main__":
    # 使い方:
    #   python add_class_to_edge_list.py             # 全年処理
    #   python add_class_to_edge_list.py 2007 2008   # 指定年のみ
    #   python add_class_to_edge_list.py --rebuild   # クラス索引を再構築
    args = sys.argv[1:]
    rebuild = "--rebuild" in args
    years = [a for a in args if a != "--rebuild"] or None
    main(years, rebuild_index=rebuild)