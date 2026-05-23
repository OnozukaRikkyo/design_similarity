# 意匠特許類似ペア Ground Truth 抽出 — 手法批判と提案

**対象データ**: `all.jsonl`（1,530エッジ、1,030ノード、USPTO意匠特許のペア類似判定）

---

## 1. データ実態調査の結果（事前検証）

提案前に、データそのものが孕む構造的問題を特定しました。

### 1.1 LLM 判定は三角整合性を満たさない（決定的所見）

`judgment=Yes & confidence=5` のエッジで構成される部分グラフから、第3ノード C が観測されている三角形（A–B Yes, B–C Yes, A–C が観測済み）を全列挙したところ、

- 観測総数: **200 件**
- A–C が `Yes` に伝播: **0 件**
- A–C が `No`: **200 件（100%）**
- うち `sim > 0.95` で No判定: **124 件**

「A=B かつ B=C ならば A=C」が成立すべき *identical* の文脈で、200/200 が破綻しています。これは LLM 判定が**ペア毎に独立にプロンプトされる「局所判断」**であり、グローバル整合性を欠くという構造的特性を示します。可視化した実例（先のSVG）では、`D0574417 ↔ D0579481` が **judgment=No, sim=0.9855** にもかかわらず、理由文には *"identical line drawings with no discernible differences ... they are the same design"* と書かれています。

**含意**: `judgment` フィールド単独を Ground Truth として採用する設計は、200/200 の不整合により直ちに却下されます。

### 1.2 判定フィールドと理由文の内部矛盾

`judgment=No` だが理由文に強い同一性表現を含む 9 件（sim>0.99）が確認されました。これは LLM がプロンプト指示と内部知識の間でドリフトしている結果と解釈できます。

### 1.3 信号の分布

| 集計 | 数値 |
|---|---|
| 全エッジ | 1,530 |
| ユニークノード | 1,030 |
| Yes / No / Unknown | 216 / 1,064 / 250 |
| Yes & conf=5 | 216 |
| No & sim>0.99 | 9 |
| 連続番号 (差≤5) の Yes-conf5 | 52 |
| 番号差>100 の Yes-conf5 | 164 |
| Yes-only グラフの連結成分数 | 93 |
| 最大連結成分のサイズ | 17 ノード |

連続番号ペアの多くは USPTO の continuation/divisional に対応する出願族と推測できますが、番号差>100の Yes が 164 件もある事実は、「単純な番号近接や family ID では捕まらない真の意匠類似」が存在することを示しています。

---

## 2. 添付資料 (Disparity Filter / ORC-ManL / GraphPruning) に対する批判

添付の手法群は**バックボーン抽出**（巨大な重み付きネットワークから統計的に有意なエッジを残す）が目的であり、**ground truth 抽出**とは異なる問題に最適化されています。本タスクへの適用について以下を指摘します。

### 2.1 規模の不適合

Serrano et al. (2009) の Disparity Filter は、**数万〜数百万エッジ規模の Hairball ネットワーク**を想定して設計されています。本データは 1,530 エッジ・1,030 ノードと小さく、統計的有意性検定（次数ベースの p 値）はノードあたりのエッジ数が少なすぎて意味のある分布を形成しません。特にノードの**約2/3 は次数1**であり、Disparity Filter の核心である「ノードの強度分布からの逸脱」を測れません。

### 2.2 目的関数の不一致

- Backbone extraction の目的: **構造的に重要なエッジ**を保存
- GT 抽出の目的: **判定の信頼性が高いエッジ**を保存

Disparity Filter は重み(=cosine similarity)の絶対値を「強い証拠」として扱いますが、データが示すのは「**sim>0.99 でも 9件は No 判定**」「**No判定でも理由文に identical を含む**」というように、cosine similarity と真のラベルの相関は強くないということです。重みベースの枝刈りは、本タスクで生じる誤りに対して直接的な救済になりません。

### 2.3 ORC-ManL の幾何前提

