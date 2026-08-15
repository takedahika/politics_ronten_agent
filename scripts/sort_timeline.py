import re
from pathlib import Path

def sort_timeline_file(filepath):
    content = Path(filepath).read_text(encoding="utf-8")
    header_match = re.search(r"###\s*📜\s*発端と経過（歴史的事実）\s*\n+", content)
    
    if not header_match:
        return
        
    header = content[:header_match.end()]
    body = content[header_match.end():]
    
    # Split by list item starting with date
    entries = re.findall(r"(?m)^- \*\*(\d{4}-\d{2}-\d{2})\*\*: (.*?(?=\n- \*\*|\Z))", body, re.DOTALL)
    
    if not entries:
        return
        
    # Reconstruct entries and sort
    sorted_entries = sorted(entries, key=lambda x: x[0], reverse=True)
    
    new_body = ""
    for date, text in sorted_entries:
        new_body += f"- **{date}**: {text.strip()}\n\n"
        
    Path(filepath).write_text(header + new_body, encoding="utf-8")
    print(f"Sorted {filepath}")

for p in Path("topics").rglob("timeline.md"):
    sort_timeline_file(p)
