# Yes ペアの reason キーワード3分類 (`analysis/split_by_reason.py`)

Yes 判定ペアを `reason` フィールドのキーワードで「完全一致」「高類似」「類似」の
3 グループに分類し、それぞれ JSONL と画像を別ディレクトリに保存する。

`split_same_id.py` と同じ入力を独立して処理する（依存関係なし）。

---

## スクリプト

```
/home/sonozuka/design_similarity/analysis/split_by_reason.py
```

---

## 入出力

| | パス | 形式 |
|---|---|---|
| 入力 JSONL | `/mnt/eightthdd/uspto/yes_pair/{backend}_yes_pairs/{year}.jsonl` | JSONL |
| 入力 画像 | `/mnt/eightthdd/uspto/yes_pair/{backend}_yes_image_pair/` | PNG |
| 出力（完全一致） JSONL | `/mnt/eightthdd/uspto/yes_pair/{backend}/exact_match/jsonl/{year}.jsonl` | JSONL |
| 出力（完全一致） 画像 | `/mnt/eightthdd/uspto/yes_pair/{backend}/exact_match/images/` | PNG |
| 出力（高類似） JSONL | `/mnt/eightthdd/uspto/yes_pair/{backend}/high_similar/jsonl/{year}.jsonl` | JSONL |
| 出力（高類似） 画像 | `/mnt/eightthdd/uspto/yes_pair/{backend}/high_similar/images/` | PNG |
| 出力（類似） JSONL | `/mnt/eightthdd/uspto/yes_pair/{backend}/similar/jsonl/{year}.jsonl` | JSONL |
| 出力（類似） 画像 | `/mnt/eightthdd/uspto/yes_pair/{backend}/similar/images/` | PNG |

入力元のファイルは削除・移動せず、コピーのみ行う。

---

## 分類ロジック

高類似パターンを先にチェックし、`substantially identical` が完全一致に混入するのを防ぐ。

```
reason
  │
  ├─ HIGH_SIMILAR_PATTERNS にヒット → high_similar
  │
  ├─ EXACT_PATTERNS にヒット        → exact_match
  │
  └─ どちらにもヒットしない          → similar
```

### 完全一致パターン（EXACT_PATTERNS）

| パターン | 例 |
|---------|-----|
| `\bindistinguishable\b` | "creating a visually indistinguishable overall impression" |
| `\bno\s+discernible\s+differences?\b` | "with no discernible differences in overall shape" |
| `\bidentical\b` | "Both designs feature identical overall shape" |

### 高類似パターン（HIGH_SIMILAR_PATTERNS）

| パターン | 例 |
|---------|-----|
| `\bsubstantially\s+identical\b` | "creating a substantially identical visual impression" |
| `\bmatching\s+proportions?\b` | "with matching proportions and layout" |
| `\bmatching\s+patterns?\b` | "matching patterns of surface ornamentation" |
| `\bsame\s+(?:overall\s+)?configuration\b` | "same overall configuration of components" |
| `\bsame\s+arrangement\b` | "same arrangement of decorative elements" |
| `\bsame\s+silhouette\b` | "same silhouette and profile" |
| `\bsame\s+overall\s+shape\b` | "same overall shape and form" |

---

## 出力スキーマ

入力レコードのフィールドをそのまま引き継ぎ、完全一致・高類似グループのみ以下を追加：

| フィールド | 内容 |
|-----------|------|
| `matched_patterns` | ヒットした正規表現パターンのリスト（例: `["\\bidentical\\b"]`） |

出力例（`exact_match`）：

```json
{
  "source": "D0546588",
  "target": "D0555918",
  "reason": "Both designs feature an identical X-shaped frame structure...",
  "matched_patterns": ["\\bidentical\\b"]
}
```

---

## ディレクトリ構造（`{backend} = qwen` の場合）

```
/mnt/eightthdd/uspto/yes_pair/
  qwen_yes_pairs/          ← 入力 JSONL（変更なし）
  qwen_yes_image_pair/     ← 入力 画像（変更なし）
  qwen/
    exact_match/
      jsonl/
        2007.jsonl
        2008.jsonl
        ...
      images/
        {src}__{tgt}.png
    high_similar/
      jsonl/
        2007.jsonl
        ...
      images/
        {src}__{tgt}.png
    similar/
      jsonl/
        2007.jsonl
        ...
      images/
        {src}__{tgt}.png
```

---

## 実行方法

```bash
python analysis/split_by_reason.py
```

バックエンドはスクリプト冒頭の `BACKEND` 変数で切り替える：

```python
BACKEND = "qwen"    # "gemini" | "qwen"
```

### スキップモード（resume）

スクリプト起動時に出力先 3 ディレクトリ（`exact_match/`, `high_similar/`, `similar/`）の
既存 JSONL を読み込み、処理済みの `(source, target)` ペアをスキップして未処理分のみ追記する。
中断後の再開や、新年度データ追加時の差分更新に使用できる。

- JSONL は追記モードのため、スキップ判定なしに再実行すると重複が発生する（スキップモードで防止）
- 画像は `shutil.copy2` による上書きのため重複しない
- 完全に作り直す場合は出力ディレクトリを削除してから実行：

```bash
rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/exact_match
rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/high_similar
rm -rf /mnt/eightthdd/uspto/yes_pair/qwen/similar
python analysis/split_by_reason.py
```

---

## 前後の処理との関係

| 前工程 | 本スクリプト | 後工程 |
|--------|-------------|--------|
| `extract_yes_pairs.py`（STEP 4） | `analysis/split_by_reason.py` | 類似ペアの分析・モデル学習用データ作成 |
| `{backend}_yes_pairs/*.jsonl` | → `exact_match/`, `high_similar/`, `similar/` | — |
| `{backend}_yes_image_pair/` | → 同上（コピー） | — |

`split_same_id.py` と同じ入力を独立して処理するため、実行順序に依存関係はない。