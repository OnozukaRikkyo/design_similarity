# vector/analysis/ — 分析・可視化スクリプト群

## 概要

`join_judgments.py`（Step 5）が生成した `rank_judgments/{sim_func}/all.jsonl` を入力として、
統計分析・可視化・データエクスポートを行うスクリプト群。

---

## スクリプト一覧

| スクリプト | 役割 |
|---|---|
| `rank_analysis.py` | CCDF・散布図・ペア比較画像を生成 |
| `export_yes_reasons.py` | Yes 判定ペアを CSV にエクスポート |
| `export_non_exact_pairs.py` | 完全一致でない Yes ペアの画像を出力 |

---

## 共通入力

**3 スクリプトすべて同じ入力源:**

```
class/{CLASS}/rank_judgments/{sim_func}/all.jsonl
```

このファイルの `judgment` フィールド（`"Yes"` / `"No"` / `"Unknown"`）を
Similar / Non-similar として使用する。

### judgment フィールドの出所

```
画像ファイル（.TIF）× 2枚
    ↓ Qwen3-VL-4B-Instruct（法的類似性プロンプト）
    ↓ judge_cited_pairs.py
qwen_similarity_results/{year}.jsonl
    ↓ join_judgments.py（Step 5）
rank_judgments/cosine_numpy/all.jsonl  ← ここを読む
```

判定は**画像の視覚内容のみ**に基づく。特許メタデータは使用しない。

### yes_pair/qwen/ との関係

`/mnt/eightthdd/uspto/yes_pair/qwen/` は**使用しない**。

`yes_pair/qwen/`（exact_match / high_similar / similar）は別系統のスクリプトが使用する:

| スクリプト | 入力 |
|---|---|
| `make_two_heatmaps.py` | `yes_pair/qwen/exact_match/`, `high_similar/`, `similar/` |
| `visualize_ergm_network.py` | `yes_pair/qwen/` 以下を再帰的に読み込み |

`vector/analysis/` はこれらとは独立したパイプラインである。

---

## 実行順序

3 スクリプトは互いに独立しており、どの順でも実行できる。
以下は目的に沿った自然な順序:

```bash
cd /home/sonozuka/design_similarity

# 1. 全体把握（CCDF・散布図・ペア比較画像）
python vector/analysis/rank_analysis.py --class D18

# 2. Yes ペアの一覧確認（CSV）
python vector/analysis/export_yes_reasons.py --class D18

# 3. 完全一致でない Yes ペアの詳細確認（画像）
python vector/analysis/export_non_exact_pairs.py --class D18
```

**いずれも resume なし（常に上書き）。** `all.jsonl` を更新した後はそのまま再実行すればよい。

---

## rank_analysis.py

### 出力

```
vector/output/{CLASS}/{sim_func}/
  rank_ccdf_{type}.png               — Figure 1: 順位の CCDF（log-log、Yes/No 別）
  rank_scatter_{type}.png            — Figure 2: 順位 vs コサイン類似度の散布図
  rank_scatter_{type}_zoom.png       — Figure 2b: 散布図拡大（rank ≤ 20, similarity ≥ 0.85）
  rank_density_{type}.png            — Figure 2d: 2次元確率密度関数（全体）
  rank_density_{type}_zoom.png       — Figure 2d-zoom: 2次元確率密度関数（rank ≤ 20 拡大）

class/{CLASS}/rank_analysis/{sim_func}/{type}/pair_comparison/
  {src}--{tgt}_rank{r:03d}.png       — Figure 3: Yes かつ rank ≤ topk の全ペア比較画像
```

### Similar / Non-similar の情報源

散布図の Similar（青・菱形）/ Non-similar（赤・×）は `all.jsonl` の `judgment` フィールド。

```python
# rank_analysis.py 内
recs = [r for r in records if r["judgment"] == "Yes"]   # Similar
recs = [r for r in records if r["judgment"] == "No"]    # Non-similar
```

### 主なオプション

```bash
python vector/analysis/rank_analysis.py --class D18
python vector/analysis/rank_analysis.py --class D18 --top-k 10   # Figure 3 の対象順位
python vector/analysis/rank_analysis.py --class D18 --type front # 画像タイプ指定
```

---

### Figure 2d: 2次元確率密度関数（`rank_density_{type}.png` / `rank_density_{type}_zoom.png`）

#### 概要

