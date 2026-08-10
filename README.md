# 論点の現在地（Ronten no Genzaichi）

政治の論点を継続的にAIが収集・整理し、公開するプロジェクト。
ニュースレター「[1年に3日だけ政治を考える](https://poli3year.substack.com)」と連携し、エッセイで取り上げた論点を詳細に追跡します。

**サイト**: [takedahika.github.io/politics_ronten_agent](https://takedahika.github.io/politics_ronten_agent)

---

## このプロジェクトについて

ニュースレターのエッセイが「問いを投げる」。  
このサイトが「その問いの現在地を整理し続ける」。

読者はトピックページからニュースレターへ誘導される。
エッセイを読み、サイトで論点を深掘りし、また次のエッセイを読む——そういうループを作ります。

---

## 仕組み

```
【情報収集】GitHub Actions (daily.yml) — 毎日 6:00 UTC
    ↓
  NHK政治RSS + 国会議事録API（過去14日間）
  → 各トピックに関連するニュースをAI（Gemini）が要約・整理
  → Markdownファイルとして自動PR作成
  → 承認するとGitHub Pagesに反映

【論点提案】GitHub Actions (propose_topics.yml) — 手動実行
    ↓
  記事URLを貼り付けて実行
  → Geminiが記事から「新しい論点候補」を抽出
  → 新規トピックのYAMLをPRとして提案
  → 承認すると新しい論点ページが追加される
```

---

## ディレクトリ構成

```
.
├── topics/                    # 各論点データ（1フォルダ＝1論点）
│   └── {slug}/
│       ├── topic.yaml         # 論点の設定（キーワード、ニュースレター記事URLなど）
│       ├── overview.md        # 現在の状況
│       ├── timeline.md        # タイムライン
│       ├── facts.md           # 確認された事実
│       ├── claims.md          # 立場・主張
│       ├── issues.md          # 主要な論点
│       ├── international.md   # 国際比較
│       └── sources.md         # 情報源
│
├── config/
│   └── shared_sources.yaml    # 全論点共通のRSSソース（NHK政治など）
│
├── scripts/
│   ├── collect.py             # ニュース収集・整理スクリプト
│   ├── propose_topics.py      # 新規論点提案スクリプト
│   └── requirements.txt
│
├── site/                      # Next.jsサイト（GitHub Pages）
│   └── src/app/
│       ├── page.tsx           # トップページ
│       └── topics/[slug]/     # 各論点ページ
│
└── .github/workflows/
    ├── daily.yml              # ニュース収集（毎日自動）
    ├── propose_topics.yml     # 論点提案（手動実行）
    └── deploy.yml             # GitHub Pagesデプロイ
```

---

## 論点ページの `topic.yaml` 設定例

```yaml
id: flag-desecration
title: 国旗損壊罪
slug: flag-desecration
description: 日本の国旗（日章旗）を損壊した場合の刑事罰の導入をめぐる法的・政治的議論
status: active
priority: high

keywords:
  - 国旗損壊罪
  - 日の丸

use_shared_sources: true
rss_feeds: []
related_countries: [JP]
created_at: "2026-08-10"

# このトピックを取り上げたニュースレター記事
newsletter_articles:
  - url: "https://poli3year.substack.com/p/f92"
    title: "国旗損壊罪、あるいは従順であることについて考える"
```

---

## 手動で論点提案を実行する

1. [Actions タブ](https://github.com/takedahika/politics_ronten_agent/actions) を開く
2. **「新規論点の自動提案（Substack解析）」** をクリック
3. **「Run workflow」** → 記事URLを入力して実行
4. PRが作成されたらレビューして承認（マージ）

---

## 必要なSecrets（GitHub Settings → Secrets）

| 名前 | 説明 |
|------|------|
| `GEMINI_API_KEY` | Google AI Studio で発行 |
| `DISCORD_WEBHOOK_URL` | Discordの通知先Webhook URL |

---

## 技術スタック

- **フロントエンド**: Next.js 15 (Static Export) → GitHub Pages
- **AI**: Google Gemini API（gemini-2.5-flash）
- **自動化**: GitHub Actions
- **情報源**: NHK政治RSS、国会議事録API
