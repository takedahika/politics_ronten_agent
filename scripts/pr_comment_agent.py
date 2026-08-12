import os
import sys
import json
import subprocess
from pathlib import Path
from github import Github
import google.generativeai as genai

def run_git(args: list[str]):
    print(f"Running git command: git {' '.join(args)}")
    result = subprocess.run(["git"] + args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Git command failed: {result.stderr}")
        raise RuntimeError(f"Git error: {result.stderr}")
    return result.stdout.strip()

def main():
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")
    pr_number_str = os.environ.get("PR_NUMBER")
    comment_body = os.environ.get("COMMENT_BODY", "")
    comment_id_str = os.environ.get("COMMENT_ID")

    if not all([token, repo_name, pr_number_str]):
        print("Required environment variables are missing.")
        sys.exit(1)

    pr_number = int(pr_number_str)
    
    # 1. Initialize GitHub API
    g = Github(token)
    repo = g.get_repo(repo_name)
    pr = repo.get_pull(pr_number)
    
    if comment_id_str:
        try:
            # React to the comment to show we're processing
            comment = pr.as_issue().get_comment(int(comment_id_str))
            comment.create_reaction("eyes")
        except Exception as e:
            print(f"Could not create reaction: {e}")

    # 2. Identify target files (Markdown files modified in this PR)
    pr_files = pr.get_files()
    target_files = []
    for f in pr_files:
        if f.filename.startswith("topics/") and f.filename.endswith(".md"):
            target_files.append(f.filename)

    if not target_files:
        pr.as_issue().create_comment("申し訳ありません。このPRには修正対象となるトピックの記事（Markdownファイル）が含まれていないため、自動修正を実行できません。")
        sys.exit(0)

    print(f"Target files: {target_files}")

    # 3. Get conversation history
    comments = pr.as_issue().get_comments()
    history = []
    for c in comments:
        role = "AI" if c.user.login == "github-actions[bot]" else "User"
        history.append(f"{role}: {c.body}")
    
    history_text = "\n\n".join(history[-10:]) # Keep last 10 comments for context

    # 4. Prepare files content
    files_content = {}
    for filename in target_files:
        if os.path.exists(filename):
            with open(filename, 'r', encoding='utf-8') as f:
                files_content[filename] = f.read()
        else:
            print(f"File not found locally: {filename}")
            
    if not files_content:
        print("No local files found to modify.")
        sys.exit(1)

    # 5. Call Gemini to modify the files
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not set.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-3.5-flash')
    
    prompt = f"""あなたは客観的で中立な「論点の現在地」の編集AIです。
ユーザーからPull Requestのコメントで記事の修正指示を受けました。

【修正指示】
{comment_body}

【これまでの会話履歴（文脈）】
{history_text}

【対象ファイル】
"""
    for filename, content in files_content.items():
        prompt += f"\n--- {filename} ---\n```markdown\n{content}\n```\n"

    prompt += """
指示:
ユーザーの修正指示に従って、対象ファイルの内容を修正してください。

【出力フォーマット】
複数のファイルがある場合を考慮し、必ず以下のJSONフォーマットで出力してください。装飾やJSON以外のテキストは含めないでください。
{
  "ファイル名": "修正後の完全なMarkdownテキスト",
  "ファイル名2": "修正後の完全なMarkdownテキスト"
}

【絶対ルール】
1. 「AIがまとめました」「私が提案します」などのAI自身についてのメタな言及や挨拶は一切含めないこと。
2. 文章は「だ・である調」で知的なトーンを維持すること。
3. ただし、高校三年生（18歳）が読んでスムーズに理解できるよう、官公庁や法律の特有の難解な熟語（例：「乏しい」「属し」「不均衡」など）は使用を禁止し、簡潔で明瞭な平易な言葉に翻訳して記載すること。
4. Markdownのフォーマット（見出し、リスト、リンクなど）は絶対に崩さないこと。
"""

    print("Calling Gemini to process modifications...")
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.2)
        )
        
        result_text = response.text.strip()
        if result_text.startswith("```json"):
            result_text = result_text[7:]
        elif result_text.startswith("```"):
            result_text = result_text[3:]
        if result_text.endswith("```"):
            result_text = result_text[:-3]
        
        updated_files = json.loads(result_text.strip())
    except Exception as e:
        error_msg = f"申し訳ありません。AIによる修正処理中にエラーが発生しました。\nエラー詳細: {e}"
        print(error_msg)
        pr.as_issue().create_comment(error_msg)
        sys.exit(1)

    # 6. Save modified files
    modified_any = False
    for filename, new_content in updated_files.items():
        if filename in target_files:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(new_content)
            run_git(["add", filename])
            modified_any = True
            print(f"Updated {filename}")

    if not modified_any:
        print("No files were modified.")
        pr.as_issue().create_comment("指定された修正指示に基づくファイル変更はありませんでした。")
        sys.exit(0)

    # 7. Commit and Push
    try:
        run_git(["config", "user.name", "論点の現在地 Bot"])
        run_git(["config", "user.email", "bot@ronten-no-genzaichi.example"])
        
        # Determine the correct remote URL with token
        remote_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"
        run_git(["remote", "set-url", "origin", remote_url])
        
        commit_message = f"fix(ai): ユーザーの指示に基づく自動修正\n\nTriggered by comment: {comment_body[:50]}..."
        run_git(["commit", "-m", commit_message])
        
        # Head branch (where the PR is coming from)
        head_branch = pr.head.ref
        run_git(["push", "origin", f"HEAD:{head_branch}"])
        
        # 8. Success Comment
        if comment_id_str:
            try:
                comment.create_reaction("+1")
            except:
                pass
        
        pr.as_issue().create_comment("✅ ご指示いただいた修正を反映し、コミットを追加しました！\n差分（Files changed）をご確認ください。")
        print("Successfully pushed changes and commented.")

    except Exception as e:
        print(f"Git operations failed: {e}")
        pr.as_issue().create_comment(f"修正は作成できましたが、コミット・プッシュ中にエラーが発生しました。\n`{e}`")
        sys.exit(1)

if __name__ == "__main__":
    main()
