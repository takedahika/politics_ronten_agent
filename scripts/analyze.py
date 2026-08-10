"""
analyze.py
----------
収集したドキュメントを Gemini で分析し、
各 Topic の Markdown ファイルを更新する。

更新内容は /tmp/analysis_results.json にも保存する。
"""

import google.generativeai as genai
import json
import yaml
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# ==============================
# Gemini 設定
# ==============================

RELEVANCE_MODEL = "gemini-2.0-flash"
EXTRACTION_MODEL = "gemini-2.5-flash"

RELEVANCE_PROMPT_TEMPLATE = """
あなたは政治・社会問題のリサーチアシスタントです。

以下の記事が、指定されたTopicに関連しているかを判定してください。

## Topic
タイトル: {topic_title}
キーワード: {keywords}

## 記事
タイトル: {article_title}
URL: {article_url}
内容: {article_content}

## 出力形式（JSONのみ、他のテキストなし）
{{
  "relevant": true または false,
  "reason": "判定理由（1文）",
  "confidence": 0.0〜1.0
}}
""".strip()

EXTRACTION_PROMPT_TEMPLATE = """
あなたは「論点の現在地」というメディアの情報整理AIです。

## あなたの役割
- 収集した記事から、Topicに関連する情報を抽出する
- 既存の知識と重複しない新しい情報のみを抽出する
- Facts（確認可能な事実）とClaims（誰かの主張）を明確に分離する

## 厳守ルール
- 出典のないFactを生成しない
- Sourceに存在しない発言を生成しない
- ClaimとFactを混同しない
- 推測をFactとして扱わない
- 政治的な結論を自分で出さない

---

## Topic: {topic_title}

## 現在の知識（既存のMarkdown）
{current_state}

## 新しく収集した記事（関連性の高いもの）
{new_documents}

---

## 出力形式（JSONのみ、他のテキストなし）
{{
  "current_status_update": "現在の状況の更新文（変更不要なら null）",
  "new_events": [
    {{
      "date": "YYYY-MM-DD または YYYY-MM または YYYY",
      "title": "出来事のタイトル",
      "description": "詳細説明",
      "source_url": "出典URL"
    }}
  ],
  "new_facts": [
    {{
      "statement": "確認可能な事実の文",
      "source_url": "出典URL"
    }}
  ],
  "new_claims": [
    {{
      "speaker": "発言者名・組織名",
      "statement": "主張の内容",
      "context": "発言の文脈（いつ・どこで）",
      "source_url": "出典URL"
    }}
  ],
  "new_sources": [
    {{
      "name": "情報源名",
      "url": "URL",
      "type": "government / academic / news / other"
    }}
  ],
  "open_questions": ["まだ分かっていない問い"],
  "summary_of_changes": "変更内容の要約（PR descriptionに使用）"
}}
""".strip()


# ==============================
# Topic の現在の状態を読み込む
# ==============================

def load_topic_state(topic_dir: str) -> dict[str, str]:
    state = {}
    for filename in [
        "overview.md", "timeline.md", "facts.md",
        "claims.md", "issues.md", "international.md", "sources.md",
    ]:
        path = Path(topic_dir) / filename
        if path.exists():
            state[filename] = path.read_text(encoding="utf-8")
    return state


# ==============================
# Relevance フィルタ（安価・高速）
# ==============================

def filter_relevant_documents(
    topic: dict,
    documents: list[dict],
    model: genai.GenerativeModel,
) -> list[dict]:
    """安価なモデルで関連性を判定し、関連するドキュメントのみ返す"""
    relevant = []
    keywords = topic.get("keywords", [])

    for doc in documents:
        text = f"{doc.get('title', '')} {doc.get('content', '')}".lower()

        # まずキーワードマッチで高速フィルタ
        if not any(kw.lower() in text for kw in keywords):
            continue

        # Gemini で精密判定
        prompt = RELEVANCE_PROMPT_TEMPLATE.format(
            topic_title=topic["title"],
            keywords="、".join(keywords),
            article_title=doc.get("title", ""),
            article_url=doc.get("url", ""),
            article_content=doc.get("content", "")[:500],
        )

        try:
            response = model.generate_content(
                prompt,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            result = json.loads(response.text)
            if result.get("relevant") and result.get("confidence", 0) >= 0.6:
                relevant.append(doc)
        except Exception as e:
            print(f"    [RELEVANCE ERROR] {doc.get('title', '')[:40]}: {e}")
            # エラー時はキーワードマッチのみで判断（含める）
            relevant.append(doc)

    return relevant


# ==============================
# 情報抽出（高性能モデル）
# ==============================

def extract_updates(
    topic: dict,
    relevant_docs: list[dict],
    current_state: dict[str, str],
    model: genai.GenerativeModel,
) -> dict | None:
    """関連ドキュメントから更新情報を抽出する"""

    current_state_text = "\n\n".join(
        f"=== {fname} ===\n{content}"
        for fname, content in current_state.items()
    )

    docs_text = "\n\n".join(
        f"--- 記事{i+1} ---\n"
        f"タイトル: {doc.get('title', '')}\n"
        f"URL: {doc.get('url', '')}\n"
        f"公開日: {doc.get('published_at', '不明')}\n"
        f"内容: {doc.get('content', '')[:1500]}"
        for i, doc in enumerate(relevant_docs[:8])  # 最大8件
    )

    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        topic_title=topic["title"],
        current_state=current_state_text[:6000],
        new_documents=docs_text,
    )

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
        print(f"  [EXTRACTION ERROR] {topic['title']}: {e}")
        return None