散布図（Figure 2）では点が重なって分布の全体構造が見えにくい。
Figure 2d では rank × cosine similarity の空間を**連続な2次元確率密度関数（PDF）**として推定し、1枚の図で全データの統計的分布を表現する。
物理学論文でよく用いられる手法（2D KDE + contourf）に準拠。

#### 確率密度関数の推定方法

`scipy.stats.gaussian_kde` によるカーネル密度推定（KDE）を使用する。

1. **スケール正規化**：rank（1–1000）と similarity（0.38–1.0）はスケールが大きく異なるため、それぞれ $[0, 1]$ に線形変換してからKDEを計算する。
2. **帯域幅**：Scott則（`bw_method='scott'`）で自動決定。サンプル数 $N=1447$ に対して適切な平滑化量を与える。
3. **グリッド評価**：300×300 の等間隔グリッド上でKDEを評価し、最大値で正規化して相対密度 $p/p_{\max} \in [0, 1]$ を得る。
4. **zoom版**：`xlim`/`ylim` で指定した範囲のデータのみを抽出してKDEを再推定し、その領域の密度構造を高解像度で描画する。

#### 描画仕様

| 要素 | 設定 |
|---|---|
| 塗り潰し（`contourf`） | `cmap="Reds"`、$p/p_{\max} \in [0.02, 1.0]$ の20段階。0.02未満は白（背景）。 |
| 等高線（`contour`） | $p/p_{\max} =$ 0.05, 0.2, 0.5, 0.8 の4本、黒細線。 |
| カラーバー | 目盛り 0.2, 0.4, 0.6, 0.8, 1.0。ラベルは $p/p_{\max}$。 |
| オーバーレイ | Similar（Yes）点を青菱形で重ねて表示。 |

```python
# KDE 推定（rank_analysis.py 内）
rx = (all_ranks - rank_lo) / (rank_hi - rank_lo)   # スケール正規化
ry = (all_sims  - sim_lo)  / (sim_hi  - sim_lo)
kde = gaussian_kde(np.vstack([rx, ry]), bw_method="scott")
ZZ  = kde(...).reshape(XX.shape)
ZZ /= ZZ.max()                                       # 相対密度に正規化

# 塗り潰しと等高線
ax.contourf(XX, YY, ZZ, levels=np.linspace(0.02, 1.0, 20), cmap="Reds", extend="neither")
ax.contour( XX, YY, ZZ, levels=[0.05, 0.2, 0.5, 0.8], colors="k", linewidths=0.5)
```

#### 全体図（`rank_density_{type}.png`）から読み取れること

1. **分布は双峰（bimodal）**  
   $p/p_{\max} = 0.5$ の等高線が2つの山を示す。
   - **第1峰**：Rank 1–30、similarity ≥ 0.93（最高密度の核、濃赤）  
   - **第2峰**：Rank 100–250、similarity ≈ 0.85–0.90  
   「ほぼ同一の意匠（近傍ランクに必ず登場する）」と「類似するが別物（中程度のランクに散在する）」の2集団が混在している可能性を示す。

2. **Similar（Yes）点は密度分布の「外側」に位置する**  
   引用された特許ペア（青菱形）の多くは $p/p_{\max} = 0.2$ 等高線の外側にある。
   審査官が類似と判断するペアは、全体の密度主流から外れた統計的に稀な組み合わせであり、
   コサイン類似度だけでは捉えにくい視覚的類似性が存在することを示唆する。

3. **高ランク・低類似度の Yes 点はモデルの限界を示す**  
   Rank 600–900、similarity 0.62–0.79 付近の Yes 点はKDE密度がほぼゼロの白色領域に存在する。
   これはベクトル検索が見逃している意匠類似事例であり、
   コサイン類似度による近傍探索の検索精度の上限（recall@k の限界）を示す外れ値と解釈できる。

#### ズーム図（`rank_density_{type}_zoom.png`）から読み取れること

範囲：Rank ≤ 20、similarity ≥ 0.84。この領域のデータのみで KDE を再推定。

1. **最高密度はRank 1–2 に集中**  
   $p/p_{\max} = 0.8$ の等高線がRank 1–2、similarity ≥ 0.98 付近に収束しており、
   最近傍（Rank 1）は極めて高い類似度を持つ点が密集する。

