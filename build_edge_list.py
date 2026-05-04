#!/usr/bin/env python3
"""
USPTO 意匠特許引用データ (JSON) から共引用エッジリスト CSV を生成する。

エッジの定義:
    同一の出願審査 (patentApplicationNumber) で共に引用された
    2つの意匠特許を「類似」とみなしエッジを張る（共引用ネットワーク）。

    例: 出願 29701893 が D535736, D543613, D543266 を引用
        → エッジ (D535736, D543613), (D535736, D543266), (D543613, D543266)

グラフ構造:
    source, target : 意匠特許 ID (D0XXXXXX 形式、source < target で正規化)

エッジ属性:
    patentApplicationNumber : 両特許を繋ぐ出願番号
    その他の属性 (officeActionDate 等) : source が引用された際のレコードから取得

出力:
    /mnt/eightthdd/uspto/edge_list/<year>.csv
    カラム: source, target, patentApplicationNumber,
            officeActionDate, officeActionCategory, citationCategoryCode,
            examinerCitedReferenceIndicator,
            applicantCitedExaminerReferenceIndicator,
            workGroup, groupArtUnitNumber, techCenter
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# パス設定
# ---------------------------------------------------------------------------
JSON_DIR = Path("/mnt/eightthdd/uspto/json")
CSV_DIR  = Path("/mnt/eightthdd/uspto/data")
OUT_DIR  = Path("/mnt/eightthdd/uspto/edge_list")

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
# 有効な意匠特許 ID の収集
# ---------------------------------------------------------------------------
def load_valid_ids(csv_dir: Path) -> set[str]:
    """
    data/ 以下の全 CSV から意匠特許 ID (D0XXXXXX) の集合を返す。
    エッジ生成時に JSON に含まれる特許が実際に存在するか確認するために使用する。
    """
    valid: set[str] = set()
    for path in sorted(csv_dir.glob("*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pid = row.get("id", "").strip()
                if pid:
                    valid.add(pid)
    return valid


# ---------------------------------------------------------------------------
# エッジリスト生成
# ---------------------------------------------------------------------------
def build_edge_list(json_path: Path, valid_ids: set[str], out_path: Path) -> None:
    print(f"読み込み中: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        data: dict = json.load(f)

    # app_no → { patent_id: record }
    # 同一出願で同一特許が複数回引用された場合は最初のレコードを代表として使用
    app_to_patents: dict[str, dict[str, dict]] = defaultdict(dict)

    for value in data.values():
        patent_id = value.get("original_id", "").strip()
        if not patent_id or patent_id not in valid_ids:
            continue
        for record in value.get("records", []):
            app_no = record.get("patentApplicationNumber", "").strip()
            if not app_no:
                continue
            if patent_id not in app_to_patents[app_no]:
                app_to_patents[app_no][patent_id] = record

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["source", "target"] + EDGE_ATTRS
    n_edges = n_single = 0

    with open(out_path, "w", newline="", encoding="utf-8") as out_f:
        writer = csv.DictWriter(out_f, fieldnames=fieldnames)
        writer.writeheader()

        for app_no, patent_map in app_to_patents.items():
            patents = sorted(patent_map)  # ソートで source < target を保証（重複排除）
            if len(patents) < 2:
                n_single += 1
                continue

            for i in range(len(patents)):
                for j in range(i + 1, len(patents)):
                    source, target = patents[i], patents[j]
                    rec = patent_map[source]
                    row: dict = {"source": source, "target": target}
                    for attr in EDGE_ATTRS:
                        row[attr] = app_no if attr == "patentApplicationNumber" else rec.get(attr, "")
                    writer.writerow(row)
                    n_edges += 1

    print(f"  エッジ: {n_edges:,}  単独引用スキップ: {n_single:,}  -> {out_path}")


# ---------------------------------------------------------------------------
# メイン
# ---------------------------------------------------------------------------
def main(years: list[str] | None = None) -> None:
    print("有効な意匠特許IDをロード中...", end=" ", flush=True)
    valid_ids = load_valid_ids(CSV_DIR)
    print(f"{len(valid_ids):,} 件")

    if years is None:
        json_files = sorted(JSON_DIR.glob("*.json"))
    else:
        json_files = [JSON_DIR / f"{y}.json" for y in years]

    for json_path in json_files:
        if not json_path.exists():
            print(f"JSONが見つかりません: {json_path}", file=sys.stderr)
            continue
        out_path = OUT_DIR / json_path.name.replace(".json", ".csv")
        build_edge_list(json_path, valid_ids, out_path)

    print("完了")


if __name__ == "__main__":
    # 使い方:
    #   python build_edge_list.py            # 全年処理
    #   python build_edge_list.py 2007 2008  # 指定年のみ
    years = sys.argv[1:] if len(sys.argv) > 1 else None
    main(years)
