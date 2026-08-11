from __future__ import annotations

"""
collect.py
----------
RSS フィードとウェブ検索から、各 Topic に関連するドキュメントを収集する。
結果は /tmp/collected_documents.json に保存する。
"""

import feedparser
import httpx
import json
import yaml
import os
import hashlib
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from dateutil import parser as dateutil_parser
import google.generativeai as genai
import google.generativeai.client as client_mod


# ==============================
# Topic の読み込み
# ==============================

def load_topics() -> list[dict]:
    """topics/ 配下の全 topic.yaml を読み込む"""
    topics_dir = Path("topics")
    topics = []
    if not topics_dir.exists():
        print("topics/ ディレクトリが存在しません")
        return topics

    for topic_dir in sorted(topics_dir.iterdir()):
        if not topic_dir.is_dir():
            continue
        config_file = topic_dir / "topic.yaml"
        if not config_file.exists():
            continue
        with open(config_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        config["_dir"] = str(topic_dir)
        topics.append(config)
    return topics


# ==============================
# RSS 収集
# ==============================

def fetch_rss(url: str, max_age_days: int = 14) -> list[dict]:
    """RSS フィードを取得し、最新 max_age_days 日以内の記事を返す"""
    try:
        feed = feedparser.parse(url, agent="RontenNoGenzaichi/1.0")
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
        items = []

        for entry in feed.entries:
            published = None
            for attr in ("published_parsed", "updated_parsed"):
                val = getattr(entry, attr, None)
                if val:
                    try:
                        published = datetime(*val[:6], tzinfo=timezone.utc)
                        break
                    except Exception:
                        pass

            # 古い記事はスキップ（日付不明の場合は含める）
            if published and published < cutoff:
                continue

            url_val = entry.get("link", "")
            content = entry.get("summary", entry.get("description", ""))
            # HTML タグを簡易除去
            import re
            content = re.sub(r"<[^>]+>", "", content)

            items.append({
                "title": entry.get("title", ""),
                "url": url_val,
                "content": content[:2000],
                "published_at": published.isoformat() if published else None,
                "source_name": feed.feed.get("title", url),
                "source_url": url,
                "hash": hashlib.md5(url_val.encode()).hexdigest(),
            })

        return items

    except Exception as e:
        print(f"  [RSS ERROR] {url}: {e}")
        return []


# ==============================
# 国会議事録検索 API（国立国会図書館）
# ==============================

def fetch_kokkai_records(keyword: str, from_date: str) -> list[dict]:
    """
    国会議事録検索システム API でキーワード検索する。
    from_date 以降の記録を全件取得する。
    """
    results = []
    try:
        start_record = 1
        while True:
            resp = httpx.get(
                "https://kokkai.ndl.go.jp/api/speech",
                params={
                    "any": keyword,
                    "recordPacking": "json",
                    "maximumRecords": 10,
                    "startRecord": start_record,
                    "from": from_date,
                },
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
            
            records = data.get("speechRecord", [])
            if not records:
                break
                
            for record in records:
                meeting_url = record.get("meetingURL", "")
                speech_url = record.get("speechURL", meeting_url)
                date_str = record.get("date", "")
                house = record.get("nameOfHouse", "")
                committee = record.get("nameOfMeeting", "")
                speaker = record.get("speaker", "")
                speech = record.get("speech", "")[:2000]

                title = f"【{house}】{committee} — {speaker}発言（{date_str}）"

                results.append({
                    "title": title,
                    "url": speech_url or meeting_url,
                    "content": speech,
                    "published_at": date_str,
                    "source_name": f"国会議事録（{house}・{committee}）",
                    "source_url": speech_url or meeting_url,
                    "source_type": "government",
                    "hash": hashlib.md5((speech_url + date_str + speaker).encode()).hexdigest(),
                })
            
            next_record_pos = data.get("nextRecordPosition")
            if next_record_pos:
                start_record = int(next_record_pos)
            else:
                break

        return results

    except Exception as e:
        print(f"  [KOKKAI API ERROR] keyword={keyword!r}: {e}")
        return []


# ==============================
# Web 検索（Gemini Google Search Grounding）
# ==============================

def search_via_gemini_grounding(topic_title: str, keywords: list[str], model_name: str = "gemini-1.5-flash", from_date: str = "") -> list[dict]:
    """GeminiのGoogle Search Groundingを使って、主要新聞社のサイトから最新情報を検索する"""


    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  [WARNING] GEMINI_API_KEY が設定されていないため、Gemini検索をスキップします")
        return []

    # REST転送を使用して設定（gRPCがブロックされるのを回避するため）
    genai.configure(api_key=api_key, transport="rest")
    raw_client = client_mod.get_default_generative_client()

    # 検索対象ドメインを主要新聞社に限定
    domains = [
        "site:asahi.com",
        "site:yomiuri.co.jp",
        "site:nikkei.com",
        "site:mainichi.jp",
        "site:nhk.or.jp",
        "site:sankei.com",
        "site:47news.jp"
    ]
    domain_query = " OR ".join(domains)

    prompt = f"""あなたは政治・社会問題のニュースを収集する有能なリサーチアシスタントです。

テーマ「{topic_title}」（キーワード: {", ".join(keywords)}）に関する、{from_date}以降に報じられた最新のニュースや報道記事をGoogle検索してください。
検索の際は、必ず以下の主要ニュースサイトのいずれかから情報を取得してください：
朝日新聞 (asahi.com)、読売新聞 (yomiuri.co.jp)、日本経済新聞 (nikkei.com)、毎日新聞 (mainichi.jp)、産経新聞 (sankei.com)、NHK (nhk.or.jp)、共同通信 (47news.jp)

取得したニュースから、客観的な事実（いつ、誰が、何をしたか、どのような発言をしたか）をリストアップし、以下のJSON配列フォーマットで返してください。
実在する記事の正確なURLと日付（YYYY-MM-DD形式）を記述してください。絶対に存在しないダミーURLを捏造しないでください。

JSONフォーマット（※コードブロック等の余計な装飾は付けず、生のJSON配列のみを返してください）:
[
  {{
    "title": "記事のタイトル",
    "url": "実在する記事の正確なURL",
    "content": "記事の具体的な内容要約（200文字以上、客観的ファクトを詳しく記載してください）",
    "published_at": "YYYY-MM-DD",
    "source_name": "新聞社名（例: 朝日新聞、NHK等）"
  }}
]

検索キーワードの例: ({topic_title} OR {keywords[0] if keywords else ""}) ({domain_query})
"""

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
            response_mime_type="application/json",
            temperature=0.2,
        )
    )

    try:
        response = raw_client.generate_content(request)
        text_content = response.candidates[0].content.parts[0].text
        data = json.loads(text_content)
        results = []
        for item in data:
            url_val = item.get("url", "")
            if not url_val:
                continue
            results.append({
                "title": item.get("title", ""),
                "url": url_val,
                "content": item.get("content", "")[:2000],
                "published_at": item.get("published_at"),
                "source_name": item.get("source_name", "主要新聞"),
                "source_url": url_val,
                "hash": hashlib.md5(url_val.encode()).hexdigest(),
            })
        print(f"    Gemini検索成功: {len(results)}件の記事を取得しました")
        return results
    except Exception as e:
        print(f"  [GEMINI SEARCH ERROR] {topic_title!r}: {e}")
        return []


