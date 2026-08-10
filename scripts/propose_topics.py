from __future__ import annotations

"""
propose_topics.py
-----------------
SubstackのRSSフィードから最新エッセイを読み込み、
AI（Gemini）によって継続追跡すべき新しい論点（Topic）を抽出する。
未登録のTopicが見つかった場合、新しいトピックフォルダと設定ファイルを自動生成し、
GitHubのPull Requestとして提案する。
"""

import json
import os
import sys
import hashlib
import time
import httpx
import yaml
import feedparser
import google.generativeai as genai
from pathlib import Path
from datetime import datetime, timezone
from github import Github

# ==============================
# 設定の読み込み
# ==============================

def load_config() -> dict:
    config_path = Path("config/newsletter.yaml")
    if not config_path.exists():
        print("config/newsletter.yaml が存在しません。デフォルト設定を使用します。")
        return {"newsletter_rss_url": "", "analysis": {"model": "gemini-3.5-flash", "max_topics_per_essay": 2}}
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_existing_slugs() -> list[str]:
    topics_dir = Path("topics")
    if not topics_dir.exists():
        return []
    return [d.name for d in topics_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]


# ==============================
# 処理済みエッセイの管理
# ==============================

def load_processed_essays() -> set[str]:
    path = Path("topics/.processed_essays.json")
    if not path.exists():
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_processed_essay(essay_hash: str):
    path = Path("topics/.processed_essays.json")
    processed = load_processed_essays()
    processed.add(essay_hash)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(processed), f, ensure_ascii=False, indent=2)


# ==============================
# エッセイからTopicを抽出（Gemini）
# ==============================

def extract_topics_from_essay(
    title: str,
    content: str,
    existing_slugs: list[str],
    model_name: str,
) -> list[dict]:
    
    prompt = f"""
あなたは社会的・政治的な議論を中立に整理する調査専門のAIアシスタントです。
提示された「ニュースレター（エッセイ）」を深く読み込み、継続的にニュースや国会議事録を追跡・調査する価値のある、具体的な「社会的・政治的論点（Topic）」を抽出してください。

【既存のトピック一覧（重複を避けること）】
{", ".join(existing_slugs)}

【エッセイ】
タイトル: {title}
内容:
{content[:4000]}

【抽出ルール】
1. エッセイが言及しているテーマの中から、ニュース報道や国会審議を継続的に追跡すべき客観的な論点（Topic）を最大2件抽出してください。
2. 既に存在するトピックと意味的に重複するものは絶対に除外してください。
3. トピックID (id) はURL等に使うため、英語小文字とハイフンのみ（例: seikatsu-hogo, nuclear-power-debate）にしてください。
4. ndl_keyword は、国立国会図書館の国会議事録APIで検索した時に最もヒットしやすい、日本語の代表的な単語（例: 生活保護、原発）を指定してください。

【出力フォーマット】
以下の構造のJSON配列のみを返してください。説明文や```jsonなどのMarkdownの装飾は一切含めないでください。
[
  {{
    "id": "英数字とハイフン（例: child-sns-regulation）",
    "title": "日本語のトピックタイトル（例: 子どもSNS利用規制）",
    "description": "この論点についての短い中立な説明文",
    "keywords": ["検索用のキーワード1", "キーワード2"],
    "ndl_keyword": "国会図書館API検索用の代表的な日本語キーワード"
  }}
]
"""

    model = genai.GenerativeModel(model_name)
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.2,
            ),
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Geminiでのトピック抽出エラー: {e}")
        return []


# ==============================
# 新規トピックファイルの自動作成
# ==============================

