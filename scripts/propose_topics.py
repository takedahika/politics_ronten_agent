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

        pr_title = f"論点追加提案: 『{topic_title}』"
        pr_body = f"""
## 📌 新規論点の追跡提案: {topic_title}

ニュースレターエッセイ **「{essay_title}」** より、新しい論点として継続追跡することを提案します。

- **トピック名**: {topic_title}
- **設定フォルダ**: `topics/{slug}/`

この変更をマージすると、国会議事録APIおよびニュースフィードからの自動情報蓄積が開始されます。

---
### レビュー方法
1. 追跡を開始する場合は **Merge pull request** をクリック
2. 保留・見送る場合は **Close pull request** をクリック
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
    try:
        config = load_config()

        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY 環境変数が設定されていません")
        genai.configure(api_key=gemini_key)

        essay_title: str = ""
        essay_url: str = ""
        essay_content: str = ""

        # ==============================
        # 入力ソースの判定（優先順位順）
        # ==============================

        article_url = os.environ.get("ARTICLE_URL", "").strip()
        article_content = os.environ.get("ARTICLE_CONTENT", "").strip()  # GASから直接本文を渡す用

        if article_url:
            # 【手動実行 or GAS経由】記事URLが渡された場合 → 直接フェッチ
            print(f"記事URLから本文を取得中: {article_url}")
            import re
            resp = httpx.get(article_url, timeout=20, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"})
            resp.raise_for_status()
            # HTMLから本文っぽいテキストを抜き出す
            html = resp.text
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL)
            text = re.sub(r"<[^>]+>", " ", text)
            text = re.sub(r"\s+", " ", text).strip()
            essay_url = article_url
            essay_content = text[:6000]
            # タイトルをHTMLのtitleタグから取得
            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            essay_title = title_match.group(1).strip() if title_match else article_url
            print(f"取得成功: 「{essay_title}」")

        elif article_content:
            # 【GAS経由・本文直接渡し】メール本文がそのまま渡された場合
            print("GASから渡されたメール本文を使用します。")
            article_title_line = os.environ.get("ARTICLE_TITLE", "").strip()
            essay_title = article_title_line or "（タイトル不明）"
            essay_url = os.environ.get("ARTICLE_ORIGINAL_URL", "").strip() or f"substack-email-{hashlib.md5(article_content[:100].encode()).hexdigest()}"
            essay_content = article_content[:6000]

        else:
            print("処理する記事が指定されていません。")
            print("  - 手動実行: GitHub Actions の 'Run workflow' でARTICLE_URLを入力してください")
            print("  - 自動実行: GASからARTICLE_CONTENTを渡してください")
            return

        essay_hash = hashlib.md5(essay_url.encode("utf-8")).hexdigest()
        processed_essays = load_processed_essays()

        if essay_hash in processed_essays:
            print(f"エッセイ 「{essay_title}」 はすでに処理済みです。")
            return

        print(f"最新のエッセイを分析中: 「{essay_title}」")
        existing_slugs = get_existing_slugs()
        model_name = config.get("analysis", {}).get("model", "gemini-3.5-flash")

        # Topic抽出
        proposed_topics = extract_topics_from_essay(essay_title, essay_content, existing_slugs, model_name)
        if not proposed_topics:
            print("エッセイから新しいTopicは抽出されませんでした。")
            save_processed_essay(essay_hash)
            return

        print(f"AIが {len(proposed_topics)} 件のトピック案を抽出しました。")

        # 提案処理
        for topic_data in proposed_topics:
            topic_dir = create_topic_files(topic_data)
            if topic_dir:
                save_processed_essay(essay_hash)
                propose_via_github(topic_dir, topic_data.get("title", ""), essay_title)
                break

    except Exception as e:
        error_msg = f"propose_topics.py 実行エラー: {str(e)}"
        print(f"\n[CRITICAL ERROR] {error_msg}")
        with open("/tmp/error_info.json", "w", encoding="utf-8") as f:
            json.dump({"error": error_msg, "step": "propose_topics.py"}, f, ensure_ascii=False)
        sys.exit(1)


if __name__ == "__main__":
    main()

    main()
