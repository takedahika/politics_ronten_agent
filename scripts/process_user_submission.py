import os
import sys
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

def fetch_url_content(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for script in soup(["script", "style", "nav", "footer", "header"]):
            script.extract()
        text = soup.get_text(separator='\n')
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        text = '\n'.join(chunk for chunk in chunks if chunk)
        return text[:10000]
    except Exception as e:
        print(f"Warning: Failed to fetch URL content: {e}")
        return "ウェブページの内容を直接取得できませんでした。"

def process_submission():
    slug = os.environ.get("TOPIC_SLUG")
    news_url = os.environ.get("NEWS_URL", "")
    comment = os.environ.get("USER_COMMENT", "")
    
    if not slug or not news_url:
        print("Error: TOPIC_SLUG and NEWS_URL are required.")
        sys.exit(1)
        
    facts_path = f"topics/{slug}/facts.md"
    timeline_path = f"topics/{slug}/timeline.md"
    
    if not os.path.exists(facts_path) or not os.path.exists(timeline_path):
        print(f"Error: Topic files not found for {slug}")
        sys.exit(1)
        
    with open(facts_path, 'r', encoding='utf-8') as f:
        current_facts = f.read()
    with open(timeline_path, 'r', encoding='utf-8') as f:
        current_timeline = f.read()
        
    print(f"Fetching content from: {news_url}")
    url_content = fetch_url_content(news_url)
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-3.5-flash')
    prompt = f"""あなたは客観的で中立な「論点の現在地」のファクトチェッカー・編集者です。
現在、以下の2つのMarkdown記事（ファクトリストとタイムライン）があります。

【現在の記事 (facts.md)】
```markdown
{current_facts}
```

【現在の記事 (timeline.md)】
```markdown
{current_timeline}
```

読者から、この記事の情報の裏付け、または修正に関する情報提供がありました。

【ユーザーからの提供情報】
- 報告の目的・コメント: {comment}
- URL: {news_url}

【URLの内容（抜粋）】
{url_content}

指示:
この情報（URLの内容）を評価し、既存のファクトやタイムラインの出来事の裏付けが取れたか、あるいは修正が必要かを判定してください。
- 裏付けが取れた場合、該当箇所の `[status:unverified]` を `[status:verified]` に変更してください。必要に応じて、提供されたURLを出典として末尾に追記してください。
- ユーザーから修正提案があり、URLの内容がそれを裏付ける信頼できる情報（大手報道機関や公的機関）であれば、記述を客観的な事実に修正した上で `[status:verified]` にしてください。
- 全く無関係なスパムや、信頼できないソースの場合はMarkdownを変更しないでください。

【出力フォーマット】
以下のJSONフォーマットで出力してください。装飾やJSON以外のテキストは含めないでください。
{{
  "summary": "管理人に向けた検証結果の報告（PRのコメントとして表示されます）。『提供されたURLを確認した結果、事実リストの○○という記載の裏付けが取れたため、検証済ステータスに変更しました。』など。",
  "updated_facts_md": "修正後の完全な facts.md のテキスト（変更がない場合は元のテキストをそのまま出力）",
  "updated_timeline_md": "修正後の完全な timeline.md のテキスト（変更がない場合は元のテキストをそのまま出力）"
}}

【絶対ルール】
1. 「AIがまとめました」「私が提案します」などのAI自身についての言及や挨拶は一切含めないこと。
2. 文章は「だ・である調」で知的なトーンを維持すること。ただし、高校三年生（18歳）が読んでスムーズに理解できるよう、官公庁や法律の特有の難解な熟語は使用を禁止し、平易な言葉に翻訳して記載すること。
"""
    print("Sending to Gemini...")
    response = model.generate_content(
        prompt,
        generation_config=genai.GenerationConfig(temperature=0.2),
        tools=[genai.protos.Tool(google_search=genai.protos.Tool.GoogleSearch())]
    )
    
    result_text = response.text.strip()
    if result_text.startswith("```json"):
        result_text = result_text[7:]
    elif result_text.startswith("```"):
        result_text = result_text[3:]
    if result_text.endswith("```"):
        result_text = result_text[:-3]
        
    import json
    try:
        output_data = json.loads(result_text.strip())
        new_facts = output_data.get("updated_facts_md", current_facts)
        new_timeline = output_data.get("updated_timeline_md", current_timeline)
        summary = output_data.get("summary", "要約の生成に失敗しました。")
    except json.JSONDecodeError:
        print("Failed to parse JSON response.")
        new_facts = current_facts
        new_timeline = current_timeline
        summary = "AIからの応答が正しいJSON形式ではありませんでした。"
    
    with open(facts_path, 'w', encoding='utf-8') as f:
        f.write(new_facts)
    with open(timeline_path, 'w', encoding='utf-8') as f:
        f.write(new_timeline)
        
    with open("summary.txt", 'w', encoding='utf-8') as f:
        f.write(summary)
        
    print(f"Successfully updated files and created summary.txt")

if __name__ == "__main__":
    process_submission()