def create_topic_files(topic_data: dict) -> Path | None:
    slug = topic_data.get("id")
    if not slug:
        return None

    topic_dir = Path("topics") / slug
    if topic_dir.exists():
        print(f"Topic {slug} はすでにフォルダが存在するためスキップします。")
        return None

    topic_dir.mkdir(parents=True, exist_ok=True)

    # 1. topic.yaml の作成
    config = {
        "id": slug,
        "title": topic_data.get("title", slug),
        "slug": slug,
        "description": topic_data.get("description", ""),
        "status": "active",
        "priority": "normal",
        "keywords": topic_data.get("keywords", [topic_data.get("title")]),
        "use_shared_sources": True,
        "rss_feeds_primary": [
            {
                "type": "ndl_api",
                "keyword": topic_data.get("ndl_keyword", topic_data.get("title"))
            }
        ],
        "rss_feeds": [],
        "related_countries": ["JP"],
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    }

    with open(topic_dir / "topic.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 2. 空のMarkdownファイルの作成
    files = ["overview.md", "timeline.md", "facts.md", "claims.md", "issues.md", "international.md", "sources.md"]
    for file in files:
        (topic_dir / file).write_text("", encoding="utf-8")

    print(f"新トピックファイルを生成しました: {topic_dir}")
    return topic_dir


# ==============================
# GitHub PRの作成
# ==============================

def propose_via_github(topic_dir: Path, topic_title: str, essay_title: str) -> bool:
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo_name:
        print("GITHUB_TOKEN または GITHUB_REPOSITORY が設定されていません。PR作成をスキップします。")
        return False

    slug = topic_dir.name
    branch_name = f"proposal/new-topic-{slug}"

    try:
        # Git操作
        def run_git(args: list[str]):
            import subprocess
            subprocess.run(["git"] + args, check=True, capture_output=True)

        run_git(["config", "user.name", "論点の現在地 Bot"])
        run_git(["config", "user.email", "bot@ronten-no-genzaichi.example"])
        run_git(["checkout", "-b", branch_name])
        
        # 処理済みエッセイログも含めて登録
        run_git(["add", str(topic_dir)])
        run_git(["add", "topics/.processed_essays.json"])
        
        run_git(["commit", "-m", f"propose: 新しい論点『{topic_title}』の追跡を提案"])
        
        remote_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"
        run_git(["remote", "set-url", "origin", remote_url])
        run_git(["push", "origin", branch_name, "--force"])

        # GitHub API で PR作成
        g = Github(token)
        repo = g.get_repo(repo_name)

        pr_title = f"[論点提案] エッセイから『{topic_title}』の追跡を提案"
        pr_body = f"""
## 🤖 AI による新規論点（Topic）の自動提案

ニュースレターエッセイ **「{essay_title}」** から、新しく継続追跡すべき社会的・政治的な問いを検出しました。

### 📌 提案トピック: {topic_title}
- **フォルダ**: `topics/{slug}/`
- **概要**: {topic_dir.name}

この論点の追跡を開始（マージ）すると、翌朝の自動スケジュールから**国会議事録API**および**NHK等のニュースフィード**の自動巡回と情報蓄積が自動的に開始されます。

---
### レビュー方法
1. 提案内容に問題なければ **Merge pull request** をクリック（自動的に追跡開始）
2. 不要な場合は **Close pull request** で拒否（変更は破棄されます）
"""

        pr = repo.create_pull(
            title=pr_title,
            body=pr_body,
            head=branch_name,
            base="main"
        )
        print(f"✅ Pull Request を作成しました: {pr.html_url}")

        # Discord通知用にPRの情報を保存
        with open("/tmp/pr_info.json", "w", encoding="utf-8") as f:
            json.dump({"title": pr_title, "url": pr.html_url}, f, ensure_ascii=False)

        return True
    except Exception as e:
        print(f"PR作成エラー: {e}")
        # mainブランチに戻しておく
        try:
            import subprocess
            subprocess.run(["git", "checkout", "main"], capture_output=True)
        except Exception:
            pass
        return False


# ==============================
# メイン
# ==============================

def main():
    config = load_config()
    rss_url = config.get("newsletter_rss_url")
    if not rss_url:
        print("ニュースレターの RSS URL が設定されていません。")
        return

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        print("GEMINI_API_KEY が設定されていません。")
        return
    genai.configure(api_key=gemini_key)

    # RSSフィードの取得
    print(f"ニュースレターRSSを取得中: {rss_url}")
    try:
        # User-Agent をブラウザ風に偽装して Cloudflare ブロックを回避
        feed = feedparser.parse(
            rss_url,
            agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    except Exception as e:
        print(f"RSS取得失敗: {e}")
        return

    # HTTPステータスのチェック
    status = getattr(feed, "status", None)
    if status and status != 200:
        print(f"RSS取得エラー: HTTPステータス {status} が返されました。")
        if status == 403:
            print("警告: SubstackのCloudflare等によってアクセスが拒否（403）されました。")

    if not feed.entries:
        print("エッセイが見つかりませんでした。")
        if hasattr(feed, "bozo") and feed.bozo:
            print(f"パース例外: {feed.bozo_exception}")
        return

    latest_essay = feed.entries[0]
    essay_title = latest_essay.title
    essay_url = latest_essay.link
    essay_content = latest_essay.description  # 本文またはサマリー
    if not essay_content and "content" in latest_essay:
        essay_content = latest_essay.content[0].value

    essay_hash = hashlib.md5(essay_url.encode("utf-8")).hexdigest()
    processed_essays = load_processed_essays()

    if essay_hash in processed_essays:
        print(f"最新エッセイ 「{essay_title}」 はすでに処理済みです。")
        return

    print(f"最新のエッセイを分析中: 「{essay_title}」")
    existing_slugs = get_existing_slugs()
    model_name = config.get("analysis", {}).get("model", "gemini-3.5-flash")

    # Topic抽出
    proposed_topics = extract_topics_from_essay(essay_title, essay_content, existing_slugs, model_name)
    if not proposed_topics:
        print("エッセイから新しいTopicは抽出されませんでした。")
        # 処理済みとしてマーク（何回も同じエッセイを分析しないようにする）
        save_processed_essay(essay_hash)
        return

    print(f"AIが {len(proposed_topics)} 件のトピック案を抽出しました。")

    # 提案処理
    for topic_data in proposed_topics:
        topic_dir = create_topic_files(topic_data)
        if topic_dir:
            # 処理済みエッセイとして保存（コミットに含める）
            save_processed_essay(essay_hash)
            # PRを作成
            propose_via_github(topic_dir, topic_data.get("title", ""), essay_title)
            # 一度に複数PRを作ると競合するため、1回の実行につき1件のみ処理
            break


if __name__ == "__main__":
    main()
