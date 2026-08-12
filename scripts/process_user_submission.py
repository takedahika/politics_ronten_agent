import os
import sys
import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

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
    info_type = os.environ.get("INFO_TYPE", "未分類")
    news_url = os.environ.get("NEWS_URL", "")
    comment = os.environ.get("USER_COMMENT", "")
    
    if not slug or not news_url:
        print("Error: TOPIC_SLUG and NEWS_URL are required.")
        sys.exit(1)
        
    md_path = f"topics/{slug}/content.md"
    if not os.path.exists(md_path):
        print(f"Error: Topic file not found at {md_path}")
        sys.exit(1)
        
    with open(md_path, 'r', encoding='utf-8') as f:
        current_md = f.read()
        
    print(f"Fetching content from: {news_url}")
    url_content = fetch_url_content(news_url)
    
    client = genai.Client()
    prompt = f"""あなたは客観的で中立な「論点の現在地」の編集者です。
現在、以下のMarkdown形式のトピック記事があります。

【現在の記事】
```markdown
{current_md}
```

読者から、このトピックに関して新しい情報提供がありました。

【ユーザーからの提供情報】
- 情報の種類: {info_type}
- URL: {news_url}
- 補足コメント: {comment}

【URLの内容（抜粋）】
{url_content}

指示:
この新しい情報（URLの内容）を評価し、信頼できる一次情報または大手報道機関のものであれば、現在の記事の適切なセクション（タイムライン、関連する事実とデータ、政党・団体のスタンスなど）に追記してください。
- 追記する際は、客観的な事実のみを記載し、出典として提供されたURLをリンクしてください。

【出力フォーマット】
以下のJSONフォーマットで出力してください。装飾やJSON以外のテキストは含めないでください。
{
  "summary": "ニュースの内容の要約と、今回どこをどのように修正・追記したかの詳細な説明",
  "updated_markdown": "修正後の完全なMarkdownテキスト"
}

【絶対ルール】
1. 「AIがまとめました」「私が提案します」などのAI自身についての言及や挨拶は一切含めないこと。
2. 文章は「だ・である調」で知的なトーンを維持すること。ただし、高校三年生（18歳）が読んでスムーズに理解できるよう、官公庁や法律の特有の難解な熟語（例：「乏しい」「属し」など）は使用を禁止し、簡潔で明瞭な平易な言葉に翻訳して記載すること。
"""
    print("Sending to Gemini...")
    response = client.models.generate_content(
        model='gemini-2.5-pro',
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.2, tools=[{"google_search": {}}])
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
        new_md = output_data.get("updated_markdown", current_md)
        summary = output_data.get("summary", "要約の生成に失敗しました。")
    except json.JSONDecodeError:
        print("Failed to parse JSON response.")
        new_md = current_md
        summary = "AIからの応答が正しいJSON形式ではありませんでした。"
    
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(new_md)
        
    with open("summary.txt", 'w', encoding='utf-8') as f:
        f.write(summary)
        
    print(f"Successfully updated {md_path} and created summary.txt")

if __name__ == "__main__":
    process_submission()
