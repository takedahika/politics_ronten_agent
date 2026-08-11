# Substack Gmail 検知 GAS スクリプト

Gmailに届いた Substack の新着エッセイメールを自動検知し、メール本文・タイトル・記事URLを抽出して GitHub Actions (`propose_topics.yml`) に渡す Google Apps Script (GAS) です。

---

## 🚀 セットアップ手順（約3分）

### 1. Google Apps Script の新規作成
1. [Google Apps Script (script.google.com)](https://script.google.com/) を開きます。
2. **「新しいプロジェクト」** をクリックします。
3. 左上のプロジェクト名を「**Substack Gmail Trigger**」などに変更します。

### 2. コードの貼り付け
1. このフォルダにある [`Code.gs`](file:///Users/hikarisuenaga/Library/CloudStorage/GoogleDrive-hikari.suenaga.sci@gmail.com/マイドライブ/Obsidian%20Vault/02_Homemade_Apps/33_ronten_no_genzaichi/gas/Code.gs) の内容をコピーして、エディタの `Code.gs` に上書き貼り付けします。

### 3. GitHub アクセストークン (PAT) の設定
1. GitHub の [Personal Access Tokens (classic)](https://github.com/settings/tokens) を開き、**`repo` スコープ**（または `workflow`）付きのトークンを発行します。
2. GAS エディタの左メニュー「⚙️ **プロジェクトの設定**」をクリックします。
3. 一番下の「**スクリプト プロパティ**」で「**スクリプト プロパティを追加**」をクリックします。
   - プロパティ: `GITHUB_PAT`
   - 値: 発行した GitHub トークン (`ghp_...`)
4. 「スクリプト プロパティを保存」をクリックします。

### 4. 初回実行（権限の承認）
1. コードエディタに戻り、上部の関数選択で `checkSubstackEmails` を選択します。
2. **「実行」** を押します。
3. 初回のみ「承認が必要です」というダイアログが出ます。
   - 「権限を確認」 → 自分のGoogleアカウントを選択 → 「詳細」 → 「Substack Gmail Trigger（安全ではないページ）に移動」 → 「許可」 を選択します。

### 5. 自動実行トリガーの設定
1. 左メニューの「⏰ **トリガー**」をクリックします。
2. 右下の「**トリガーを追加**」をクリックします。
   - 実行する関数を選択: `checkSubstackEmails`
   - イベントのソースを選択: `時間主導型`
   - 時間ベースのトリガーのタイプを選択: `分ベースのタイマー`
   - 時間の間隔を選択: `10分おき` または `15分おき`
3. 「保存」をクリックします。

---

## 💡 動作の仕組み
1. GASが10分〜15分おきにGmailを検索（`from:substack.com is:unread`）
2. 新着メールが見つかったら、メール本文・タイトル・URLを抽出
3. GitHub API 経由で Actions (`propose_topics.yml`) を起動
4. 処理したメールには `Processed_RontenBot` ラベルを付与して既読化（重複処理を防ぎます）