ORC-ManL (ICLR 2025) は「最近傍グラフの偽エッジ（多様体上のショートカット）を負曲率で検出」しますが、これが有効なのは**真のラベルが多様体構造を反映している場合**です。本データの LLM 判定は前項で見たように三角整合性を欠くため、Ollivier-Ricci 曲率が「真のラベルの構造」を測っているのか「LLM のクセ」を測っているのか識別できません。

### 2.4 結論

添付の手法群は **GT が確定した後の二次的なフィルタリング工程**で（残る曖昧エッジに対して）使う価値はあるものの、**GT 抽出の主軸として採用すべきではありません**。GT 抽出は別の問題設定 — *programmatic weak supervision with conflicting noisy sources* — に属します。

---

## 3. 候補手法の批判的検討

各手法について「本タスクで本当に効くか」を個別評価します。

### 3.1 画像 Perceptual Hash (pHash / dHash / DINOHash)

**位置づけ**: 画像レベルの独立信号として、LLM 判定とは無相関なノイズ特性を持つ — これがアンサンブルの根拠になります。

- **dHash / pHash (classical)**: 線画に対しては高速かつ十分。ICLR 2025 級の手法を使うまでもありません。Hamming距離 ≤ 4/64 で near-duplicate と判定するのが標準実務 (MDPI Electronics, 2026 比較研究で確認)。
- **DINOHash (ICML 2025)**: DINOv2 特徴 + 敵対的微調整で SOTA。圧縮・クロップ・敵対的攻撃に頑健。ただし**カラー自然画像で学習されており、線画 (TIFF 白黒) への直接適用は性能保証外**。

**批判**: 意匠図はそもそも「線画 + ハッチング + 部分破線」で、自然画像向け hash の前処理（DCT、wavelet）の前提と合いません。dHash で実験的に試し、ROC を引いて閾値を決めるのが堅実です。

**結論**: **採用**。ただし「LLM の判定と独立な信号」としてアンサンブルに組み込み、単独 GT 化はしません。

### 3.2 画像 Graph Edit Distance (GED)

**位置づけ**: 意匠図を線画グラフ (vertex = junction, edge = stroke) に変換し、グラフ編集距離を計算する。Sanfeliu & Fu (1983)、最新は NeurIPS 2024 GraphEdX (neural GED with general costs)。

**批判**:

1. **計算量**: 厳密 GED は NP-hard。Neural surrogate でも全1,530ペアを走らせる前段に「全画像 → グラフ」変換コストが膨大。
2. **ノード抽出の精度依存**: HAWPv3 等で junction を抽出した後の GED 計算ですが、HAWPv3 のノイズが GED に直接乗ります（ユーザの JTPN プロジェクトの議論と同型）。
3. **オーバースペック**: exact match の判定なら、phash の Hamming 距離で十分。GED は **near-similar pairs の*順位付け***にこそ威力を発揮しますが、本タスクは「明らかな exact match の抽出」が目的なので、ここに高コストな手法を投入する必要はありません。

**結論**: **不採用（本フェーズでは）**。GED は後段の JTPN 評価や類似度ランキングの検証に温存。

### 3.3 テキスト編集距離 (理由文の表層比較)

**位置づけ**: 同一ペアに対する LLM 理由文の一貫性、または「identical 系定型表現」の出現を編集距離で測定。

**批判**: 同一ペアは1度しか評価されていない (双方向観測ペア = 0 件と確認) ため、編集距離による LLM 自己整合性測定はこのデータでは適用不可能。**ただし**理由文の n-gram レベルでの「強い同一性パターン」 (`identical line drawings`, `no discernible differences`, `depict the same` etc.) の有無は別の信号として有効です — これは編集距離ではなくキーワードベース。

**結論**: **キーワード抽出として採用、編集距離としては不採用**。

### 3.4 ランダム・パーコレーション / 摂動による頑健性検証

