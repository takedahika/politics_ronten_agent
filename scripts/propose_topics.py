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
import google.generativeai.client as client_mod
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
あなたは政治・社会問題を中立に調査・整理する専門のリサーチアシスタントです。
提示されたニュースレター（エッセイ）を読み込み、継続追跡すべき「論点（Topic）」を抽出してください。

【最重要ルール：エッセイの主張を中心に据えること】
トピックは必ず「このエッセイの筆者が最も伝えたかった問題意識や主張」を核にしてください。
一般的な政策テーマや関連する広い論点に流れることは禁止です。

【悪い例】
- エッセイが「外国人への生活保護にまつわるデマが拡散している」という内容なのに、
  「外国人に対する生活保護の運用適正化」というトピックを設定してしまう。
  → 筆者の問題意識（デマ・誤情報）から外れ、政策論一般になっている。

【良い例】
- 上記と同じエッセイなら →「外国人生活保護デマ・誤情報の拡散と実態」のように、
  エッセイが指摘している「デマという現象」を中心に据えた論点を設定する。

【手順】
ステップ1: エッセイを読み、筆者の「核心的な主張・問題提起」を一文で要約する。
ステップ2: その主張を中心に据えたトピックを最大2件抽出する。
ステップ3: Google検索で最新の状況（関連ニュース・国会での議論など）を確認し、descriptionに反映する。

【既存のトピック一覧（重複を避けること）】
{", ".join(existing_slugs)}

【エッセイ】
タイトル: {title}
内容:
{content[:4000]}

【抽出ルール】
1. トピックの「title」と「essay_claim」は、必ずエッセイが直接言及している具体的な問題に基づくこと。
2. 「〇〇の制度改革」「〇〇の適正化」のような一般的な政策論になっていないか、常に確認すること。
3. 既に存在するトピックと意味的に重複するものは絶対に除外すること。
4. トピックID (id) は英語小文字とハイフンのみ（例: foreign-welfare-misinformation）。
5. ndl_keyword は、国立国会図書館の国会APIで最もヒットしやすい具体的なフレーズを指定すること。
6. 「論点の現在地」などのニュースレター名・著者の活動自体はトピックにしないこと。

【出力フォーマット】
以下の構造のJSON配列のみを返してください。装飾や説明文は一切含めないでください。
[
  {{
    "id": "英数字とハイフン",
    "title": "日本語のトピックタイトル（エッセイの主張を直接反映したもの）",
    "essay_claim": "エッセイの筆者が最も伝えたかった主張・問題提起を1〜2文で要約したもの",
    "description": "検索から得られた政治的コンテキスト（どの政党の肝入りか等）を含む中立な説明文",
    "keywords": ["検索用のキーワード1", "キーワード2"],
    "ndl_keyword": "実際の国会審議で使われる具体的な検索キーワード"
  }}
]
"""

    raw_model_name = model_name if model_name.startswith("models/") else f"models/{model_name}"
    
    # REST転送を使用して設定
    api_key = os.environ.get("GEMINI_API_KEY")
    genai.configure(api_key=api_key, transport="rest")
    raw_client = client_mod.get_default_generative_client()

    request = genai.protos.GenerateContentRequest(
        model=raw_model_name,
        contents=[genai.protos.Content(parts=[genai.protos.Part(text=prompt)])],
        tools=[genai.protos.Tool(google_search=genai.protos.Tool.GoogleSearch())],
        generation_config=genai.protos.GenerationConfig(
            temperature=0.2,
        )
    )

    try:
        response = raw_client.generate_content(request)
        text_content = response.candidates[0].content.parts[0].text
        cleaned_text = text_content.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()
        
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Geminiでのトピック抽出エラー: {e}")
        try:
            print(f"Raw response: {text_content}")
        except:
            pass
        raise RuntimeError("トピック抽出に失敗しました") from e


def generate_initial_topic_content(title: str, description: str, keywords: list[str], model_name: str, essay_claim: str = "") -> dict[str, str]:
    """新規トピック追加時に、学術・公的・ファクトベースの初期Markdown（全記述URL付き）をGeminiで生成する"""
    essay_claim_section = f"""
【このトピックを設定したエッセイの核心的な主張】
{essay_claim}

上記の主張に対して、客観的な事実・ファクトで応答する形でドキュメントを構成してください。
「議論されている主なポイント」は、このエッセイの問題提起に直接答える形の内容を最初に来るようにしてください。
""" if essay_claim else ""
    prompt = f"""
あなたは法学・政治学・社会問題の調査専門アシスタントです。
新規に追跡を開始する論点「{title}」（説明: {description}、キーワード: {', '.join(keywords)}）について、
客観的な事実（Fact）と公的文書・学術論文・公式判例等のURLをベースとした初期ドキュメントを作成してください。
{essay_claim_section}