# ==============================
# Markdown ファイルの更新
# ==============================

def _source_link(url: str, label: str | None = None) -> str:
    """出典URLを必ずハイパーリンク形式にフォーマットする"""
    if not url:
        return "出典URL不明"
    display = label if label else url
    return f"[{display}]({url})"


def update_markdown_files(topic_dir: str, updates: dict) -> bool:
    """抽出した情報を各 Markdown ファイルに追記する。変更があった場合 True を返す"""
    import re

    changed = False
    topic_path = Path(topic_dir)
    now = datetime.now(tz=timezone.utc).strftime("%Y年%m月%d日")

    # --- overview.md: Current Status 更新 ---
    if updates.get("current_status_update"):
        overview_path = topic_path / "overview.md"
        content = overview_path.read_text(encoding="utf-8") if overview_path.exists() else ""

        if "## 現在の状況" in content:
            new_content = re.sub(
                r"(## 現在の状況\n).*?(?=\n##|\Z)",
                r"\1" + updates["current_status_update"].replace("\\", "\\\\") + "\n\n",
                content,
                flags=re.DOTALL,
            )
        else:
            new_content = content + f"\n## 現在の状況\n\n{updates['current_status_update']}\n"

        new_content = re.sub(
            r"\*最終更新: .*?\*",
            f"*最終更新: {now}*",
            new_content,
        )
        if "*最終更新:" not in new_content:
            new_content = f"*最終更新: {now}*\n\n" + new_content

        overview_path.write_text(new_content, encoding="utf-8")
        changed = True

    # --- timeline.md: 新しいイベントを追加（出典リンク必須） ---
    if updates.get("new_events"):
        timeline_path = topic_path / "timeline.md"
        existing = timeline_path.read_text(encoding="utf-8") if timeline_path.exists() else "## タイムライン\n\n"

        new_entries = []
        for event in updates["new_events"]:
            source_url = event.get("source_url", "")
            source_name = event.get("source_name", source_url or "出典URL不明")

            # 出典URLがない場合は警告（スキップはしない）
            if not source_url:
                print(f"  [WARNING] Eventに出典URLなし: {event.get('title', '')[:40]}")

            source_text = _source_link(source_url, source_name) if source_url else "*(出典URL不明)*"

            entry = (
                f"### {event.get('date', '日付不明')} — {event.get('title', '')}\n\n"
                f"{event.get('description', '')}\n\n"
                f"> 出典: {source_text}\n"
            )
            if event.get("title", "") not in existing:
                new_entries.append(entry)

        if new_entries:
            header = "## タイムライン\n\n"
            body = existing.replace(header, "", 1)
            timeline_path.write_text(
                header + "\n---\n\n".join(new_entries) + "\n---\n\n" + body,
                encoding="utf-8",
            )
            changed = True

    # --- facts.md: 新しいファクト（出典ハイパーリンク必須） ---
    if updates.get("new_facts"):
        facts_path = topic_path / "facts.md"
        existing = facts_path.read_text(encoding="utf-8") if facts_path.exists() else "## Facts（確認された事実）\n\n"

        new_entries = []
        for fact in updates["new_facts"]:
            stmt = fact.get("statement", "")
            source_url = fact.get("source_url", "")
            source_name = fact.get("source_name", None)

            if not source_url:
                print(f"  [WARNING] Factに出典URLなし: {stmt[:60]}")
                # 出典なしFactは追加しない（仕様上の制約）
                continue

            source_text = _source_link(source_url, source_name or "出典")
            entry = f"- {stmt} {source_text}\n"

            if stmt not in existing:
                new_entries.append(entry)

        if new_entries:
            facts_path.write_text(existing + "\n" + "".join(new_entries), encoding="utf-8")
            changed = True

    # --- claims.md: 新しいClaim（出典ハイパーリンク必須） ---
    if updates.get("new_claims"):
        claims_path = topic_path / "claims.md"
        existing = claims_path.read_text(encoding="utf-8") if claims_path.exists() else "## Claims（立場・主張）\n\n"

        new_entries = []
        for claim in updates["new_claims"]:
            stmt = claim.get("statement", "")
            source_url = claim.get("source_url", "")
            source_name = claim.get("source_name", None)
            pub_date = claim.get("published_at", "")

            if not source_url:
                print(f"  [WARNING] Claimに出典URLなし: {stmt[:60]}")

            source_text = _source_link(source_url, source_name or "出典") if source_url else "*(出典URL不明)*"
            date_text = f"・{pub_date}" if pub_date else ""

            entry_text = (
                f"### {claim.get('speaker', '不明')}\n\n"
                f"> {stmt}\n\n"
                f"*{claim.get('context', '')}*\n\n"
                f"出典: {source_text}{date_text}\n"
            )
            if stmt not in existing:
                new_entries.append(entry_text)

        if new_entries:
            claims_path.write_text(existing + "\n---\n\n" + "\n---\n\n".join(new_entries), encoding="utf-8")
            changed = True

    # --- sources.md: 新しいソースを追加（完全なメタデータ） ---
    if updates.get("new_sources"):
        sources_path = topic_path / "sources.md"
        existing = sources_path.read_text(encoding="utf-8") if sources_path.exists() else "## Sources（情報源）\n\n"

        new_entries = []
        for source in updates["new_sources"]:
            url = source.get("url", "")
            name = source.get("name", url)
            src_type = source.get("type", "other")
            retrieved = source.get("retrieved_at", now)

            if url and url not in existing:
                entry = f"- [{name}]({url}) `{src_type}` — 取得日: {retrieved}\n"
                new_entries.append(entry)

        if new_entries:
            sources_path.write_text(existing + "".join(new_entries), encoding="utf-8")
            changed = True

    # --- Open Questions を overview.md に追記 ---
    if updates.get("open_questions"):
        overview_path = topic_path / "overview.md"
        existing = overview_path.read_text(encoding="utf-8") if overview_path.exists() else ""

        new_q = [q for q in updates["open_questions"] if q not in existing]

        if new_q:
            if "## Open Questions" in existing:
                existing = existing.rstrip() + "\n" + "\n".join(f"- {q}" for q in new_q) + "\n"
            else:
                existing += "\n\n## Open Questions（未解決の問い）\n\n" + "\n".join(f"- {q}" for q in new_q) + "\n"
            overview_path.write_text(existing, encoding="utf-8")
            changed = True

    return changed