**位置づけ**: exact match と推定されたペアの画像にランダム摂動（小規模 affine, noise, 描画太さ変動）を加え、CLIP/IMPACT embedding が依然として sim>0.99 を維持するか確認する。Test-Time Augmentation (NeurIPS 2020) 系の発想。

**意義**: これは「GT を新規に抽出する手法」ではなく「**抽出した GT 候補の頑健性を検証する手法**」です。摂動後にも sim>0.99 が保たれるなら、その類似度は「特定の描画スタイルの一致」ではなく「**真の意匠の一致**」を反映している証拠になります。逆に摂動で sim が急降下するペアは、実質的な意匠類似ではなく「同じスキャナ・同じレンダラ由来の表層的一致」の可能性があり、GT から除外すべきです。

**注意点**: 摂動の強度設計が結果を支配します。意匠特許は線の細さ・位置の数 mm の差で出願単位が変わる可能性があるため、**摂動は意匠的に意味を持たない範囲（例: gamma補正、JPEG圧縮、±2px translation）に限定**する必要があります。これは IMPACT/CLIP 系 embedding が「描画スタイル不変性」を持っているかを直接測るテストになります。

**結論**: **採用。ただし「検証ステップ」として、抽出後の Tier-A 候補に適用**。

### 3.5 三角整合性検出 (transitivity violation)

**位置づけ**: A↔B Yes ∧ B↔C Yes ∧ A↔C No という不整合ペアの体系的検出。先の分析で 200 件確認済み。

**批判**: 単純に「3項関係に基づいて Yes に修正する」ことは**やってはいけません**。理由は以下:

- 三角不整合が起きる原因は LLM の局所判断のブレだけでなく、「**A と B は形状で似ている、B と C は装飾で似ている、A と C はどちらも似ていない**」という**多側面類似**の可能性があります。
- 意匠類似判定は連続値の感覚的判断であり、必ずしも数学的同値関係を成しません。

正しい使い方は、**「三角整合性を満たすクラスタ」を抽出して GT の高信頼層に格上げ**することです。すなわち、3点 (A, B, C) が**互いに全てYes**となるクリーク (3-clique) は、各エッジ判定が独立に Yes であり、かつ判定の整合性も成立した強い証拠であり、Tier-A の有力候補です。

**結論**: **採用（クリーク発見のフィルタとして）**。

### 3.6 連結成分 / 特許族構造

**位置づけ**: Yes-conf5 グラフの連結成分は 93 個（最大 17 ノード）。これは推定的な「意匠族」を構成します。

**批判**: 連結成分内の任意の2ノード間が真に similar であるとは限りません。直接エッジで Yes 判定されていないペア (例: 17ノードCCの中の遠い2点) は、**まだ LLM に評価されていない可能性**を含みます。連結成分の transitive closure を取って GT に加えることは**過大な拡張**であり、避けるべきです。

**結論**: **採用（クラスタ構造の可視化と探索の入口として）。ただし transitive closure による GT 拡張は禁止**。

### 3.7 Snorkel-style ラベルモデル (programmatic weak supervision)

**位置づけ**: 複数の独立な labeling function (LF) を作り、それぞれの精度を unlabeled data 上で推定し、確率的に統合する (Ratner et al., 2017; Fu et al., ICML 2020; "Annotation 3.0" 2025)。

**本タスクへの適用**:

| LF | 判定根拠 |
|---|---|
| LF1 | `judgment == "Yes"` |
| LF2 | `confidence == 5` |
| LF3 | `similarity >= threshold` |
| LF4 | `reason` に identity-phrase を含む |
| LF5 | dHash Hamming 距離 ≤ k |
| LF6 | 3-clique のメンバーである |
| LF7 | 摂動後も sim>0.99 を維持 |

**批判**: Snorkel の前提は「LF 同士の相関が小さいか、相関を推定できる」こと。本データでは LF1, LF2, LF4 は全て同じ LLM 呼び出しに由来し**完全相関**しているため、Snorkel の generative model はこれらを独立信号として処理できません。LF5, LF7 は LLM と独立なので、Snorkel の枠組みが有効です。

