"""
create_pr.py
------------
analyze.py が生成した更新内容をもとに GitHub Pull Request を作成する。

必要な環境変数:
  GITHUB_TOKEN       - GitHub Personal Access Token（repo権限）
  GITHUB_REPOSITORY  - "owner/repo" 形式（例: yourname/ronten-no-genzaichi）
"""

import json
import os
import sys
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from github import Github, GithubException


# ==============================
# Git 操作ヘルパー
# ==============================

def run_git(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        check=check,
        capture_output=True,
        text=True,
    )


def get_changed_files() -> list[str]:
    result = run_git(["diff", "--name-only", "HEAD"], check=False)
    files = [f.strip() for f in result.stdout.splitlines() if f.strip()]
    # 新規ファイルも含める
    result2 = run_git(["ls-files", "--others", "--exclude-standard"], check=False)
    files += [f.strip() for f in result2.stdout.splitlines() if f.strip()]
    return files


# ==============================
# PR 説明文の生成
# ==============================

def build_pr_body(results: dict) -> str:
    now = datetime.now(tz=timezone.utc).strftime("%Y年%m月%d日 %H:%M UTC")
    lines = [
        "## 🤖 AI による自動更新提案",
        "",
        f"**実行日時**: {now}",
        "",
        "---",
        "",
        "### 更新内容",
        "",
    ]

    for slug, result in results.items():
        if not result.get("changed"):
            continue
        lines.append(f"#### 📌 {slug}")
        lines.append("")
        lines.append(f"**要約**: {result.get('summary', '（要約なし）')}")
        lines.append("")
        items = []
        if result.get("events"):
            items.append(f"- 新しいイベント: {result['events']}件")
        if result.get("facts"):
            items.append(f"- 新しいFact: {result['facts']}件")
        if result.get("claims"):
            items.append(f"- 新しいClaim: {result['claims']}件")
        lines.extend(items)
        lines.append("")

    lines.extend([
        "---",
        "",
        "### レビュー方法",
        "",
        "1. **Files changed** タブで変更内容を確認",
        "2. 問題なければ **Merge pull request** でApprove",
        "3. 不要な場合は **Close pull request** でReject",
        "",
        "> このPRはシステムによって自動生成されました。",
        "> マージすると自動的にWebサイトが更新されます。",
    ])

    return "\n".join(lines)


# ==============================
# メイン
# ==============================

def main() -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo_name = os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo_name:
        print("ERROR: GITHUB_TOKEN または GITHUB_REPOSITORY が設定されていません")
        sys.exit(1)

    # 変更なしフラグを確認
    if Path("/tmp/no_changes").exists():
        print("変更なし → PR 作成をスキップします")
        sys.exit(0)

    # 分析結果を読み込む
    results_path = "/tmp/analysis_results.json"
    if not Path(results_path).exists():
        print("ERROR: analysis_results.json が見つかりません")
        sys.exit(1)

    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)

    any_changed = any(v.get("changed") for v in results.values())
    if not any_changed:
        print("変更なし → PR 作成をスキップします")
        sys.exit(0)

    # ブランチ名を生成
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M")
    branch_name = f"update/ai-{timestamp}"

    # Git 設定
    run_git(["config", "user.name", "論点の現在地 Bot"])
    run_git(["config", "user.email", "bot@ronten-no-genzaichi.example"])

    # ブランチ作成・チェックアウト
    run_git(["checkout", "-b", branch_name])

    # 変更ファイルをステージング
    changed_files = get_changed_files()
    if not changed_files:
        print("Git の変更ファイルなし → PR 作成をスキップします")
        sys.exit(0)

    print(f"変更ファイル: {changed_files}")
    run_git(["add"] + changed_files)

    # コミット
    changed_slugs = [slug for slug, v in results.items() if v.get("changed")]
    commit_msg = f"update: AI更新 {', '.join(changed_slugs)} ({timestamp})"
    run_git(["commit", "-m", commit_msg])

    # プッシュ
    remote_url = f"https://x-access-token:{token}@github.com/{repo_name}.git"
    run_git(["remote", "set-url", "origin", remote_url])
    run_git(["push", "origin", branch_name])

    # GitHub API で PR 作成
    g = Github(token)
    repo = g.get_repo(repo_name)

    # 要約タイトルを生成
    summaries = [v["summary"] for v in results.values() if v.get("changed") and v.get("summary")]
    pr_title = f"[AI更新] {summaries[0][:60]}" if summaries else f"[AI更新] {timestamp}"

    pr_body = build_pr_body(results)

    pr = repo.create_pull(
        title=pr_title,
        body=pr_body,
        head=branch_name,
        base="main",
    )

    print(f"\n✅ PR を作成しました: {pr.html_url}")


if __name__ == "__main__":
    main()
