"""
意匠特許の類似ペアグラフから、3-clique (三角形) の「コサイン類似度ベース」整合性を
評価して Ground Truth 候補を抽出するスクリプト。

## 設計原理

LLM の Yes/No 判定が信頼できないことが事前検証で確認されたため、判定は使わず、
コサイン類似度のみを用いて「3点が互いに近い」ことの確信度を測る。

依拠する主要文献:

[1] Schubert, E. (2021). "A Triangle Inequality for Cosine Similarity."
    SISAP 2021. arXiv:2107.04071. DOI: 10.1007/978-3-030-89657-7_3
    https://arxiv.org/abs/2107.04071
    → コサイン類似度自体は metric ではないが、角距離 arccos(s) は単位球面上の
      proper metric であり三角不等式を満たす。Schubert はコサイン類似度に対する
      三角不等式の明示的な境界を導出: s_AC は s_AB, s_BC から
        cos(d_AB + d_BC) ≤ s_AC ≤ cos(|d_AB − d_BC|)
      の範囲に収まる (d_ij = arccos(s_ij)).

[2] Jarvis, R.A., Patrick, E.A. (1973). "Clustering Using a Similarity Measure
    Based on Shared Near Neighbors." IEEE Trans. Computers C-22(11): 1025–1034.
    https://doi.org/10.1109/T-C.1973.223640
    → 共有最近傍 (Shared Nearest Neighbor, SNN) 類似度。
      二点 A,B の k-NN リストが多くの要素を共有していれば、A,B は単なる「直接近接」
      以上の構造的近接性を持つ。

[3] Houle, M.E., Kriegel, H.-P., Kröger, P., Schubert, E., Zimek, A. (2010).
    "Can Shared-Neighbor Distances Defeat the Curse of Dimensionality?" SSDBM 2010.
    Lecture Notes in Computer Science, vol 6187, pp. 482–500.
    https://doi.org/10.1007/978-3-642-13818-8_34
    → SNN 距離は高次元 (curse of dimensionality 下) でも primary distance より
      安定する。64次元 embedding (本データの想定) のような中〜高次元で重要。

[4] Zhong, Z., Zheng, L., Cao, D., Li, S. (2017). "Re-ranking Person
    Re-identification with k-reciprocal Encoding." CVPR 2017. arXiv:1701.08398
    https://arxiv.org/abs/1701.08398
    → k-reciprocal nearest neighbor (k-RNN): A が B の top-k NN かつ B が A の
      top-k NN であるとき、A↔B は強い相互類似ペア。一方向の k-NN より厳しく、
      false positive が少ない。

[5] Sia, J., Jonckheere, E., Bogdan, P. (2019). "Ollivier-Ricci Curvature-Based
    Method to Community Detection in Complex Networks." Sci Rep 9, 9800.
    https://doi.org/10.1038/s41598-019-46079-x
    → Ollivier-Ricci 曲率 κ(i,j) について、コミュニティ内エッジは正曲率
      (周辺と密に結合)、コミュニティ間ショートカットエッジは負曲率。
      3-clique を構成するエッジは典型的に正曲率を持つ。

[6] Gilad-Bachrach et al. → ORC-ManL (ICLR 2025): "Recovering Manifold Structure
    Using Ollivier-Ricci Curvature." arXiv:2410.01149
    https://arxiv.org/abs/2410.01149
    → 多様体構造をショートカットする偽エッジの ORC は負。
      これは「真のクラスタ内エッジ」と「クラスタ間偽エッジ」の幾何学的識別。

これらを統合し、3-clique それぞれに 4 種の独立スコアを与えて重み付き合計する。
各スコアは閉形式・解釈可能で、ハイパーパラメータは最小限に保つ。
"""

import json
import math
from collections import defaultdict
from itertools import combinations
import networkx as nx


# ==============================================================================
# データロード
# ==============================================================================

def load_data(jsonl_path):
    with open(jsonl_path) as f:
        return [json.loads(line) for line in f]


def build_similarity_graph(data):
    """
    エッジ重み = cosine similarity の重み付き無向グラフを構築。
    LLM 判定 (judgment, confidence) は意図的に無視する。
    """
    G = nx.Graph()
    for d in data:
        G.add_edge(d['source'], d['target'], sim=d['similarity'])
    return G


# ==============================================================================
# 三角形ごとの確信度スコア (4種)
# ==============================================================================

def angular_distance(s):
    """
    コサイン類似度 → 角距離 (Schubert 2021)
    arccos は単位球面上の proper metric。
    s が [-1, 1] の外に出るのは数値誤差のみ。
    """
    return math.acos(max(-1.0, min(1.0, s)))


def schubert_lower_bound(s_ab, s_bc):
    """
    Schubert (2021) Eq.: 三角不等式の下界。
        s_AC >= s_AB * s_BC - sqrt(1-s_AB^2) * sqrt(1-s_BC^2)
    s_AB, s_BC が高いほど s_AC の下界が高くなり、三角形は強く制約される。
    """
    return s_ab * s_bc - math.sqrt(max(0, 1 - s_ab**2)) * math.sqrt(max(0, 1 - s_bc**2))


