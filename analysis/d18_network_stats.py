#!/usr/bin/env python3
"""
analysis/d18_network_stats.py

D18 within-class co-citation network statistics.

Edge source: qwen_all_pairs/*.jsonl (same dataset as the paper's 55,794 pairs).
Filters to D18–D18 pairs using the same parse_class logic as export_diagonal_csv.py.

Usage:
    python analysis/d18_network_stats.py
    python analysis/d18_network_stats.py --edge-dir /mnt/eightthdd/uspto/all_pair/qwen_all_pairs
"""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

EDGE_DIR = Path("/mnt/eightthdd/uspto/all_pair/qwen_all_pairs")
TARGET_CLASS = "D18"


def parse_class(raw: str) -> str:
    m = re.match(r"D\s*0*(\d+)", str(raw).strip(), re.I)
    if not m:
        return "D??"
    n = int(m.group(1))
    return f"D{n:02d}" if (1 <= n <= 34) or n == 99 else "D??"


def load_d18_edges(edge_dir: Path) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    n_total = n_d18 = 0

    for path in sorted(edge_dir.glob("*.jsonl")):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                n_total += 1
                sc = parse_class(rec.get("source_class", ""))
                tc = parse_class(rec.get("target_class", ""))
                if sc != TARGET_CLASS or tc != TARGET_CLASS:
                    continue
                n_d18 += 1
                src, tgt = rec["source"], rec["target"]
                edge = (min(src, tgt), max(src, tgt))
                edges.add(edge)

    print(f"  {n_total:,} total pairs read")
    print(f"  {n_d18:,} D18–D18 pairs (before dedup)")
    print(f"  {len(edges):,} unique edges after dedup")
    return edges


def compute_stats(edges: set[tuple[str, str]]) -> None:
    degree: dict[str, int] = defaultdict(int)
    for src, tgt in edges:
        degree[src] += 1
        degree[tgt] += 1

    nodes = list(degree.keys())
    degrees = list(degree.values())

    n_nodes = len(nodes)
    n_edges = len(edges)
    avg_deg = sum(degrees) / n_nodes if n_nodes else 0
    max_deg = max(degrees)
    min_deg = min(degrees)
    max_node = max(degree, key=degree.get)
    min_node = min(degree, key=degree.get)

    print()
    print("=" * 40)
    print(f"  D18 co-citation network statistics")
    print("=" * 40)
    print(f"  Nodes (unique patents) : {n_nodes:,}")
    print(f"  Edges (unique pairs)   : {n_edges:,}")
    print(f"  Average degree         : {avg_deg:.4f}")
    print(f"  Max degree             : {max_deg}  ({max_node})")
    print(f"  Min degree             : {min_deg}  ({min_node})")
    print("=" * 40)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Compute D18 within-class co-citation network statistics."
    )
    ap.add_argument("--edge-dir", default=str(EDGE_DIR))
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    edge_dir = Path(args.edge_dir)

    print(f"Loading D18–D18 edges from {edge_dir} ...")
    edges = load_d18_edges(edge_dir)
    compute_stats(edges)


if __name__ == "__main__":
    main()