**結論**: **採用、ただし LLM 由来の信号は1つに集約**してから入力。

---

## 4. 「Exact match を GT positive にする」設計の根本的批判

ユーザ提案の核心 — exact match を見つけ、その特徴から類似ペアの確信度を高める — について、以下の懸念があります。

### 4.1 Exact match は意匠類似ペアの「特殊な極限」であって代表ではない

USPTO の continuation/divisional 制度のもとで「ほぼ同一図面」のペアが多数存在することは事実です（連続番号 Yes ペアが 52 件、これらの典型）。しかしこれらは:

- **同一発明者・同一出願人・同一意匠の絵を流用**したものが大半
- **真の prior art retrieval で問題になる「異なる出願人が独立に出した類似意匠」とは性質が異なる**

Exact match から学習した特徴量・閾値は、**continuation/divisional の「同一図面」**を区別する能力に最適化され、本来の prior art 問題（番号差>100 の真の意匠類似）に対して**過剰適合**するリスクがあります。

実際にデータは、番号差>100 の Yes-conf5 が 164 件存在することを示しています。**これら 164 件こそが、JTPN 評価のための本命の Ground Truth 候補です**。Exact match (typically 連続番号) はノイズ評価の参照点として有用ですが、**それ単独で GT セットを構成すべきではありません**。

### 4.2 Negative GT (確信度の高い「非類似」) の重要性

意匠類似判定の評価には、

- **Hard positive**: 番号差大・出願人異・しかし真に類似 → 164件の遠距離 Yes-conf5
- **Hard negative**: 高 cosine similarity だが意匠的に非類似 → No-conf5 で sim>0.95 のもの

の両方が必要です。**ユーザ提案には negative GT の議論が欠落**しています。Hard negative こそ、IMPACT/CLIP 系 embedding の弱点を測定する critical 信号です。

---

## 5. 提案: 4階層 Ground Truth 抽出パイプライン

以上の批判を踏まえ、以下の階層化アプローチを提案します。各層は**独立な信号の合意**によって定義され、判定根拠が個別に説明可能です。

### Layer 1 — Tier-A (Exact-Match Positive, n=17)

**条件 (全て AND)**:
1. `judgment == "Yes"` かつ `confidence == 5`
2. `similarity >= 0.99`
3. `reason` に identity-phrase (`identical line drawings`, `depict the same`, `no discernible differences`, etc.) を含む

**性質**: continuation/divisional family が大多数。GT positive の「アンカー」だが、retrieval 評価本体ではなく**較正参照**として使用。

### Layer 2 — Tier-B (Strong Positive, n=83)

**条件 (全て AND)**:
1. `judgment == "Yes"` かつ `confidence == 5`
2. `similarity >= 0.95`
3. `reason` に identity-phrase を含む
4. **3-clique のメンバー** または **Tier-A エッジと共有ノードを持つ**

**性質**: 高 cosine sim・LLM 高信頼度・3項整合性の3条件で fully cross-validated。

### Layer 3 — Tier-C (Distant Positive, expected ≤164)

**条件 (全て AND)**:
1. `judgment == "Yes"` かつ `confidence == 5`
2. **番号差 > 100** (異なる出願時期、独立した意匠類似の可能性が高い)
3. **dHash / phash で near-duplicate ではない** (= 図面流用ではない)

**性質**: これが retrieval 評価本体の主力 GT。「異なる出願人による真の意匠類似」を含む。

### Layer 4 — Tier-N (Hard Negative, n≈9〜数十)

**条件 (全て AND)**:
1. `judgment == "No"` かつ `confidence == 5`
2. `similarity >= 0.95`
3. **理由文に identity-phrase を含まない**（内部矛盾の 2 件を除外）

**性質**: 高 cosine sim だが意匠的に非類似 → embedding の偽陽性を検出する critical pair。

### 除外集合

- 三角不整合に関与し、他層に分類されなかったエッジ → 「**保留 (gray zone)**」として別途人手レビューに回す候補。