def schubert_upper_bound(s_ab, s_bc):
    """Schubert (2021) Eq.: 三角不等式の上界。"""
    return s_ab * s_bc + math.sqrt(max(0, 1 - s_ab**2)) * math.sqrt(max(0, 1 - s_bc**2))


def score_min_similarity(s_ab, s_bc, s_ac):
    """
    Score 1: weakest-link similarity (最弱辺類似度)。

    3 辺全てが高くなければ「三角形が強い」とは言えない。
    最も弱い辺の cosine similarity を直接スコアにする。
    解釈: 「三角形を支える weakest link」。
    """
    return min(s_ab, s_bc, s_ac)


def score_angular_tightness(s_ab, s_bc, s_ac):
    """
    Score 2: 角距離による三角形の「タイトネス」(Schubert 2021 にもとづく)。

    3 辺の角距離の最大値が 0 に近いほど 3 点は同じ場所に密集している。
    1 - max(d) / (π/2) を [0, 1] にスケール (π/2 = 直交)。
    """
    d_ab = angular_distance(s_ab)
    d_bc = angular_distance(s_bc)
    d_ac = angular_distance(s_ac)
    max_d = max(d_ab, d_bc, d_ac)
    # max_d=0 → score=1 (完全一致), max_d=π/2 → score=0 (直交), さらに大なら負
    return max(0.0, 1.0 - max_d / (math.pi / 2))


def score_bound_compliance(s_ab, s_bc, s_ac):
    """
    Score 3: Schubert 三角不等式境界への適合度。

    観測された s_AC が、s_AB と s_BC から導かれる Schubert 境界の
    [lower_bound, upper_bound] 区間のどこに位置するかを評価。

    s_AB, s_BC が高い場合、境界は狭く、s_AC は upper_bound 近傍に集中する。
    s_AC が upper_bound に近いほど、3 点が単一ベクトル幾何 (近い 3 点を
    球面に張った場合) に強く合致する。

    返り値:
        1.0: s_AC が upper_bound と一致 (最も整合的)
        0.0: s_AC が lower_bound (境界の最緩端)
        負値: s_AC が下界を下回る (= 三角不等式違反、データの誤りを示唆)

    Note: 単位ベクトルから生成された真の cosine similarity は必ず
    下界以上を満たすため、下界違反 (負スコア) は数値誤差か、
    embedding が真に同じ単位球面上にない (異なる正規化が混在) ことを示唆。
    """
    lb = schubert_lower_bound(s_ab, s_bc)
    ub = schubert_upper_bound(s_ab, s_bc)
    if ub - lb < 1e-9:  # 境界が縮退 (s_AB=s_BC=1)
        return 1.0 if s_ac > 0.99 else 0.0
    return (s_ac - lb) / (ub - lb)


def score_snn(snn_a, snn_b, snn_c, k_norm):
    """
    Score 4: 3-way Shared Nearest Neighbor 類似度
    (Jarvis & Patrick 1973; Houle et al. 2010)

    A, B, C 三者が共有する近傍ノード数 / 個々の近傍数の最大値。
    値域 [0, 1]。三者が共通の意匠族の中に埋め込まれている度合を測る。

    高次元 embedding では cosine sim 自体より SNN 類似度のほうが
    安定する (Houle et al. 2010)。
    """
    common = snn_a & snn_b & snn_c
    if k_norm == 0:
        return 0.0
    return len(common) / k_norm


# ==============================================================================
# 3-clique 列挙 と スコア合成
# ==============================================================================

def enumerate_triangles(G):
    """G 内の全 3-clique を列挙。"""
    triangles = []
    nodes_sorted = sorted(G.nodes())
    adj = {n: set(G.neighbors(n)) for n in G.nodes()}
    for a in nodes_sorted:
        neighbors_a = adj[a]
        for b in neighbors_a:
            if b <= a:
                continue
            common = neighbors_a & adj[b]
            for c in common:
                if c <= b:
                    continue
                triangles.append((a, b, c))
    return triangles


def compute_node_neighborhoods(G):
    """各ノードの隣接ノード集合を辞書化 (SNN 用)。"""
    return {n: set(G.neighbors(n)) for n in G.nodes()}