# ==============================
# メイン
# ==============================

def main() -> None:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("ERROR: GEMINI_API_KEY が設定されていません")
        sys.exit(1)

    genai.configure(api_key=api_key)
    relevance_model = genai.GenerativeModel(RELEVANCE_MODEL)
    extraction_model = genai.GenerativeModel(EXTRACTION_MODEL)

    # 収集済みドキュメントを読み込む
    docs_path = "/tmp/collected_documents.json"
    if not Path(docs_path).exists():
        print("ERROR: /tmp/collected_documents.json が見つかりません。collect.py を先に実行してください")
        sys.exit(1)

    with open(docs_path, encoding="utf-8") as f:
        all_documents: dict[str, list[dict]] = json.load(f)

    # Topic を読み込む
    topics_dir = Path("topics")
    topics = []
    for topic_dir in sorted(topics_dir.iterdir()):
        config_file = topic_dir / "topic.yaml"
        if config_file.exists():
            with open(config_file, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            config["_dir"] = str(topic_dir)
            topics.append(config)

    results = {}

    for topic in topics:
        slug = topic["slug"]
        if topic.get("status") != "active":
            continue
        if slug not in all_documents:
            continue

        docs = all_documents[slug]
        print(f"\n[ANALYZE] {topic['title']} ({slug})")
        print(f"  収集ドキュメント数: {len(docs)}")

        # Step 1: Relevance フィルタ
        relevant = filter_relevant_documents(topic, docs, relevance_model)
        print(f"  関連ドキュメント数: {len(relevant)}")

        if not relevant:
            print("  → 更新なし")
            results[slug] = {"changed": False, "summary": "関連する新情報なし"}
            continue

        # Step 2: 現在の状態を読み込む
        current_state = load_topic_state(topic["_dir"])

        # Step 3: 情報抽出
        updates = extract_updates(topic, relevant, current_state, extraction_model)
        if not updates:
            results[slug] = {"changed": False, "summary": "抽出失敗"}
            continue

        # Step 4: Markdown 更新
        changed = update_markdown_files(topic["_dir"], updates)
        print(f"  変更あり: {changed}")
        print(f"  要約: {updates.get('summary_of_changes', '')}")

        results[slug] = {
            "changed": changed,
            "summary": updates.get("summary_of_changes", ""),
            "events": len(updates.get("new_events", [])),
            "facts": len(updates.get("new_facts", [])),
            "claims": len(updates.get("new_claims", [])),
        }

    # 結果を保存
    with open("/tmp/analysis_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    any_changed = any(v.get("changed") for v in results.values())
    print(f"\n完了: 変更あり={any_changed}")

    # 変更がなければ exit code 0 だが、GitHub Actions 側でスキップ判定
    if not any_changed:
        # 変更なしを示すファイルを作成
        Path("/tmp/no_changes").touch()


if __name__ == "__main__":
    main()