【Google検索グラウンディングの使用について】
1. あなたにはGoogle検索ツールが提供されています。生成を行う前に、この論点に関する事実関係、背景、学術論文、判例、公的調査を検索してください。
2. 検索の際は、特に日本の大学・研究機関（site:ac.jp）、政府・省庁・自治体（site:go.jp）、または信頼性の高い主要ニュース機関の一次資料を優先的に検索・参照してください。
3. 【禁止事項】Wikipedia（wikipedia.org）や個人のブログ、特定の弁護士会・活動団体の意見書などを「事実」として絶対に参照・引用しないでください。事実の出典は、必ず政府機関・公的機関・裁判所・または主要報道機関（新聞社・NHK等）に限定してください。
4. 【禁止事項】他者の主張を引用する際、それを批判する別の団体（例：弁護士会やNPO）の声明文を根拠（出典）として「〇〇党はこう発言した」と記載するのは禁止です。発言があった事実を記載する場合は、必ずその発言自体の一次資料（国会議事録や大手ニュース）を出典としてください。
5. 記述するすべての事実・出来事の項目について、あなたが検索結果から【実際に参照した本物のURL】を必ず `[出典: 資料名・サイト名](URL)` の形式で付与してください。
6. URLの捏造（ハルシネーション）は絶対に禁止します。必ず実在するURLのみを使用してください。

【絶対ルール】
1. 実際に起きている出来事、制定された法律、判例、公的調査、学術的指摘のみを事実として記述すること。
2. 「AIがまとめました」「私が提案します」などのAI自身についての言及や挨拶は一切含めないこと。
3. 文章は「だ・である調」で知的なトーンを維持すること。ただし、高校三年生（18歳）が読んでスムーズに理解できるよう、官公庁や法律の特有の難解な熟語（例：「乏しい」「属し」など）は使用を禁止し、簡潔で明瞭な平易な言葉に翻訳して記載すること。
4. タイムライン（timeline）の日付は、必ず「実際にその出来事が起こった日（法案成立日、判決日、声明発表日など）」を記載すること。「そのニュース記事がWebに配信された日」ではないことに強く注意してください。
5. タイムラインは、最新の出来事が一番上（降順 / 新しい順）に来るように並べること。

【出力フォーマット】
以下のJSON形式でのみ出力してください。他の装飾テキストは一切含めないでください。

{{
  "overview": "### 📌 実際に議論されている主なポイント\\n\\n- **[ポイント名]**\\n  [具体的な事実説明]\\n  [出典: 資料名](https://...)\\n\\n...",
  "timeline": "### 📜 発端と経過（歴史的事実）\\n\\n- **YYYY-MM-DD**: [直近の出来事・法案成立等の事実]\\n  [出典: 公式議事録/判例等](https://...)\\n\\n- **YYYY-MM-DD**: [過去の出来事・原点]\\n  [出典: 公式議事録/判例等](https://...)\\n",
  "facts": "### 💬 確認された事実と主な立場\\n\\n#### 確認された事実（Fact）\\n- [法的規定・数値データ等]\\n  [出典: 官報/e-Gov](https://...)\\n\\n#### 主な立場（Claims）\\n- **[立場名]**: [発言・公約・意見書の要旨]\\n  [出典: 公式議事録/意見書](https://...)\\n",
  "parties": "### 🏛️ 各党のスタンスと政治的背景\\n\\n- **[政党名・派閥]**: [推進/慎重/反対などのスタンスとその理由。どの政党の肝入り政策か等]\\n  [出典: 公式議事録/ニュース](https://...)\\n",
  "international": "### 🌐 各国との比較\\n\\n- **[国名]**: [制度や対応 of 事実]\\n  [出典: 公式資料](https://...)\\n",
  "sources": "### 🔗 参照した情報源・一次資料\\n\\n- [国会議事録検索システム](https://kokkai.ndl.go.jp/)\\n- [e-Gov 法令検索](https://elaws.e-gov.go.jp/)\\n- [その他の参照元](実際のURL)\\n"
}}

"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません")

    # Google Search Groundingツールを有効化 (SDKのバグ回避のためraw_clientを使用)

    # REST転送を使用して設定（gRPCがブロックされるのを回避するため）
    genai.configure(api_key=api_key, transport="rest")
    raw_client = client_mod.get_default_generative_client()

    raw_model_name = model_name if model_name.startswith("models/") else f"models/{model_name}"

    request = genai.protos.GenerateContentRequest(
        model=raw_model_name,
        contents=[
            genai.protos.Content(
                parts=[genai.protos.Part(text=prompt)]
            )
        ],
        tools=[
            genai.protos.Tool(
                google_search=genai.protos.Tool.GoogleSearch()
            )
        ],
        generation_config=genai.protos.GenerationConfig(
            temperature=0.2,
        )
    )

    try:
        response = raw_client.generate_content(request)
        text_content = response.candidates[0].content.parts[0].text
        cleaned_text = text_content.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()
        return json.loads(cleaned_text)
    except Exception as e:
        raise RuntimeError(
            f"Google Search Groundingを使用した初期コンテンツ生成に失敗しました。\n"
            f"原因: {e}\n"
            f"※APIキーの権限設定、またはモデル名（{model_name}）がGoogle Search Groundingに対応しているか確認してください。"
        ) from e


