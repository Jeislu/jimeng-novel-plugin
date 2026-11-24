"""原文里哪几行是集标题。

规则：
1. 认「第N集」和 EP01 / E01 / Episode 1 这类写法，标题前可以有 #、**（加粗）或【。
2. 「第N集」后面直接接字（没有空格、冒号等隔开）时，只认 12 字以内、不带句读的短题（「第1集分镜表」），
   接长句的是正文（「第三集播完那天，……」）。隔开的后面再长也算标题（标题后常接一整句梗概）。
3. 同一个集号连着出现：中间没有正文（重复写了一遍标题），或者前后集号是连着的（「第14集（续）」），
   都并进前一集；前后缺号的（12、14、14，13 写成了 14）是写错了集号，照样算一集。
4. 集号按出现顺序切成递增的组。集号回退的地方是新的一组：开头的目录、大纲，
   后面的分镜表、修订记录、附录。只取一组当正文的集，其余各组的行归到相邻的集里。
   - 后一组集号接着往上走、或者只是前一组最后一个集号写大了（中间写错了一个集号），
     或者两组之间有「第二季」这类标题，两组连起来算。
   - 每集正文很短（目录、一行梗概的大纲）而别的组每集正文长得多的，不选。
   - 剩下的取集数最多的一组，一样多取前面的。
"""
import re
from statistics import median

NUM = r'[0-9０-９零〇一二三四五六七八九十百千两]+'
ZH = re.compile(r'^\s*(?:#{1,6}\s*)?(?:\*{1,2}\s*)?[【\[［]?\s*第\s*(' + NUM + r')\s*集(?:\s*[】\]］])?(.*)$')
EP = re.compile(r'^\s*(?:#{1,6}\s*)?(?:\*{1,2}\s*)?[【\[［]?\s*(?:Episode|EPISODE|EP|Ep|ep|E)\s*[-_.#]?\s*([0-9０-９]{1,4})(?![0-9０-９])(?:\s*[】\]］])?(.*)$')
SEASON = re.compile(r'^\s*(?:#{1,6}\s*)?第\s*' + NUM + r'\s*[季部卷]\s*\S{0,20}\s*$')
SEP = ' \t　:：、.．·-—–|｜,，(（[【《「*'
SENTENCE = re.compile(r'[，。！？；…,!?;]')
LIST_CHARS = 400   # 每集正文中位数短于这个字数、别的组又长 3 倍以上的组，当目录或大纲


def parse_number(s):
    try:
        return int(s)
    except ValueError:
        digits = dict(zip('零〇一二三四五六七八九两', [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 2]))
        total = current = 0
        for c in s:
            if c in digits:
                current = digits[c]
            elif c in '十百千':
                total += (current or 1) * {'十': 10, '百': 100, '千': 1000}[c]
                current = 0
            else:
                raise ValueError('bad number ' + s)
        return total + current


def _candidates(lines, pattern):
    out = []
    for i, line in enumerate(lines, 1):
        m = pattern.match(line)
        if not m:
            continue
        rest = m[2]
        if pattern is EP and (re.match(r'[A-Za-z0-9０-９]', rest) or re.match(r'\s*[-_.]\s*[0-9]', rest)):
            continue  # EPx 后面紧跟字母数字的是别的编号，EP1-2 是场次号
        if rest and rest[0] not in SEP and not rest[0].isspace() and (len(rest.strip()) > 12 or SENTENCE.search(rest)):
            continue
        out.append((i, parse_number(m[1]), line.strip().lstrip('#').strip()))
    return out


def _body(lines, a, b):
    """第 a 行之后、第 b 行之前的非空字数（行号从 1 起）。"""
    return sum(len(l.strip()) for l in lines[a:b - 1])


def _select(lines, cands):
    kept = []  # (行号, 集号, 标题, 排序用的集号)
    for k, c in enumerate(cands):
        if kept and c[1] == kept[-1][1]:
            before = kept[-2][1] if len(kept) > 1 else None
            after = cands[k + 1][1] if k + 1 < len(cands) else None
            typo = (before is not None and before < c[1] - 1) or (after is not None and after > c[1] + 1)
            if typo and _body(lines, kept[-1][0], c[0]):
                kept.append((*c, kept[-1][3] + .5))
            continue
        kept.append((*c, c[1]))
    if not kept:
        return []
    body = {c[0]: _body(lines, c[0], (kept[k + 1][0] if k + 1 < len(kept) else len(lines) + 1)) for k, c in enumerate(kept)}
    groups = [[kept[0]]]
    for c in kept[1:]:
        if c[3] > groups[-1][-1][3]:
            groups[-1].append(c)
        else:
            groups.append([c])
    merged = [groups[0]]
    for g in groups[1:]:
        prev = merged[-1]
        between = lines[prev[-1][0]:g[0][0] - 1]
        # 后一组接着往上走，或者只是前一组最后一个集号写大了（5、10、7、8…：6 写成了 10）
        onward = g[0][3] > prev[0][3] and (max(c[3] for c in g) > max(c[3] for c in prev) or (len(prev) > 1 and g[0][3] > prev[-2][3]))
        if onward or any(SEASON.match(l) for l in between):
            prev.extend(g)
        else:
            merged.append(g)
    med = [median(body[c[0]] for c in g) for g in merged]

    def list_like(k):
        return med[k] < LIST_CHARS and any(j != k and len(merged[j]) >= 2 and med[j] >= 3 * max(med[k], 1) for j in range(len(merged)))
    eligible = [k for k in range(len(merged)) if not list_like(k)] or list(range(len(merged)))
    best = max(eligible, key=lambda k: (len(merged[k]), -k))
    return [c[:3] for c in merged[best]]


def episode_starts(lines):
    """返回 [{'line': 行号, 'number': 集号, 'title': 标题行}]，行号从 1 起；没有集标题时返回 []。"""
    zh = _select(lines, _candidates(lines, ZH))
    ep = _select(lines, _candidates(lines, EP))
    chosen = zh if len(zh) >= len(ep) else ep
    return [{'line': i, 'number': n, 'title': t} for i, n, t in chosen]
