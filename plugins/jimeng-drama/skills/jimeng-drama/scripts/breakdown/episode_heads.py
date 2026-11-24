#!/usr/bin/env python3
"""列出原文里建议当作集起点的行。用法：python3 episode_heads.py input.txt

认「第N集」「EP01」「Episode 1」这类标题；开头的目录和大纲、后面的分镜表和修订记录这类集号回退的块、
同一集的续写标题、正文里以「第N集」开头的长句，都不算新的一集（规则见 headings.py 开头）。
打印 JSON：{"episodes": [{"line": 行号, "number": 集号, "title": 标题行}], "count": 集数}；没有集标题时 count 为 0。"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from headings import episode_starts
from textio import read_text, utf8_stdio

utf8_stdio()
if len(sys.argv) != 2:
    sys.exit(__doc__)
starts = episode_starts(read_text(sys.argv[1]).splitlines())
print(json.dumps({'episodes': starts, 'count': len(starts)}, ensure_ascii=False))