def triadic_confidence(triangle, G, neighborhoods, weights=None):
    """
    1つの 3-clique に対する統合確信度スコア。

    重みのデフォルト (合計 = 1):
        w1=0.30  weakest-link similarity
        w2=0.30  angular tightness
        w3=0.25  Schubert bound compliance
        w4=0.15  SNN similarity

    SNN のウェイトを低めにしているのは、本データが「クエリごとの top-k
    候補リスト」由来のスパースグラフであり、観測されない真の最近傍が
    多く存在しうるため (Houle et al. 2010 の前提とは完全には合わない)。
    """
    if weights is None:
        weights = (0.30, 0.30, 0.25, 0.15)
    w1, w2, w3, w4 = weights
    a, b, c = triangle

    s_ab = G[a][b]['sim']
    s_bc = G[b][c]['sim']
    s_ac = G[a][c]['sim']

    s1 = score_min_similarity(s_ab, s_bc, s_ac)
    s2 = score_angular_tightness(s_ab, s_bc, s_ac)
    s3 = score_bound_compliance(s_ab, s_bc, s_ac)
    # SNN: 3点の neighborhood サイズの mean を正規化基準に
    snn_a = neighborhoods[a] - {a, b, c}
    snn_b = neighborhoods[b] - {a, b, c}
    snn_c = neighborhoods[c] - {a, b, c}
    k_norm = max(1, min(len(snn_a), len(snn_b), len(snn_c)))
    s4 = score_snn(snn_a, snn_b, snn_c, k_norm)

    score = w1 * s1 + w2 * s2 + w3 * s3 + w4 * s4

    return {
        'triangle': triangle,
        'sims': (s_ab, s_bc, s_ac),
        's1_weakest_link': s1,
        's2_angular_tightness': s2,
        's3_bound_compliance': s3,
        's4_snn': s4,
        'confidence': score,
    }


# ==============================================================================
# Main: 全 3-clique のスコア計算と階層分類
# ==============================================================================

def main(jsonl_path='/mnt/user-data/uploads/all.jsonl'):
    data = load_data(jsonl_path)
    G = build_similarity_graph(data)
    print(f"Graph: |V|={G.number_of_nodes()}, |E|={G.number_of_edges()}")

    triangles = enumerate_triangles(G)
    print(f"観測された 3-clique 数: {len(triangles)}")

    neighborhoods = compute_node_neighborhoods(G)

    # 全 3-clique にスコアを付与
    scored = []
    for t in triangles:
        r = triadic_confidence(t, G, neighborhoods)
        scored.append(r)

    # 確信度降順ソート
    scored.sort(key=lambda r: -r['confidence'])

    # 階層化 (パーセンタイル基準)
    n = len(scored)
    tier_thresholds = {
        'A': 0.95,  # 上位 5%
        'B': 0.85,  # 上位 5-15%
        'C': 0.70,  # 上位 15-30%
    }

    # 絶対閾値も併用 (Schubert 境界に基づく)
    # 全 sim ≥ 0.95 + bound compliance ≥ 0.9 → Tier-A
    tiers = {'A': [], 'B': [], 'C': [], 'D': []}
    for r in scored:
        s_min = r['s1_weakest_link']
        bc = r['s3_bound_compliance']
        conf = r['confidence']
        if s_min >= 0.95 and bc >= 0.90 and conf >= 0.85:
            tiers['A'].append(r)
        elif s_min >= 0.90 and bc >= 0.70 and conf >= 0.75:
            tiers['B'].append(r)
        elif s_min >= 0.85 and conf >= 0.65:
            tiers['C'].append(r)
        else:
            tiers['D'].append(r)

    print("\n=== 階層分布 ===")
    for k, v in tiers.items():
        print(f"  Tier-{k}: {len(v)} triangles")

    print("\n=== Tier-A サンプル (top 5) ===")
    for r in tiers['A'][:5]:
        a, b, c = r['triangle']
        s_ab, s_bc, s_ac = r['sims']
        print(f"\n  {a} ↔ {b} ↔ {c}")
        print(f"    sim:  {a}↔{b}={s_ab:.4f}, {b}↔{c}={s_bc:.4f}, {a}↔{c}={s_ac:.4f}")
        print(f"    s1 (weakest-link)         = {r['s1_weakest_link']:.4f}")
        print(f"    s2 (angular tightness)    = {r['s2_angular_tightness']:.4f}")
        print(f"    s3 (Schubert compliance)  = {r['s3_bound_compliance']:.4f}")
        print(f"    s4 (SNN)                  = {r['s4_snn']:.4f}")
        print(f"    confidence = {r['confidence']:.4f}")

    # GT ペアセットを構築 (Tier-A の各三角形から 3 ペアを抽出)
    gt_pairs_a = set()
    for r in tiers['A']:
        a, b, c = r['triangle']
        for u, v in [(a, b), (b, c), (a, c)]:
            gt_pairs_a.add(frozenset([u, v]))
    print(f"\nTier-A 由来の unique GT ペア数: {len(gt_pairs_a)}")

    return tiers, scored


if __name__ == '__main__':
    tiers, scored = main()

    # 結果を JSONL で保存
    out_path = '/mnt/user-data/outputs/triadic_gt_results.jsonl'
    with open(out_path, 'w') as f:
        for tier_name, lst in tiers.items():
            for r in lst:
                obj = {
                    'tier': tier_name,
                    'A': r['triangle'][0],
                    'B': r['triangle'][1],
                    'C': r['triangle'][2],
                    's_AB': r['sims'][0],
                    's_BC': r['sims'][1],
                    's_AC': r['sims'][2],
                    'score_weakest_link': r['s1_weakest_link'],
                    'score_angular_tightness': r['s2_angular_tightness'],
                    'score_bound_compliance': r['s3_bound_compliance'],
                    'score_snn': r['s4_snn'],
                    'confidence': r['confidence'],
                }
                f.write(json.dumps(obj) + '\n')
    print(f"\n結果を保存しました: {out_path}")