# ==============================
# Topic ごとの収集
# ==============================

def collect_for_topic(topic: dict) -> list[dict]:
    documents: list[dict] = []
    seen: set[str] = set()

    def add_doc(doc: dict) -> None:
        if doc["hash"] not in seen and doc["url"]:
            seen.add(doc["hash"])
            documents.append(doc)

    from datetime import datetime, timedelta
    default_from_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    
    kokkai_last_date = topic.get("kokkai_last_date", default_from_date)
    news_last_date = topic.get("news_last_date", default_from_date)

    latest_kokkai_date = kokkai_last_date
    latest_news_date = news_last_date

    # ── Tier 1: 一次資料 ──────────────────────
    # 国会議事録 API（認証不要）
    for primary in topic.get("rss_feeds_primary", []):
        if isinstance(primary, dict) and primary.get("type") == "ndl_api":
            kw = primary.get("keyword", topic["title"])
            print(f"    国会議事録API: keyword={kw!r}, from={kokkai_last_date}")
            for item in fetch_kokkai_records(kw, from_date=kokkai_last_date):
                add_doc(item)
                if item["published_at"] and item["published_at"] > latest_kokkai_date:
                    latest_kokkai_date = item["published_at"]

    # ── Tier 2: RSS フィード（共通ソース + 固有ソース） ──
    rss_list = []
    # デフォルトで共通ソースを使用（明示的にFalseにされていない限り）
    if topic.get("use_shared_sources", True):
        shared_path = Path(__file__).parent.parent / "config" / "shared_sources.yaml"
        if shared_path.exists():
            try:
                import yaml
                with open(shared_path, encoding="utf-8") as f:
                    shared_data = yaml.safe_load(f)
                for item in shared_data.get("shared_rss_feeds", {}).values():
                    url = item.get("url")
                    if url:
                        rss_list.append(url)
            except Exception as e:
                print(f"    [WARNING] shared_sources.yaml 読み込み失敗: {e}")

    # 個別Topic固有のRSS
    rss_list.extend(topic.get("rss_feeds", []))

    # 重複URLを排除して巡回
    for rss_url in set(rss_list):
        print(f"    RSS: {rss_url}")
        for item in fetch_rss(rss_url):
            add_doc(item)
            pub_at = item.get("published_at")
            if pub_at and pub_at > latest_news_date:
                latest_news_date = pub_at
        # 連続アクセスを防ぐために1秒スリープ
        time.sleep(1)

    # ── Tier 2-3: Web 検索 (Gemini Google Search Grounding) ──
    print(f"    Gemini Google Search Grounding を実行中...")
    gemini_model = "gemini-3.5-flash"  # 日次更新での検索グラウンディング用モデル
    for item in search_via_gemini_grounding(topic["title"], topic.get("keywords", []), gemini_model, from_date=news_last_date):
        add_doc(item)
        pub_at = item.get("published_at")
        if pub_at and pub_at > latest_news_date:
            latest_news_date = pub_at

    # 最新日付を保存
    topic_dir = Path(topic.get("_dir", ""))
    if topic_dir.exists():
        yaml_path = topic_dir / "topic.yaml"
        try:
            with open(yaml_path, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            config["kokkai_last_date"] = latest_kokkai_date
            config["news_last_date"] = latest_news_date
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception as e:
            print(f"    [WARNING] topic.yaml 保存エラー: {e}")

    return documents


# ==============================
# メイン
# ==============================

def main() -> None:
    topics = load_topics()
    if not topics:
        print("Topic が見つかりません")
        return

    all_documents: dict[str, list[dict]] = {}

    for topic in topics:
        if topic.get("status") != "active":
            print(f"[SKIP] {topic.get('title')} (status: {topic.get('status')})")
            continue

        print(f"\n[COLLECT] {topic['title']} ({topic['slug']})")
        docs = collect_for_topic(topic)
        print(f"  収集件数: {len(docs)}")
        all_documents[topic["slug"]] = docs

    output_path = "/tmp/collected_documents.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(all_documents, f, ensure_ascii=False, indent=2, default=str)

    total = sum(len(v) for v in all_documents.values())
    print(f"\n完了: {len(all_documents)} topic, {total} documents → {output_path}")


if __name__ == "__main__":
    main()
