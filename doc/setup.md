# セットアップガイド

## 仮想環境 (venv) の自動有効化

このプロジェクトは VS Code でフォルダを開いてターミナルを起動すると、自動で `.venv` が有効になります。

### 仕組み

`.vscode/settings.json` に以下の設定が入っており、VS Code がターミナル起動時に自動で `.venv/bin/activate` を実行します。

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.terminal.activateEnvironment": true,
  "python.terminal.activateEnvInCurrentTerminal": true
}
```

### 初回セットアップ手順

1. VS Code でこのフォルダ (`design_similarity/`) を開く
2. ターミナルを開く（`` Ctrl+` ``）→ プロンプトに `(.venv)` が表示されることを確認
3. 依存パッケージをインストール

```bash
pip install -r requirements.txt
```

### インタープリタが認識されない場合

`Ctrl+Shift+P` → `Python: Select Interpreter` → `.venv` を選択してください。

---

## API キーの設定

Google AI Studio から取得した Gemini API キーを環境変数に設定します。

```bash
export GEMINI_API_KEY="your-api-key-here"
```

毎回設定するのが手間な場合は `~/.bashrc` に追記してください。

```bash
echo 'export GEMINI_API_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc
```