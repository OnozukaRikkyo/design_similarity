# パイロットサンプリング (`extract_pilot.py`)

220 行の入力 CSV から、6 層・計 23 行を層別サンプリングして
パイロット分析セットを作成する。

LLM API のコストを抑えながら、M1/M2/M3/M5/B を適用すべき
代表的なケースを網羅的にカバーするための設計。

処理順序の全体像は [pipeline.md](pipeline.md) を参照。

---

## スクリプト

```
vector/reasoning/extract_pilot.py
```

---

## 出力ファイル

```
vector/output/{CLASS}/{sim_func}/reasoning/
  pilot_24.csv       — 23 行のパイロットサンプル
  pilot_strata.csv   — 層別監査テーブル（n_target / n_actual）
```

---

## 層定義

| 層 ID | 件数 | 条件 | 意図 |
|-------|------|------|------|
| L1 | 2 | `confidence=5` & `judgment=No` & reason に完全一致キーワード | 自己矛盾ケース（LLM の判定根拠と結論が乖離）|
| L2 | 4 | `similarity ≥ 0.99` & `judgment=No` | 高類似度パラドックス（ベクトル距離は近いが LLM は否定）|
| L3 | 5 | `similarity ≥ 0.99` & `judgment=Yes` | 高類似度マッチ（最も確信度の高い一致群）|
| L4 | 5 | `similarity` 最小 & `judgment=Yes` | 低類似度マッチ（ベクトル距離が遠いが LLM は肯定）|
| L5 | 5 | `similarity ∈ [0.965, 0.975]` | キャリブレーション境界（閾値前後の曖昧ゾーン）|
| L6 | 2 | networkx 最大連結成分に属するエッジ | デザインファミリークラスター（同一出願人の類似意匠群）|

**完全一致キーワード定義（L1）:**

```python
EXACT_KEYWORDS = ["identical", "exact", "same"]
```

単語境界 (`\b`) 付き正規表現でマッチング。大文字小文字は区別しない。

---

## 層選択ロジック

各層は直前の層で `used_idx`（選択済みインデックス集合）を更新し、
重複なく選択する。層の優先順序は L1 → L2 → L3 → L4 → L5 → L6。

### L6: デザインファミリークラスター

`source` / `target` 列で無向グラフを構築し、最大連結成分のノードを特定。
その成分に属する行から 2 件をサンプリングする。

```python
G = nx.Graph()
for _, row in df.iterrows():
    G.add_edge(str(row["source"]), str(row["target"]))
largest = max(nx.connected_components(G), key=len)
```

`networkx` が未インストールの場合は `source` の最頻値グループで代替する。

---

## 監査テーブル（pilot_strata.csv）

| 列名 | 内容 |
|------|------|
| `stratum` | 層 ID（L1–L6）|
| `n_target` | 目標件数 |
| `n_actual` | 実際に選択された件数 |
| `description` | 層の説明 |

`n_actual < n_target` の場合、その層の候補行が不足していることを意味する。

---

## 固定パス

| 種別 | パス |
|------|------|
| 入力 CSV | `vector/output/D18/cosine_numpy/high_sim_perspective_0950_judged.csv` |
| パイロット CSV | `vector/output/D18/cosine_numpy/reasoning/pilot_24.csv` |
| 監査テーブル | `vector/output/D18/cosine_numpy/reasoning/pilot_strata.csv` |
| 乱数シード | `42`（固定）|

## 実行方法

```bash
cd vector/reasoning
python3 extract_pilot.py
```

引数は不要。パスはスクリプト内に固定されている。

---

## 動作確認

```bash
cd vector/reasoning
python3 demo_offline.py
```

期待出力（D18 perspective, 2026-05-20 時点）:

```
Input: 220 rows
Pilot: 23 rows
stratum  n_target  n_actual  description
     L1         2         2  self-inconsistent ...
     L2         4         4  high-sim paradox ...
     L3         5         5  high-sim match ...
     L4         5         5  low-sim match ...
     L5         5         5  calibration boundary ...
     L6         2         2  design-family cluster ...
```

---

## 前後の処理との関係

```
high_sim_perspective_0950_judged.csv  →  extract_pilot.py  →  pilot_24.csv
                                                                   ↓
                              patent_rationale_pms.py（--pilot-csv）
                              patent_visual_probes.py（--pilot-only）
                              prepare_human_annotation.py（入力）
```

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `rank_analysis.py`（Step 4a）| `extract_pilot.py`（Step 0）| Step 1〜4 各スクリプト |