---

## 6. パイプラインの実装疑似コード

```python
import json
import re
import networkx as nx
from collections import defaultdict

with open('all.jsonl') as f:
    data = [json.loads(line) for line in f]

# --- Signal extraction ---
IDENTITY_PHRASES = [
    'identical line drawings', 'depict the same', 'identical overall',
    'no discernible differences', 'no perceptible differences',
    'they are the same', 'depict identical', 'identical structural',
]
DIFFERENTIATION_PHRASES = [
    r'\bdiffer\b', r'\bdistinct\b', r'\bdifferent\b'
]

def signal_identity(reason):
    r = reason.lower()
    return any(p in r for p in IDENTITY_PHRASES)

def signal_diff(reason):
    r = reason.lower()
    return any(re.search(p, r) for p in DIFFERENTIATION_PHRASES)

def patent_number_gap(a, b):
    try:
        return abs(int(a[1:]) - int(b[1:]))
    except:
        return None

# --- Graph construction ---
G_yes = nx.Graph()
for d in data:
    if d['judgment']=='Yes' and d['confidence']==5:
        G_yes.add_edge(d['source'], d['target'])

# 3-clique enumeration
cliques3 = [c for c in nx.enumerate_all_cliques(G_yes) if len(c)==3]
nodes_in_3clique = set(n for c in cliques3 for n in c)

# Tier-A エッジから1ホップ以内のノード
tier_a_edges = []
for d in data:
    if (d['judgment']=='Yes' and d['confidence']==5 and 
        d['similarity']>=0.99 and signal_identity(d['reason'])):
        tier_a_edges.append(d)
tier_a_nodes = set()
for d in tier_a_edges:
    tier_a_nodes.add(d['source']); tier_a_nodes.add(d['target'])

# --- Tier classification ---
tiers = {'A': [], 'B': [], 'C': [], 'N': [], 'gray': []}

for d in data:
    s, t = d['source'], d['target']
    gap = patent_number_gap(s, t)
    in_3clique = (s in nodes_in_3clique) and (t in nodes_in_3clique)
    near_tier_a = (s in tier_a_nodes) or (t in tier_a_nodes)
    id_phrase = signal_identity(d['reason'])
    diff_phrase = signal_diff(d['reason'])
    
    # 内部矛盾は除外
    if d['judgment']=='No' and id_phrase and not diff_phrase:
        tiers['gray'].append(('contradiction', d))
        continue
    
    # Tier-A
    if (d['judgment']=='Yes' and d['confidence']==5 and 
        d['similarity']>=0.99 and id_phrase):
        tiers['A'].append(d)
    # Tier-B
    elif (d['judgment']=='Yes' and d['confidence']==5 and 
          d['similarity']>=0.95 and id_phrase and 
          (in_3clique or near_tier_a)):
        tiers['B'].append(d)
    # Tier-C
    elif (d['judgment']=='Yes' and d['confidence']==5 and 
          gap and gap > 100):
        tiers['C'].append(d)
    # Tier-N (hard negative)
    elif (d['judgment']=='No' and d['confidence']==5 and 
          d['similarity']>=0.95 and not id_phrase):
        tiers['N'].append(d)

# 三角不整合検出
yes_edge_set = {frozenset([d['source'],d['target']]): d for d in data 
                if d['judgment']=='Yes' and d['confidence']==5}
neighbors = defaultdict(set)
for e in yes_edge_set:
    a,b = list(e); neighbors[a].add(b); neighbors[b].add(a)

all_edges = {frozenset([d['source'],d['target']]): d for d in data}
triangle_violations = set()
for a in neighbors:
    for b in neighbors[a]:
        for c in neighbors[b]:
            if c==a or c in neighbors[a]: continue
            ek = frozenset([a,c])
            if ek in all_edges and all_edges[ek]['judgment']=='No':
                triangle_violations.add(ek)

# 三角不整合に関与するエッジはGTから降格
for tier in ['A','B','C','N']:
    new_tier = []
    for d in tiers[tier]:
        ek = frozenset([d['source'], d['target']])
        if ek in triangle_violations:
            tiers['gray'].append(('triangle_violation', d))
        else:
            new_tier.append(d)
    tiers[tier] = new_tier

print(f"Tier-A: {len(tiers['A'])}")
print(f"Tier-B: {len(tiers['B'])}")
print(f"Tier-C: {len(tiers['C'])}")
print(f"Tier-N: {len(tiers['N'])}")
print(f"Gray (excluded): {len(tiers['gray'])}")
```