2. **Rank 5–10 で密度が急落**  
   等高線の間隔がRank 5付近で急に広がり、分布が急速に拡散することを示す。
   Rank 5以降は「ほぼ同一」の集団から「類似するが別物」の集団への遷移領域と見なせる。

3. **Similar（Yes）点はRank 1–15 の広い範囲に分布**  
   ズーム図では Yes 点がRank 1–15 にわたって広く分散しており、
   引用特許は必ずしも最近傍（Rank 1）でなく、中位ランクにも多く存在することが確認できる。

---

#### 解釈上の注意：Yes ラベルは Ground Truth ではない

**Yes/No ラベルは LLM（Qwen3-VL-4B-Instruct）による視覚的類似判定であり、Ground Truth ではない。**  
埋め込みモデル（Qwen3-VL-Embedding-2B）と判定モデルは同一ファミリーであるため、
両者の出力の一致はモデルの独立した検証ではなく、共通の視覚的バイアスを反映している可能性がある。

この前提のもとで、図から**言えること・言えないこと**を以下に整理する。

**言えること**

- Qwen埋め込みモデルによる近傍ランクと、同系統LLMの視覚類似判定には**一定の相関がある**。
- Rank 1–10 に Yes点が集中する傾向は、少なくとも両モデルの出力が整合していることを示す。

**言えないこと**

- 正例が「正しく」判定されているか（独立した Ground Truth がないため評価不能）。
- コサイン類似度が意匠の法的類似性を反映しているか（引用関係 ≠ 視覚的類似）。
- 高ランク・低similarityの Yes点が「検索の失敗」か「LLMの誤判定（False Positive）」かの区別。

真の検証には、人間専門家によるアノテーションまたは法的判断（審判・訴訟記録）を Ground Truth とした評価が必要である。

---

## export_yes_reasons.py

### 出力

```
vector/output/{CLASS}/{sim_func}/yes_sim{threshold}_reasons.csv
```

Yes 判定かつ指定類似度以上のペアを全フィールド付きで CSV に出力する。

### 主なオプション

```bash
python vector/analysis/export_yes_reasons.py --class D18
python vector/analysis/export_yes_reasons.py --class D18 --min-sim 0.9
```

---

## export_non_exact_pairs.py

### 出力

```
class/{CLASS}/rank_analysis/{sim_func}/{type}/non_exact_pairs/
  {src}--{tgt}_rank{r:03d}.png
```

Yes 判定かつ類似度閾値以上のペアのうち、reason に「完全一致」を示すキーワードを含まないペアの画像を出力する。
完全一致キーワードの判定は Qwen3-VL-4B-Instruct に問い合わせる（失敗時は identical / exact / same にフォールバック）。

### 主なオプション

```bash
python vector/analysis/export_non_exact_pairs.py --class D18
python vector/analysis/export_non_exact_pairs.py --class D18 --min-sim 0.9
```

---

## データ更新後の再実行

`qwen_similarity_results/` が更新された場合は `update_downstream.py` を実行する。
Step G（`join_judgments.py`）と H〜J（分析スクリプト群）が自動的に順番に実行される。

```bash
cd /home/sonozuka/design_similarity
python update_downstream.py
```

個別に再実行したい場合:

```bash
# all.jsonl を更新
python vector/join_judgments.py --class D18 --no-resume

# 分析を再実行
python vector/analysis/rank_analysis.py --class D18
python vector/analysis/export_yes_reasons.py --class D18
python vector/analysis/export_non_exact_pairs.py --class D18
```

詳細: [join_judgments.md](join_judgments.md) · [../../UPDATE.md](../../UPDATE.md)

---

## D18 の現状（2026-05-24 確認）

| 項目 | 値 |
|---|---|
| 対象クラス | D18 のみ（他クラスは未作成） |
| 対象年 | 2007〜2022（16 年分） |
| all.jsonl 総件数 | 1,530 件 |
| Yes（Similar） | 217 件 |
| No（Non-similar） | 1,157 件 |
| Unknown | 156 件 |

Unknown は `qwen_similarity_results/` に対応するペアが存在しない年（2020〜2022）のレコード。
`judge_cited_pairs.py` の処理が進むにつれ Yes/No に変わる。

---

## 関連ドキュメント

- [pipeline.md](pipeline.md) — パイプライン全体
- [join_judgments.md](join_judgments.md) — Step 5: all.jsonl の生成と更新手順