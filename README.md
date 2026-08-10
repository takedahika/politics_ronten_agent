# 論点の現在地 — 技術ドキュメント

> 人間が重要だと考えた社会的・政治的な問いを継続的に調査し、  
> AIと人間の協働によってその現在地を更新・記録するメディア。

---

## 目次

1. [システム全体の流れ](#1-システム全体の流れ)
2. [毎日の自動処理（GitHub Actions）](#2-毎日の自動処理github-actions)
3. [Step 1: 情報収集 — collect.py](#3-step-1-情報収集--collectpy)
4. [Step 2: AI分析 — analyze.py](#4-step-2-ai分析--analyzepy)
5. [Step 3: PR作成 — create_pr.py](#5-step-3-pr作成--create_prpy)
6. [承認フロー（GitHub上での運用）](#6-承認フローgithub上での運用)
7. [マージ後の自動デプロイ](#7-マージ後の自動デプロイ)
8. [Topicの仕組み](#8-topicの仕組み)
9. [Webサイトの仕組み（Next.js）](#9-webサイトの仕組みnextjs)
10. [コスト設計](#10-コスト設計)
11. [初回セットアップ手順](#11-初回セットアップ手順)
12. [新しいTopicの追加方法](#12-新しいtopicの追加方法)
13. [セキュリティ設計](#13-セキュリティ設計)
    - [13-1. APIキーと秘密情報の管理](#13-1-apiキーと秘密情報の管理)
    - [13-2. GitHub Actions の権限設計](#13-2-github-actions-の権限設計最小権限の原則)
    - [13-3. ブランチ保護の推奨設定](#13-3-ブランチ保護branch-protectionの推奨設定)
    - [13-4. 公開情報とプライベート情報の分離](#13-4-公開情報とプライベート情報の分離)
    - [13-5. 外部サービスへのデータ送信](#13-5-外部サービスへのデータ送信)
    - [13-6. インシデント対応](#13-6-インシデント対応チェックリスト)
    - [13-7. セキュリティチェックリスト](#13-7-セキュリティチェックリストセットアップ時)

---

## 1. システム全体の流れ

```
毎日 JST 8:00
      │
      ▼
┌─────────────────────────────┐
│   GitHub Actions (daily.yml) │
│                              │
│  [1] collect.py              │  ← RSSフィード・Web検索から記事を収集
│       ↓                      │
│  [2] analyze.py              │  ← Gemini AI で記事を分析・Markdownを更新
│       ↓                      │
│  [3] create_pr.py            │  ← 変更をGitHub Pull Requestとして送信
└─────────────────────────────┘
      │
      ▼
   Pull Request が届く
      │
  あなたが確認
      │
  ┌───┴───┐
 マージ  クローズ
  │        │
 Approve  Reject
  │
  ▼
┌──────────────────────────────┐
│  GitHub Actions (deploy.yml)  │  ← 自動起動
│                               │
│  Next.js ビルド → 静的HTML生成 │
│       ↓                       │
│  GitHub Pages にデプロイ       │
└──────────────────────────────┘
      │
      ▼
  Webサイトが更新される
```

**ポイント：あなたが操作するのは GitHub の Pull Request を見るだけ。**

---

## 2. 毎日の自動処理（GitHub Actions）

GitHub Actions は GitHub のサーバー上で動くプログラム自動実行の仕組みです。  
コードを書いておくと、指定した条件（時刻・プッシュなど）で自動的に動きます。

### daily.yml の内容

```yaml
on:
  schedule:
    - cron: "0 23 * * *"   # UTC 23:00 = JST 翌8:00
  workflow_dispatch:        # 手動実行も可能
```

毎日この時刻になると、GitHub のサーバーが：

1. このリポジトリのコードを取得（checkout）
2. Python をセットアップ
3. 3つのスクリプトを順番に実行
4. Pull Request を作成

という処理を自動で行います。**あなたのパソコンは一切起動している必要がありません。**

---

## 3. Step 1: 情報収集 — collect.py

### やっていること

各 `topics/*/topic.yaml` を読み込み、設定された情報源から記事を収集します。

### 情報収集の2つのルート

#### ルート① RSS フィード

```
NHK政治RSS → 最新記事リスト → タイトル・URL・本文を取得
朝日新聞RSS ↗
時事通信RSS ↗
```

RSS（Really Simple Syndication）とは、ニュースサイトが提供する「新着記事の一覧データ」です。  
フォーマットが決まっているため、自動で読み取ることができます。

- 過去7日以内の記事のみ取得
- 古い記事はスキップ

#### ルート② Brave Search API（任意）

```
検索クエリ「国旗損壊罪 法案」
    ↓
Brave Search API
    ↓
検索結果10件（タイトル・URL・概要）
```

Google検索のようなウェブ検索をAPIから呼び出します。  
Brave Search API は月2,000クエリまで無料です。

#### 重複チェック

収集した記事は URL を MD5 ハッシュに変換して管理します。

```
URL → MD5ハッシュ → set() に記録 → 重複をスキップ
```

### 出力

```json
{
  "flag-desecration": [
    {
      "title": "国旗損壊罪、衆院で審議入り",
      "url": "https://example.com/...",
      "content": "記事の本文（最大2000文字）",
      "published_at": "2026-08-10T06:00:00+00:00",
      "source_name": "NHKニュース",
      "hash": "a3f2c8..."
    },
    ...
  ]
}
```

`/tmp/collected_documents.json` に保存して次のステップへ渡します。

---

## 4. Step 2: AI分析 — analyze.py

### やっていること

収集した記事を Gemini AI で2段階に分析し、Topic の Markdown ファイルを更新します。

### 段階① Relevance Filter（関連性判定）— Gemini 2.0 Flash 使用

**目的：** コストを抑えるため、安価・高速なモデルで無関係な記事を先に除外する。

```
収集記事 100件
    ↓
キーワードマッチ（高速・無料）
    ↓
残った記事に Gemini Flash で精密判定
    ↓
関連あり: confidence 0.6以上 → 次のステップへ
関連なし: スキップ
    ↓
関連記事 10件（例）
```

Gemini へのプロンプト（概略）：
```
Topic「国旗損壊罪」のキーワード: 国旗損壊罪, 日の丸, 国旗保護...
この記事は関連していますか？
→ {"relevant": true, "confidence": 0.85, "reason": "..."}
```

### 段階② Extraction（情報抽出）— Gemini 2.5 Flash 使用

**目的：** 関連記事から Event・Fact・Claim を構造化データとして抽出する。

```
現在のTopic状態（既存Markdown）
           +
新しく収集した関連記事
           ↓
Gemini 2.5 Flash（高性能）
           ↓
{
  "new_events": [...],     ← 新しい出来事
  "new_facts": [...],      ← 確認できる事実
  "new_claims": [...],     ← 誰かの主張
  "new_sources": [...],    ← 情報源
  "open_questions": [...], ← 未解決の問い
  "summary_of_changes": "国旗損壊罪について○○議員が発言"
}
```

AIへの重要な制約（プロンプトに記述済み）：
- 出典のないFactを生成しない
- ClaimとFactを混同しない
- 政治的な結論を出さない

### Markdown ファイルの更新

抽出した情報を各ファイルに追記します：

| 抽出データ | 書き込み先ファイル |
|-----------|----------------|
| current_status_update | `overview.md` の「現在の状況」セクションを置き換え |
| new_events | `timeline.md` の先頭に追加（新しいものが上） |
| new_facts | `facts.md` に箇条書きで追加 |
| new_claims | `claims.md` に引用ブロックとして追加 |
| new_sources | `sources.md` にリンクとして追加 |
| open_questions | `overview.md` の末尾に追加 |

---

## 5. Step 3: PR作成 — create_pr.py

### やっていること

更新された Markdown ファイルを新しいブランチにコミットし、Pull Request を作成します。

### 処理の流れ

```python
# 1. タイムスタンプ付きブランチ名を生成
branch_name = "update/ai-20260810-0800"

# 2. ブランチ作成・チェックアウト
git checkout -b update/ai-20260810-0800

# 3. 変更ファイルをステージング
git add topics/flag-desecration/timeline.md
git add topics/flag-desecration/facts.md

# 4. コミット
git commit -m "update: AI更新 flag-desecration (20260810-0800)"

# 5. GitHub にプッシュ
git push origin update/ai-20260810-0800

# 6. Pull Request を作成（GitHub API経由）
repo.create_pull(
    title="[AI更新] 国旗損壊罪について○○議員が発言",
    body="...",  # 変更内容の詳細説明
    head="update/ai-20260810-0800",
    base="main"
)
```

### PR の説明文（自動生成）

```markdown
## 🤖 AI による自動更新提案

実行日時: 2026年8月10日 23:00 UTC

---

### 更新内容

#### 📌 flag-desecration
要約: 国旗損壊罪について○○議員が〜と発言

- 新しいイベント: 1件
- 新しいFact: 2件
- 新しいClaim: 1件

---

### レビュー方法

1. Files changed タブで変更内容を確認
2. 問題なければ Merge pull request でApprove
3. 不要な場合は Close pull request でReject
```

---

## 6. 承認フロー（GitHub上での運用）

### 毎朝の操作（数分で完了）

```
GitHub の Pull Requests タブを開く
          ↓
PR が届いていれば開く
          ↓
「Files changed」タブで差分を確認
          ↓
  ┌───────────────────────────┐
  │ timeline.md               │
  │ + ### 2026年8月10日       │  ← 緑 = 追加
  │ + **○○議員が発言**        │
  │ + ...                     │
  │                           │
  │ facts.md                  │
  │ + - △△法案は○○を規定... │
  └───────────────────────────┘
          ↓
      判断する

問題ない → Merge pull request ✅
          → Webサイトが自動更新される

問題あり → Close pull request ❌
          → 変更が破棄される（main は変わらない）

一部修正 → PR内でファイルを直接編集してからMerge
```

### GitHubが「知識の変更履歴」になる

```
Commits in main
│
├── 2026-09-03 [AI更新] 最高裁判例が追加
├── 2026-08-20 [AI更新] 参院委員会で審議入り  
├── 2026-08-12 [AI更新] ○○議員が反対声明
└── 2026-08-10 initial: 論点の現在地 MVP
```

**誰がいつ何を追加・削除・訂正したか、すべて残ります。**

---

## 7. マージ後の自動デプロイ

main ブランチに変更がプッシュされると、`deploy.yml` が自動起動します。

```
main へのマージ
      ↓
GitHub Actions (deploy.yml) が起動
      ↓
Node.js セットアップ
      ↓
npm ci（依存関係インストール）
      ↓
npm run build（Next.js 静的ビルド）
  ├── topics/*.md を読み込む
  ├── HTML に変換
  └── site/out/ に静的ファイルを生成
      ↓
GitHub Pages にアップロード
      ↓
数分後にサイトが更新される
```

### 静的サイト生成とは

Next.js の「Static Export」機能を使っています。  
ビルド時に Markdown を読み込んで HTML を事前生成するため、**データベースもサーバーも不要**です。

```
topics/flag-desecration/overview.md
            ↓
       Next.js build
            ↓
 site/out/topics/flag-desecration/index.html
```

GitHub Pages はこの HTML をそのまま配信します。  
**ホスティング費用: 無料（パブリックリポジトリの場合）**

---

## 8. Topicの仕組み

### topic.yaml が設定の中心

```yaml
slug: flag-desecration    # URLと識別子（英語・ハイフン）
title: 国旗損壊罪          # 表示名
status: active            # active / paused / archived
priority: high            # high / normal / low

keywords:                 # キーワードマッチに使用
  - 国旗損壊罪
  - 日の丸

search_queries_ja:        # 日本語の検索クエリ
  - "国旗損壊罪 法案"

rss_feeds:                # 監視するRSSフィード
  - https://www3.nhk.or.jp/rss/news/cat4.xml
```

### Markdownが「データベース」

外部DBは使いません。各 `.md` ファイルが知識を保持します。

```
topics/flag-desecration/
├── overview.md     ← 現在の状況 + Open Questions
├── timeline.md     ← 時系列イベント
├── facts.md        ← 確認された事実
├── claims.md       ← 誰かの主張
├── issues.md       ← 主要な論点
├── international.md ← 海外比較
└── sources.md      ← 情報源リスト
```

**AIは既存の内容を読んだ上で「まだ書かれていないこと」だけを追加します。**  
重複チェックは URL と文章のマッチングで行います。

---

## 9. Webサイトの仕組み（Next.js）

### アーキテクチャ

```
topics/*.md  →  src/lib/topics.ts  →  app/topics/[slug]/page.tsx  →  HTML
```

1. `topics.ts`: Markdown ファイルを読み込み、HTML に変換
2. `page.tsx`: Topic のデータを受け取り、各セクションをレンダリング
3. ビルド時に全 Topic の HTML を事前生成（`generateStaticParams`）

### URL 構造

```
/                              ← Topic一覧（ホームページ）
/topics/flag-desecration/      ← 国旗損壊罪のTopicページ
/newsletter/                   ← ニュースレター（将来）
```

---

## 10. コスト設計

| サービス | 費用 | 用途 |
|--------|------|------|
| GitHub | 無料（パブリックリポジトリ） | コード・Markdown管理・Actions・Pages |
| Gemini API | 無料枠: Flash 15RPM・1M tokens/day | AI分析（Relevance + Extraction） |
| Brave Search API | 無料枠: 2,000クエリ/月 | Web検索（任意） |
| **合計** | **$0/月（通常使用範囲内）** | |

> **Topic が増えたり、処理頻度を上げると Gemini の無料枠を超える場合があります。**  
> その場合は Gemini API の従量課金（Flash: $0.075/1M tokens）が発生します。

---

## 11. 初回セットアップ手順

### Step 1: GitHub リポジトリを作成・プッシュ

```bash
# このディレクトリで実行
cd 33_ronten_no_genzaichi

git init
git add .
git commit -m "initial: 論点の現在地 MVP"

# GitHub で新しいリポジトリを作成してから：
git remote add origin https://github.com/YOUR_USERNAME/ronten-no-genzaichi.git
git branch -M main
git push -u origin main
```

### Step 2: Gemini API キーを取得

1. [Google AI Studio](https://aistudio.google.com/) にアクセス
2. **Get API key** → **Create API key**
3. キーをコピー（`AIza...` で始まる文字列）

### Step 3: GitHub Secrets を設定

GitHub リポジトリ → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Name | Value |
|------|-------|
| `GEMINI_API_KEY` | 取得した Gemini API キー |
| `DISCORD_WEBHOOK_URL` | Discord の Webhook URL（任意・設定するとPR通知がDiscordに届きます） |
| `BRAVE_SEARCH_API_KEY` | Brave Search API キー（任意・なくても動く） |

> **Discord Webhook URLの取得方法**  
> 送信先のDiscordチャンネルの設定 → 「連携サービス」 → 「Webhook」 → 「新しいWebhook」を作成し、「Webhook URLをコピー」をクリックして取得します。

> `GITHUB_TOKEN` は GitHub が自動で提供するため設定不要。

### Step 4: GitHub Pages を有効化

**Settings** → **Pages** → Source: **GitHub Actions** を選択

### Step 5: Actions の権限を設定

**Settings** → **Actions** → **General**
- Workflow permissions: **Read and write permissions** ✅
- **Allow GitHub Actions to create and approve pull requests** ✅

### Step 6: 動作確認（手動実行）

**Actions** タブ → **毎日の情報収集・AI分析・PR作成** → **Run workflow** → **Run workflow**

数分後に Pull Requests タブを確認する。

---

## 12. 新しいTopicの追加方法

GitHub 上で以下のファイルを作成するだけです（コマンドライン不要）。

### 必要なファイル

```
topics/
└── your-new-topic/         ← フォルダ名は英語・ハイフン区切り
    ├── topic.yaml          ← 設定ファイル（必須）
    ├── overview.md         ← 概要・現状（空でもOK）
    ├── timeline.md         ← タイムライン（空でもOK）
    ├── facts.md            ← 事実（空でもOK）
    ├── claims.md           ← 主張（空でもOK）
    ├── issues.md           ← 論点（空でもOK）
    ├── international.md    ← 国際比較（空でもOK）
    └── sources.md          ← 情報源（空でもOK）
```

### topic.yaml のテンプレート

```yaml
id: your-topic-id
title: Topicのタイトル（日本語OK）
slug: your-topic-id        # URLに使う（英語・ハイフン）
description: このTopicについての一文説明
status: active             # active で監視開始
priority: normal           # high / normal / low

keywords:
  - キーワード1
  - キーワード2

search_queries_ja:
  - "検索クエリ1"
  - "検索クエリ2"

search_queries_en:
  - "English search query"

rss_feeds:
  - https://www3.nhk.or.jp/rss/news/cat4.xml

related_countries:
  - JP

created_at: "2026-08-10"
```

main ブランチにコミットすれば、翌朝から自動収集が始まります。

---

## AIへの制約（重要）

このシステムのAIは以下を**しません**：

| 禁止事項 | 理由 |
|---------|------|
| 出典のないFactを生成 | 誤情報の混入を防ぐ |
| ClaimとFactを混同 | 「誰かの主張」と「確認できる事実」は別物 |
| 政治的な結論を出す | AIは整理するだけ。評価は人間が行う |
| 承認なしで公開 | すべての更新はPRを経由する |

**AIは提案する。人間が判断する。これが原則。**

---

## 13. セキュリティ設計

### 13-1. APIキーと秘密情報の管理

このシステムで扱う秘密情報は以下の3つです。

| 秘密情報 | 保管場所 | 絶対にやってはいけないこと |
|---------|---------|----------------------|
| `GEMINI_API_KEY` | GitHub Secrets | コードにベタ書き・チャットに貼る |
| `BRAVE_SEARCH_API_KEY` | GitHub Secrets | `.env` ファイルをコミット |
| `DISCORD_WEBHOOK_URL` | GitHub Secrets | URLをSNSや記事に掲載 |

#### GitHub Secrets の仕組み

```
あなたが設定 → GitHub の暗号化ストレージに保存
                        ↓
              GitHub Actions 実行時にのみ環境変数として注入
                        ↓
              スクリプトが os.environ.get("GEMINI_API_KEY") で読み込む
                        ↓
              ログには値が出力されない（マスキング自動適用）
```

**Secrets の値は設定後、GitHub UI上でも二度と表示されません。**  
漏洩した場合はすぐにAPIキーを無効化・再発行してください。

#### `.gitignore` で保護されているもの

```
.env          ← ローカル開発用の環境変数ファイル
.env.local    ← 同上
node_modules/ ← 依存パッケージ（サイズが大きいため除外）
```

> ⚠️ `.env` ファイルをうっかり `git add` してコミットした場合、  
> GitHubにプッシュした瞬間に公開されます。  
> 発生したら：①そのAPIキーをすぐ無効化 ②`git filter-branch` または BFG Repo Cleaner で履歴を消去

---

### 13-2. GitHub Actions の権限設計（最小権限の原則）

`daily.yml` に設定している権限は意図的に最小限に絞っています。

```yaml
permissions:
  contents: write        # ← ブランチ作成・ファイルコミットに必要
  pull-requests: write   # ← PR作成に必要
```

**これ以外の権限（issues, packages, deployments 等）は付与していません。**

`deploy.yml` の権限：

```yaml
permissions:
  contents: read         # ← コードを読むだけ
  pages: write           # ← GitHub Pagesへのデプロイに必要
  id-token: write        # ← OIDCトークン（GitHub公式のデプロイ方式）
```

#### `GITHUB_TOKEN` について

`GITHUB_TOKEN` は GitHub が自動的に発行する一時的なトークンです。

- 各 Actions 実行ごとに新しいトークンが生成される
- 実行終了後に自動で無効化される
- **あなたが管理するPersonal Access Tokenではない**ため、漏洩リスクが低い
- リポジトリのスコープ内にのみ権限が限定される

---

### 13-3. ブランチ保護（Branch Protection）の推奨設定

GitHub リポジトリ → **Settings** → **Branches** → **Add branch protection rule**

`main` ブランチに以下を設定することを推奨します：

| 設定項目 | 推奨値 | 理由 |
|---------|-------|------|
| Require a pull request before merging | ✅ ON | 直接プッシュを禁止。必ずPRを経由させる |
| Require approvals | 1（自分のみの場合は0でも可） | レビュー必須化 |
| Dismiss stale pull request approvals | ✅ ON | 承認後の変更を無効化 |
| Do not allow bypassing the above settings | ✅ ON | 管理者も例外なし |

```
AIがブランチに直接プッシュ
        ↓
Pull Request を作成（main には触れない）
        ↓
あなたがレビュー・マージ（main に反映）
        ↓
デプロイ実行
```

**ブランチ保護を設定すると、AIが誤動作しても main ブランチは絶対に直接変更されません。**

---

### 13-4. 公開情報とプライベート情報の分離

#### このシステムで公開されるもの

```
topics/*/overview.md   ← あなたがレビューしてマージしたもの
topics/*/timeline.md   ← 同上
topics/*/facts.md      ← 同上
...（すべてのMarkdownファイル）
```

> ✅ **mainブランチにマージされた情報だけが公開される**
> ✅ **AIが生成した案はPRに留まり、あなたが承認するまで非公開**

#### 公開リポジトリを使う場合の注意

リポジトリをパブリックにする場合、以下は誰でも閲覧できます：

- コードすべて（scripts/, site/ 配下）
- topics/ 配下の Markdown ファイル
- Pull Request の内容（AIが生成した更新案も含む）
- コミット履歴

これは**このプロジェクトの設計上の意図**（透明性・変更履歴の公開）と一致しています。

プライベートリポジトリにする場合：

- GitHub Pages は有料プラン（GitHub Pro以上）が必要
- ただし GitHub Actions・Secrets は引き続き利用可能

---

### 13-5. 外部サービスへのデータ送信

このシステムが外部に送信するデータ：

| 送信先 | 送信するデータ | 送信しないデータ |
|-------|-------------|---------------|
| Gemini API | 収集した記事の本文（最大2000文字）、Topicのキーワード | 個人情報・APIキー・秘密情報 |
| Brave Search API | 検索クエリ文字列 | 個人情報 |
| GitHub API | コミット内容（Markdownテキスト）、PR説明文 | APIキー |
| Discord Webhook | 処理結果のテキスト（更新あり/なし）、GitHub PR URL | APIキー・記事全文 |

#### Gemini API への送信内容について

```python
# analyze.py の送信内容（例）
prompt = """
Topic「国旗損壊罪」の関連記事を分析してください。

記事タイトル: 国旗損壊罪、衆院で審議入り
記事URL: https://nhk.or.jp/...
記事本文（先頭2000文字）: ...
"""
```

- **個人情報は含みません**（収集するのはニュース記事のみ）
- Google の利用規約・プライバシーポリシーが適用されます
- Gemini API の Free Tier は Google がモデル改善に利用する可能性があります  
  （気になる場合は有料プランを利用してください）

---

### 13-6. インシデント対応チェックリスト

#### APIキーが漏洩した疑いがある場合

```
1. 該当サービスのダッシュボードでAPIキーをすぐ無効化
   - Gemini: https://aistudio.google.com/ → キーを削除
   - Brave: https://api.search.brave.com/ → キーを削除

2. GitHub Secrets から削除
   Settings → Secrets → 該当キーを削除

3. 新しいAPIキーを発行して再設定

4. Actions のログを確認（不審な実行がないか）
   Actions タブ → 各Workflowの実行履歴
```

#### 意図しない情報がmainにマージされた場合

```
1. 該当コミットを特定
   git log --oneline

2. 修正コミットを作成（revertは使わない方が安全）
   # 問題のある行を削除・修正
   git add topics/xxx/facts.md
   git commit -m "correction: 誤情報を削除 - 理由: ..."

3. PRを作成・マージ（同じフローで訂正を記録に残す）

4. GitHubの変更履歴には削除の記録も残る（これが透明性）
```

> ⚠️ `git rebase` や `git push --force` で履歴を書き換えないこと。  
> このシステムは「何がいつ追加・削除されたか」の記録が価値であるため、  
> 誤りも「CORRECTION」として記録に残すことが重要です。

---

### 13-7. セキュリティチェックリスト（セットアップ時）

- [ ] `GEMINI_API_KEY` を GitHub Secrets に設定した
- [ ] `DISCORD_WEBHOOK_URL` を GitHub Secrets に設定した
- [ ] `.gitignore` に `.env` が含まれていることを確認した
- [ ] ローカルに `.env` ファイルを作成した場合、`git status` で追跡されていないことを確認した
- [ ] main ブランチのブランチ保護ルールを設定した
- [ ] Actions の Workflow permissions を "Read and write" に設定した
- [ ] リポジトリの公開/非公開設定を意図通りに設定した
