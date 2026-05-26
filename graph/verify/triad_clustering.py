"""
triad_clustering.py
====================

ある triad (3 ノード) の局所クラスタ係数 (local clustering coefficient) を
networkx の公式実装で計算する。

参照:
  networkx.algorithms.cluster.clustering
  https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.cluster.clustering.html

  Watts, D. J., & Strogatz, S. H. (1998).
  Collective dynamics of 'small-world' networks. Nature, 393(6684), 440-442.

使用例:
  python triad_clustering.py all.jsonl D0807426 D0807427 D0807428
  python triad_clustering.py all.jsonl --all-triads --output triad_clustering.jsonl
"""

import argparse
import json
import sys

import networkx as nx


# ============================================================
# データロードとグラフ構築
# ============================================================

def load_graph(jsonl_path):
    """all.jsonl から無向グラフを構築する。

    各行は source, target, similarity (などのキー) を含む JSON オブジェクト。
    エッジの similarity は属性として保持する (clustering 計算には使わないが、
    後で参照できる可能性のため)。
    """
    G = nx.Graph()
    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"JSON decode error at line {line_no}: {e}")
            s, t = r['source'], r['target']
            if s == t:
                continue
            G.add_edge(s, t, similarity=r.get('similarity'))
    return G


# ============================================================
# Triad の clustering coefficient
# ============================================================

def triad_clustering(G, A, B, C):
    """3 ノード (A, B, C) の局所クラスタ係数を networkx で計算する。

    networkx.clustering は引数として nodes (iterable) を取り、
    各ノードの local clustering coefficient を辞書で返す。

    weight=None (デフォルト) では、Watts-Strogatz の定義:
        C_v = 2 * T(v) / (deg(v) * (deg(v) - 1))
    ここで T(v) は v を含む triangle 数、deg(v) は v の次数。

    返り値:
        dict { 'A': str, 'B': str, 'C': str,
               'C_A': float, 'C_B': float, 'C_C': float,
               'E12_min': float, 'E12_mean': float }
    """
    for node in (A, B, C):
        if node not in G:
            raise ValueError(f"Node {node} not found in graph")

    # networkx の公式関数で 3 ノード分の clustering coefficient を一括取得
    cc = nx.clustering(G, nodes=[A, B, C])

    c_a, c_b, c_c = cc[A], cc[B], cc[C]
    return {
        'A': A, 'B': B, 'C': C,
        'C_A': c_a, 'C_B': c_b, 'C_C': c_c,
        'E12_min':  min(c_a, c_b, c_c),
        'E12_mean': (c_a + c_b + c_c) / 3.0,
    }


def all_triads_clustering(G):
    """グラフ内のすべての closed triangle について clustering を計算する。

    networkx.enumerate_all_cliques を使い、size=3 のクリークを抽出する。
    各ノードの clustering は全ノード一括で事前計算し辞書 lookup する
    (O(N) ノードを毎回再計算しない)。

    返り値: list of dict (triad_clustering と同じスキーマ)
    """
    # 全ノードの clustering を一括計算 (再利用)
    cc_all = nx.clustering(G)

    triads = []
    for clique in nx.enumerate_all_cliques(G):
        if len(clique) != 3:
            continue
        A, B, C = sorted(clique)
        c_a, c_b, c_c = cc_all[A], cc_all[B], cc_all[C]
        # エッジの similarity を付与
        s_ab = G[A][B].get('similarity')
        s_bc = G[B][C].get('similarity')
        s_ac = G[A][C].get('similarity')
        sims = [s for s in (s_ab, s_bc, s_ac) if s is not None]
        s1 = min(sims) if len(sims) == 3 else None

        triads.append({
            'A': A, 'B': B, 'C': C,
            'C_A': c_a, 'C_B': c_b, 'C_C': c_c,
            'E12_min':  min(c_a, c_b, c_c),
            'E12_mean': (c_a + c_b + c_c) / 3.0,
            's_AB': s_ab, 's_BC': s_bc, 's_AC': s_ac,
            'S1': s1,
        })
    return triads


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Compute local clustering coefficients for a triad "
                    "(3 nodes) using networkx."
    )
    parser.add_argument('jsonl', help='Input JSONL with citation pairs '
                                       '(keys: source, target, similarity, ...)')
    parser.add_argument('nodes', nargs='*',
                        help='Three node IDs (A B C) of the triad to evaluate')
    parser.add_argument('--all-triads', action='store_true',
                        help='Enumerate all closed triangles and compute '
                             'clustering for each.')
    parser.add_argument('--output', default=None,
                        help='Output JSONL file (used only with --all-triads).')
    args = parser.parse_args()

    print(f"Loading graph from {args.jsonl}...", file=sys.stderr)
    G = load_graph(args.jsonl)
    print(f"  |V| = {G.number_of_nodes()}, |E| = {G.number_of_edges()}",
          file=sys.stderr)

    if args.all_triads:
        print("Enumerating all closed triangles and computing clustering...",
              file=sys.stderr)
        triads = all_triads_clustering(G)
        print(f"  {len(triads)} triangles found.", file=sys.stderr)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                for t in triads:
                    f.write(json.dumps(t) + '\n')
            print(f"Wrote {len(triads)} records to {args.output}",
                  file=sys.stderr)
        else:
            for t in triads:
                print(json.dumps(t))
    else:
        if len(args.nodes) != 3:
            parser.error("Specify exactly three node IDs, or use --all-triads")
        A, B, C = args.nodes
        result = triad_clustering(G, A, B, C)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
