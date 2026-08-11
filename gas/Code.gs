/**
 ==============================================================================
 論点の現在地 — Substack Gmail 自動トリガー (Google Apps Script)
 ==============================================================================
 
 【機能概要】
 あなたのGmailに届いた Substack の新着メールを自動検知し、
 メール本文・タイトル・URLを抽出して GitHub Actions (propose_topics.yml) を起動します。
 
 【設定手順】
 1. https://script.google.com/ を開いて「新しいプロジェクト」を作成
 2. このコードを Code.gs に貼り付ける
 3. 以下の CONFIG の値を設定する（特に GITHUB_PAT）
    ※ GITHUB_PAT は ScriptProperties (スクリプトプロパティ) に保存することも可能です
 4. 手動で `checkSubstackEmails()` を1回実行して、Gmailアクセス権を承認する
 5. トリガー（時計アイコン）を設定:
    - 実行する関数: checkSubstackEmails
    - イベントのソース: 時間主導型
    - 時間の間隔: 10分〜15分おき
 */

const CONFIG = {
  // GitHub の設定
  GITHUB_OWNER: "takedahika",
  GITHUB_REPO: "politics_ronten_agent",
  WORKFLOW_ID: "propose_topics.yml",
  
  // GitHub Personal Access Token
  // ScriptProperties に 'GITHUB_PAT' を設定している場合は自動的にそちらが優先されます
  GITHUB_PAT: PropertiesService.getScriptProperties().getProperty("GITHUB_PAT") || "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN",
  
  // Substackからのメールを特定するための検索クエリ
  GMAIL_SEARCH_QUERY: "from:substack.com is:unread",
  
  // 処理済みメールに付けるラベル名（重複処理防止用）
  PROCESSED_LABEL: "Processed_RontenBot"
};

/**
 * メイン関数: 定期実行トリガーから呼び出される
 */
function checkSubstackEmails() {
  const pat = CONFIG.GITHUB_PAT.trim();
  if (!pat || pat === "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN") {
    Logger.log("エラー: GITHUB_PAT が設定されていません。スクリプトプロパティに 'GITHUB_PAT' を保存してください。");
    return;
  }
  
  // デバッグ用: PATが読み込めているか先頭数文字を確認
  const maskedPat = pat.substring(0, 4) + "..." + pat.substring(pat.length - 4);
  Logger.log(`使用中の GITHUB_PAT: ${maskedPat}`);

  const threads = GmailApp.search(CONFIG.GMAIL_SEARCH_QUERY, 0, 5);
  if (threads.length === 0) {
    Logger.log("新着の Substack メールはありませんでした。");
    return;
  }

  const processedLabel = getOrCreateLabel(CONFIG.PROCESSED_LABEL);

  for (const thread of threads) {
    const messages = thread.getMessages();
    const latestMessage = messages[messages.length - 1]; // 最新メッセージ

    // ==========================================
    // システムメール・運営通知・いいね等の除外判定
    // ==========================================
    if (isSystemOrNotificationEmail(title)) {
      Logger.log(`通知・システムメールのためスキップ: 「${title}」`);
      thread.addLabel(processedLabel);
      thread.markRead();
      continue;
    }

    const plainBody = latestMessage.getPlainBody();
    const htmlBody = latestMessage.getBody();
    
    // Substackの記事URLを本文から抽出
    const articleUrl = extractSubstackUrl(htmlBody) || extractSubstackUrl(plainBody) || "";

    // 記事URLが見つからない場合も通知メールとみなしてスキップ
    if (!articleUrl) {
      Logger.log(`記事URLが含まれていないためスキップ: 「${title}」`);
      thread.addLabel(processedLabel);
      thread.markRead();
      continue;
    }

    Logger.log(`新着エッセイ検出: 「${title}」 (URL: ${articleUrl})`);


    // GitHub Actions の workflow_dispatch を実行
    const success = triggerGitHubWorkflow({
      title: title,
      content: plainBody,
      originalUrl: articleUrl
    });

    if (success) {
      // 重複処理防止のためラベルを付与＆既読化
      thread.addLabel(processedLabel);
      thread.markRead();
      Logger.log(`成功: ワークフローを起動し、メールに「${CONFIG.PROCESSED_LABEL}」ラベルを付与しました。`);
    } else {
      Logger.log(`失敗: ワークフロー起動に失敗しました。次回再試行します。`);
    }
  }
}

/**
 * GitHub Actions API (workflow_dispatch) を呼び出す
 */
function triggerGitHubWorkflow(data) {
  const url = `https://api.github.com/repos/${CONFIG.GITHUB_OWNER}/${CONFIG.GITHUB_REPO}/actions/workflows/${CONFIG.WORKFLOW_ID}/dispatches`;
  const pat = CONFIG.GITHUB_PAT.trim();

  const payload = {
    ref: "main",
    inputs: {
      article_title: data.title,
      article_content: data.content,
      article_original_url: data.originalUrl
    }
  };

  const options = {
    method: "post",
    contentType: "application/json",
    headers: {
      "Authorization": `Bearer ${pat}`,
      "Accept": "application/vnd.github.v3+json",
      "User-Agent": "GAS-RontenBot"
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };

  try {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();
    if (code === 204 || code === 200) {
      return true; // 204 No Content が標準の成功レスポンス
    } else {
      Logger.log(`GitHub API エラー [${code}]: ${response.getContentText()}`);
      return false;
    }
  } catch (e) {
    Logger.log(`リクエスト例外: ${e.toString()}`);
    return false;
  }
}


/**
 * 本文から Substack の記事 URL (https://*.substack.com/p/...) を抽出するヘルパー
 */
function extractSubstackUrl(bodyText) {
  if (!bodyText) return "";
  const match = bodyText.match(/https:\/\/[a-zA-Z0-9-]+\.substack\.com\/p\/[a-zA-Z0-9-_]+/);
  return match ? match[0] : "";
}

/**
 * ラベルを取得または新規作成
 */
function getOrCreateLabel(name) {
  let label = GmailApp.getUserLabelByName(name);
  if (!label) {
    label = GmailApp.createLabel(name);
  }
  return label;
}

/**
 * お知らせ・システム通知・いいね等のメールを除外判定する
 */
function isSystemOrNotificationEmail(subject) {
  if (!subject) return true;

  const ignoreKeywords = [
    "shareable assets",
    "accepted your invitation",
    "invitation",
    "liked your",
    "liked",
    "commented",
    "comment",
    "subscriber",
    "subscribed",
    "stats for",
    "weekly stats",
    "dashboard",
    "pledge",
    "payment",
    "receipt",
    "welcome to",
    "subscription",
    "restacked",
    "repost",
    "いいね",
    "コメント",
    "登録",
    "招待",
    "アセット"
  ];

  const lowerSubject = subject.toLowerCase();
  return ignoreKeywords.some(keyword => lowerSubject.includes(keyword));
}