def create_topic_files(topic_data: dict, essay_title: str = "", essay_url: str = "", model_name: str = "gemini-3.5-flash") -> Path | None:
    slug = topic_data.get("id")
    if not slug:
        return None

    topic_dir = Path("topics") / slug
    if topic_dir.exists():
        print(f"Topic {slug} はすでにフォルダが存在します。PR作成のみ再試行します。")
        return topic_dir

    topic_dir.mkdir(parents=True, exist_ok=True)
    title = topic_data.get("title", slug)
    description = topic_data.get("description", "")
    keywords = topic_data.get("keywords", [title])

    # 1. topic.yaml の作成
    config = {
        "id": slug,
        "title": title,
        "slug": slug,
        "description": description,
        "status": "active",
        "priority": "normal",
        "keywords": keywords,
        "use_shared_sources": True,
        "rss_feeds_primary": [
            {
                "type": "ndl_api",
                "keyword": topic_data.get("ndl_keyword", title)
            }
        ],
        "rss_feeds": [],
        "related_countries": ["JP"],
        "created_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
        "newsletter_articles": [
            {
                "title": essay_title,
                "url": essay_url
            }
        ] if essay_title and essay_url else []
    }

    with open(topic_dir / "topic.yaml", "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 2. 初期コンテンツの生成（全記述URL付き）
    essay_claim = topic_data.get("essay_claim", "")
    print(f"AIによる初期コンテンツ（歴史・背景・ファクト調査）を生成中: {title}")
    initial_content = generate_initial_topic_content(title, description, keywords, model_name, essay_claim)
    if not initial_content:
        raise ValueError("AIによる初期コンテンツの生成結果が空です。APIの実行エラーが発生しました。")

    files = ["overview.md", "timeline.md", "facts.md", "claims.md", "parties.md", "issues.md", "international.md", "sources.md"]
    for file in files:
        key = file.replace(".md", "")
        text = initial_content.get(key, "")
        if text:
            (topic_dir / file).write_text(text, encoding="utf-8")

    print(f"新トピックファイルを生成しました: {topic_dir}")
    return topic_dir



# ==============================
# GitHub PRの作成
# ==============================

def propose_via_github(topic_dir: Path, topic_title: str, essay_title: str, topic_data: dict, essay_url: str) -> bool:
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

### 📝 トピックの概要（AI抽出）
- **トピック名**: {topic_title}
- **設定フォルダ**: `topics/{slug}/`
- **概要・背景**: {topic_data.get('description', '（説明なし）')}
- **検索キーワード**: {', '.join(topic_data.get('keywords', []))}

### 🔗 元情報（エッセイ）
- [元エッセイのURLを開く]({essay_url})

---
この変更をマージすると、国会議事録APIおよびニュースフィードからの自動情報蓄積が開始されます。

### レビュー方法
1. **修正したい場合**: このPRのコメント欄で `@ronten-ai ここをもっと分かりやすくして` のように指示を出すと、自動で修正されます。
2. **追跡を開始する場合**: **Merge pull request** をクリック
3. **保留・見送る場合**: **Close pull request** をクリック
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
        try:
            proposed_topics = extract_topics_from_essay(essay_title, essay_content, existing_slugs, model_name)
        except Exception as e:
            print(f"トピック抽出処理中に致命的なエラーが発生しました: {e}")
            return

        if not proposed_topics:
            print("エッセイから新しいTopicは抽出されませんでした。")
            save_processed_essay(essay_hash)
            return

        print(f"AIが {len(proposed_topics)} 件のトピック案を抽出しました。")

        # 提案処理
        for topic_data in proposed_topics:
            topic_dir = create_topic_files(topic_data, essay_title, essay_url, model_name)
            if topic_dir:
                save_processed_essay(essay_hash)
                propose_via_github(topic_dir, topic_data.get("title", ""), essay_title, topic_data, essay_url)
                break

    except Exception as e:
        error_msg = f"propose_topics.py 実行エラー: {str(e)}"
        print(f"\n[CRITICAL ERROR] {error_msg}")
        with open("/tmp/error_info.json", "w", encoding="utf-8") as f:
            json.dump({"error": error_msg, "step": "propose_topics.py"}, f, ensure_ascii=False)
        sys.exit(1)


if __name__ == "__main__":
    main()
