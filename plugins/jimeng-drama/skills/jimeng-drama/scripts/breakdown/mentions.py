#!/usr/bin/env python3
"""列出原文里提到某个人或某个地点的所有行（带行号）。
用法：python3 mentions.py <原文> 名字 [别名 ...] [--skip N]
  <原文> 是一个文件（输出 L12），或者自己写好的分集剧本目录（里面是 E01.md、E02.md……，输出 E01:L12）。

写小传、外观、空镜之前，用它把这个人或地点在全剧的出场翻一遍，补上读的时候没记下的事实。
只做字面检索：任一名字或别名出现在这一行就列出，不判断是不是同一个人。
输出过长会被工具截断，所以一次最多列约 1 万字；没列完时最后一行会提示用 --skip 接着看。"""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from textio import read_text, utf8_stdio

LIMIT = 10000


def numbered(path):
    path = Path(path)
    if not path.is_dir():
        return [(f'L{i}', l) for i, l in enumerate(read_text(path).splitlines(), 1)]
    files = sorted(path.glob('*.md'), key=lambda f: (not re.fullmatch(r'E\d+', f.stem), f.stem))
    return [(f'{f.stem}:L{i}', l) for f in files for i, l in enumerate(read_text(f).splitlines(), 1)]


def main(argv):
    utf8_stdio()
    args = [a for a in argv if not a.startswith('--')]
    skip = int(argv[argv.index('--skip') + 1]) if '--skip' in argv else 0
    if '--skip' in argv:
        args.remove(argv[argv.index('--skip') + 1])
    if len(args) < 2:
        sys.exit(__doc__)
    names = [n for n in args[1:] if n.strip()]
    hits = [(k, l.strip()) for k, l in numbered(args[0]) if any(n in l for n in names)]
    out, size, shown = [], 0, 0
    for k, l in hits[skip:]:
        row = f'{k}\t{l}'
        if size + len(row) > LIMIT and shown:
            break
        out.append(row)
        size += len(row)
        shown += 1
    print(f'# {"、".join(names)}：共 {len(hits)} 行提到，下面是第 {skip + 1}–{skip + shown} 行')
    print('\n'.join(out))
    if skip + shown < len(hits):
        print(f'# 还有 {len(hits) - skip - shown} 行没列，加 --skip {skip + shown} 接着看')


if __name__ == '__main__':
    main(sys.argv[1:])