---

## 7. 検証戦略

抽出結果が信頼に値することを示すための independent な検証を3層で実施します。

### 7.1 画像 perceptual hash による Tier-A 検証

Tier-A の各ペアについて画像を読み込み、dHash を計算。Hamming 距離 ≤ 8/64 の割合を測定する。**期待値: ≥ 90%**。低ければ Tier-A の定義が「画像同一」ではなく「LLM の同一性表現の textbook 例」に過適合している可能性。

### 7.2 摂動パーコレーションによる Tier-A の頑健性検証

Tier-A の各画像に以下の小摂動を適用し、IMPACT/CLIP 系 embedding で再計算した sim が依然として 0.99 以上を保つかを測定:
- ±2 px translation
- ±2° rotation  
- gamma ∈ [0.9, 1.1]
- JPEG compression quality ∈ [70, 95]
- 5% pepper noise

**期待値: Tier-A 平均で sim>0.95 を維持**。維持できないペアは「同じスキャナ・同じレンダラ由来の表層一致」の可能性があり、Tier-A から降格。

### 7.3 連続番号 vs 番号差大 の Tier-A 比率

Tier-A 内で連続番号ペアと番号差>100 ペアの比率を集計。**連続番号が >80% を占めれば、Tier-A は continuation/divisional family bias が強い**ことを意味し、これを retrieval 評価本体の GT に直接使うことは慎重にすべき (Tier-C の役割が重要に)。

---

## 8. 残るリスクと limitations

1. **Tier-C の規模**: 番号差>100 の Yes-conf5 が 164 件、ここから dHash で「真に異なる絵」のみ残すと、おそらく 100 件前後に減少。これが GT の最終規模を左右する律速。
2. **負例の不足**: 高 sim & No-conf5 は 9〜数十件にとどまり、評価メトリクスの統計検出力が不足する可能性。pseudo hard negative を embedding 空間から追加サンプリングする必要があるかもしれません。
3. **LLM プロンプト自体のバイアス**: 全 1530 エッジが同一プロンプトで処理されている場合、判定の系統誤差は全レイヤで共有されます。可能なら、抽出した GT 候補のサブセットを **別 LLM (Gemini/GPT-4o) で再評価**し inter-model agreement を取ることが望ましい。
4. **意匠分類による偏り**: データの type 分布 (perspective 1447, overview 74, front 9) は perspective に強く偏っており、抽出された GT も perspective view 中心になります。多視点 retrieval (ユーザの JTPN/OT-PatentCLIP 文脈) の評価には不十分かもしれません。

---

## 9. 結論

- **添付資料の手法 (Disparity Filter / ORC-ManL) は本タスクには不適合** — 規模も目的関数も合っていません。
- **Exact match を GT 抽出の中心に据える方針には危険性があり**、continuation/divisional family への過適合が retrieval 評価本体を歪めます。
- 提案する 4 階層（Tier-A/B/C/N）は **独立した信号の合意**に基づき、各層が異なる役割（較正、cross-validated positive, 主力 GT, hard negative）を担います。
- 三角整合性、画像 phash、摂動頑健性の3つを**独立した検証ステップ**として組み込むことで、抽出された GT の信頼性を説明可能な形で担保します。
- 全ての判定は **boolean threshold の連鎖**で表現されているため、各エッジが特定の Tier に分類された理由を1行で再構成できます（= 説明可能性の要件を満たす）。
