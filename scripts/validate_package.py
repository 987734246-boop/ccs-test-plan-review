#!/usr/bin/env python3
"""Validate WorkBuddy's documented frontmatter and package references."""
import re
import sys
from pathlib import Path


def validate(root):
    text=(root/"SKILL.md").read_text(encoding="utf-8")
    match=re.match(r"^---\n(.*?)\n---",text,re.S)
    if not match: raise ValueError("Missing YAML frontmatter")
    required=("name","display_name","display_name_en","description","description_zh","description_en","version","author")
    fields=dict(re.findall(r"^([a-z_]+):\s*(.+)$",match[1],re.M))
    for key in required:
        if not fields.get(key): raise ValueError("Missing WorkBuddy field: "+key)
    if fields["name"]!=root.name or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*",fields["name"]): raise ValueError("Invalid skill name")
    for relative in re.findall(r"@((?:references|scripts)/[\w./-]+)",text):
        if not (root/relative).is_file(): raise ValueError("Missing reference: "+relative)
    for file in (root/"scripts").glob("*.py"):
        compile(file.read_text(encoding="utf-8"),str(file),"exec")
    return {"valid":True,"target":"WorkBuddy","required_fields":list(required)}


if __name__=="__main__":
    import json
    root=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parents[1]
    print(json.dumps(validate(root),ensure_ascii=False))
