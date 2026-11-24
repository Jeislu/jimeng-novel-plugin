#!/usr/bin/env python3
"""把拆解结果写回短剧项目目录（jimeng-drama 的布局），不调模型。

  project.py apply --project <剧目录> [--source <原文>] [--media photoreal|anime2d|cg3d]
      读 <剧目录>/.breakdown/ 下的 characters.md、scenes.md 和 episodes.md（导入路线才有），写回：
      - 给了 --source（导入路线）：story/.raw/E01.txt 等逐集原文切片；story/outline.md 骨架和 story/setting.md 人物小传（已有就不动）。
      - 两条路线都写：cast/<角色>.md、cast/<场景>.md 的「## 设定」，按 templates/ 的骨架建文件；造型、版本小节里的 << >> 留给 agent 填。
      已有的 cast 文件只追加出场集和新造型，外观白描、已写好的小节不改。
      最后打印一行 JSON：建了哪些、改了哪些、龙套名单、拆集表。
  project.py todo --project <剧目录> [--out 清单]
      列出 cast 文件里还要写的内容字段（主体段、身份标记、音色、易混差异、造型变化、场景锚点物、其他版本），写成一个 JSON 清单。
  project.py fill --project <剧目录> [--bodies 清单...]
      把填好的清单写进 cast 文件：风格句、固定段、变体前缀句、换光句由脚本拼，固定段一字不改；已写好的小节不动。
  project.py check --project <剧目录>
      查漏：没填的 << >>、主体段过短、造型清单或版本清单里有但还没写的小节。
  project.py canvas push|diff --project <剧目录> [--force] [--layout]
      本地 md 为准，和画布同步（要求剧目录已 jimeng-novel init）：
      - push：story/setting.md、outline.md、E01.md… 推成文本节点（key story/setting、story/outline、story/E01）；
        cast/ 里每个角色的每个造型推成角色卡（一个造型一张）（key cast/<角色>.<造型>，带外观白描、音色），每个场景的每个版本推成场景卡（一个版本一张）（cast/<场景>.<版本>，带描述）；
        建三个分组：剧本（设定、大纲、各集剧本）、角色、场景；有道具图再加「道具」；分镜按集分组，片段视频 E01/S01、分镜图 shots/E01.S01 和这一集的成片 E01/成片（排第一个）进「第1集分镜」；全剧合成 全剧/成片 进「全剧成片」。默认造型、母版的卡就叫资产名，其他造型、版本叫「名·版本」。
        每组用 jimeng-novel group arrange 一次排好并建组。从左到右排剧本、角色、场景和道具、各集分镜。场景和道具分组上下排列，同段分镜图和视频相邻。
        已经排好的组不再提交。手动挪过的节点下次推送会被挪回网格；--layout 把整体起点重新定到画布上别的东西右边。
        同一个 key 已有就更新；画布上这一项在上次推送之后被改过的，不覆盖，列进 conflicts（先 diff 合回本地再推；确认要覆盖加 --force）。
        卡上的图不在这里生成：在卡上用同一个 key 带 --model、--prompt-file 再 node update、node run。
      - diff：列出画布上在上次推送之后被改过、或画布上没有的项；改过的文本节点把画布上的正文存到 .canvas-pull/<key>.md，供合回本地。
      推送记录在 <剧目录>/.canvas-sync.json。
"""
from __future__ import annotations
import argparse
import tempfile
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from headings import episode_starts
from textio import read_text, write_text, utf8_stdio

HERE = Path(__file__).resolve().parent
TIME_LABEL = {'白天': '日', '夜晚': '夜', '黄昏': '黄昏', '清晨': '晨'}


def cn_number(s):
    if s.isdigit():
        return int(s)
    digits = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    total = part = 0
    for ch in s:
        if ch in digits:
            part = digits[ch]
        elif ch == '十':
            total += (part or 1) * 10
            part = 0
        elif ch == '百':
            total += (part or 1) * 100
            part = 0
    return total + part


def templates_dir():
    for d in (HERE.parent / 'templates', HERE.parent.parent / 'templates'):
        if d.is_dir():
            return d
    return None


def blocks(text, level):
    mark = '#' * level + ' '
    parts = re.split(rf'(?m)^(?={re.escape(mark)})', text)
    return [p for p in parts if p.startswith(mark)]


def field(block, key):
    m = re.search(rf'(?m)^- {re.escape(key)}：(.*)$', block)
    return m.group(1).strip() if m else ''


def episode_numbers(text):
    """「第1、3-5集」→ [1, 3, 4, 5]。"""
    nums = []
    m = re.search(r'第(.+?)集', text or '')
    for part in re.split(r'[、,，]', m.group(1)) if m else []:
        a, _, b = part.partition('-')
        if a.strip().isdigit():
            nums += list(range(int(a), int(b) + 1)) if b.strip().isdigit() else [int(a)]
    return sorted(set(nums))


def ep_label(nums, width):
    """[1,2,3,5] → E01–E03、E05。"""
    out, run = [], []
    for n in sorted(set(nums)):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(run)
        run = [n]
    if run:
        out.append(run)
    f = lambda n: f'E{n:0{width}d}'
    return '、'.join(f(r[0]) if len(r) == 1 else f'{f(r[0])}–{f(r[-1])}' for r in out)


def read_breakdown(bd):
    eps = []
    for b in blocks(read_text((bd / 'episodes.md')), 2) if (bd / 'episodes.md').is_file() else []:
        m = re.match(r'## 第(\d+)集[：:]\s*(.*)', b.split('\n', 1)[0])
        r = re.match(r'L(\d+)-L(\d+)', field(b, '原文'))
        eps.append({'n': int(m.group(1)), 'title': m.group(2).strip(), 'start': int(r.group(1)), 'end': int(r.group(2)),
                    'synopsis': field(b, '梗概'), 'hook': field(b, '钩子'), 'people': field(b, '角色'), 'places': field(b, '场景')})
    chars = []
    for b in blocks(read_text((bd / 'characters.md')), 2):
        head = re.split(r'(?m)^### ', b, maxsplit=1)[0]
        states = []
        for s in blocks(b, 3):
            states.append({'name': s.split('\n', 1)[0][4:].strip(), 'look': field(s, '外形'), 'age': field(s, '年龄段'),
                           'design': field(s, '外观设计'), 'episodes': episode_numbers(field(s, '出现'))})
        chars.append({'name': b.split('\n', 1)[0][3:].strip(), 'tier': field(head, '级别'), 'aliases': field(head, '别名'),
                      'intro': field(head, '简介'), 'gender': field(head, '性别'), 'personality': field(head, '性格'),
                      'bio': field(head, '小传'), 'states': states})
    scenes = []
    for b in blocks(read_text((bd / 'scenes.md')), 2):
        scenes.append({'name': b.split('\n', 1)[0][3:].strip(), 'aliases': field(b, '别名'), 'parent': field(b, '上级'),
                       'desc': field(b, '描述'), 'seen': field(b, '原文所见'), 'time': field(b, '时段'), 'shot': field(b, '空镜'), 'other': field(b, '其他时段'),
                       'episodes': episode_numbers(field(b, '出现'))})
    return eps, chars, scenes


def numbering(eps, source_lines):
    """集号：原文每集开头都有集标题、而且递增不重复时照原文；否则按顺序编。"""
    printed = {e['line']: e['number'] for e in episode_starts(source_lines)} if source_lines else {}
    found = []
    for e in eps:
        found.append(next((printed[i] for i in range(e['start'], min(e['end'], e['start'] + 3) + 1) if i in printed), None))
    if source_lines and all(found) and all(b > a for a, b in zip(found, found[1:])):
        return found
    return [e['n'] for e in eps]


def names_of(c):
    return [c['name']] + [a for a in re.split(r'[、，,]', c.get('aliases') or '') if a.strip() and a.strip() != '无']


def existing_file(cast, c):
    for n in names_of(c):
        for cand in (cast / f'{n}.md',):
            if cand.is_file():
                return cand
    for f in cast.glob('*.md'):
        head = read_text(f).split('\n', 3)
        m = re.search(r'别名[：:]\s*(.*)', '\n'.join(head))
        if m and c['name'] in re.split(r'[、，,；;\s]', m.group(1)):
            return f
    return None


def setting_block(rows):
    return '## 设定\n\n' + '\n'.join(f'- {k}：{v}' for k, v in rows) + '\n'


def from_template(name, rows, template, sections=None):
    """templates/ 的骨架：标题换成名字，「## 设定」换成填好的条目，其余小节原样留给 agent 填 << >>。"""
    if template is None or not template.is_file():
        return f'# {name}\n\n' + setting_block(rows)
    text = read_text(template)
    text = re.sub(r'(?m)^# .*$', f'# {name}', text, count=1)
    text = re.sub(r'(?ms)^## 设定\s*$.*?(?=^## )', setting_block(rows) + '\n', text, count=1)
    for old, new in (sections or {}).items():
        text = re.sub(rf'(?m)^## {re.escape(old)}(?=[\s·]|$)', f'## {new}', text)
    return text


def merge_existing(path, eps_label, new_variants):
    """已有 cast 文件：出场集取并集，造型清单、版本清单补上新的项；别的一字不改。"""
    text = read_text(path)
    changed = False
    m = re.search(r'(?m)^(- 出场集：)(.*)$', text)
    if m and eps_label and eps_label not in m.group(2):
        text = text[:m.start(2)] + (m.group(2) + '；' if m.group(2).strip() else '') + eps_label + text[m.end(2):]
        changed = True
    m = re.search(r'(?m)^(- (?:造型清单|版本清单)：)(.*)$', text)
    if m:
        have = {n for n, _ in list_items(m.group(2))}
        add = [v for v in new_variants if list_items(v)[0][0] not in have]
        if add:
            text = text[:m.end(2)] + '；' + '；'.join(add) + text[m.end(2):]
            changed = True
    if changed:
        write_text(path, text)
    return changed


def apply(project, source, media):
    bd = project / '.breakdown'
    eps, chars, scenes = read_breakdown(bd)
    src = read_text(source).splitlines() if source else []
    nums = numbering(eps, src)
    seen = nums or [n for c in chars for st in c['states'] for n in st['episodes']] + [n for x in scenes for n in x['episodes']]
    width = 3 if max(seen or [1]) >= 100 else 2
    renum = {e['n']: n for e, n in zip(eps, nums)}
    tpl = templates_dir()
    report = {'created': [], 'updated': [], 'kept': [], 'extras': [], 'episodes': []}
    story = project / 'story'
    story.mkdir(parents=True, exist_ok=True)

    for e, n in zip(eps, nums):
        report['episodes'].append({'episode': f'E{n:0{width}d}', 'lines': f'L{e["start"]}-L{e["end"]}', 'title': e['title']})
    if source:
        raw = story / '.raw'
        raw.mkdir(exist_ok=True)
        for e, n in zip(eps, nums):
            write_text((raw / f'E{n:0{width}d}.txt'), '\n'.join(src[e['start'] - 1:e['end']]) + '\n')
        outline = story / 'outline.md'
        if not outline.exists():
            out = ['# 分集大纲（由原文反抽，阶段和钩子评级待补）', '']
            for e, n in zip(eps, nums):
                out += [f'## E{n:0{width}d} {e["title"]}', f'- 梗概：{e["synopsis"]}', f'- 结尾钩子：{e["hook"]}',
                        f'- 出场：{e["people"]}；场景：{e["places"]}', '']
            write_text(outline, '\n'.join(out))
            report['created'].append(str(outline.relative_to(project)))
        setting = story / 'setting.md'
        bios = []
        for c in chars:
            if c['tier'] == '龙套':
                continue
            alias = '' if c['aliases'] in ('', '无') else f'（别名：{c["aliases"]}）'
            bios.append(f'- {c["name"]}{alias}：{c["bio"] or c["intro"]}' + (f'性格：{c["personality"]}。' if c['personality'] else ''))
        if not setting.exists():
            write_text(setting, '# 设定（由原文反抽，卖点、引擎、世界规则待补）\n\n## 人物小传\n\n' + '\n'.join(bios) + '\n')
            report['created'].append(str(setting.relative_to(project)))
        elif '人物小传' not in read_text(setting):
            write_text(setting, read_text(setting).rstrip() + '\n\n## 人物小传\n\n' + '\n'.join(bios) + '\n')
            report['updated'].append(str(setting.relative_to(project)))
        else:
            report['kept'].append(str(setting.relative_to(project)))

    cast = project / 'cast'
    cast.mkdir(exist_ok=True)
    ctpl = tpl / f'cast-character.{media}.md' if tpl else None
    stpl = tpl / f'cast-scene.{media}.md' if tpl else None
    for c in chars:
        if c['tier'] == '龙套':
            report['extras'].append(c['name'])
            continue
        main = c['states'][0] if c['states'] else {'name': '默认', 'design': '', 'look': '', 'age': '', 'episodes': []}
        all_eps = sorted({renum.get(n, n) for s in c['states'] for n in s['episodes']})
        variants = [f'{s["name"]}：基于默认；变化：{s["design"] or s["look"]}；{ep_label([renum.get(n, n) for n in s["episodes"]], width)}'
                    for s in c['states'][1:]]
        found = existing_file(cast, c)
        if found:
            (report['updated'] if merge_existing(found, ep_label(all_eps, width), variants) else report['kept']).append(str(found.relative_to(project)))
            continue
        rows = [('分级', c['tier']), ('别名', c['aliases'] or '无'), ('出场集', ep_label(all_eps, width)),
                ('性别', c['gender'] or '未知'), ('年龄段', main['age']), ('性格', c['personality']),
                ('外观白描', main['design'] or main['look']), ('身份标记', ''), ('音色', ''),
                ('易混差异', ''),
                ('造型清单', '；'.join([f'默认（{main["name"]}）'] + variants))]
        path = cast / f'{c["name"]}.md'
        write_text(path, from_template(c['name'], rows, ctpl))
        report['created'].append(str(path.relative_to(project)))
    for s in scenes:
        found = existing_file(cast, s)
        label = TIME_LABEL.get(s['time'], '日')
        others = [x.strip() for x in re.split(r'[；;]', s['other'] or '') if x.strip()]
        versions = [f'默认（{s["time"] or "白天"}，16:9 母版）']
        for o in others:
            t, _, shot = o.partition('：')
            versions.append(f'{TIME_LABEL.get(t.strip(), t.strip())}：{shot.strip()}' if shot else o)
        eps_label = ep_label([renum.get(n, n) for n in s['episodes']], width)
        if found:
            (report['updated'] if merge_existing(found, eps_label, versions[1:]) else report['kept']).append(str(found.relative_to(project)))
            continue
        rows = [('别名', s['aliases'] or '无'), ('上级', s['parent'] or '无'), ('出场集', eps_label),
                ('描述', s['shot'] or s['desc']), ('锚点物', ''), ('默认初始状态', ''), ('版本清单', '；'.join(versions))]
        path = cast / f'{s["name"]}.md'
        write_text(path, from_template(s['name'], rows, stpl))
        report['created'].append(str(path.relative_to(project)))
    print(json.dumps(report, ensure_ascii=False))


# ---- 造型、版本小节：todo 列出要写的字段，agent 填好后 fill 一次写进 cast 文件，check 查漏 ----
# 固定段、风格句、变体前缀句、换光句由这里拼（原文同 references/shots/prompt-anatomy.md），agent 只写内容字段。

PLACEHOLDER = re.compile(r'<<[^<>\n]*>>')
VARIANT = '{{%s}}是同一角色的基础形象，本图仍是同一个人。严格保留其骨相、五官比例、瞳色、肤色、体型与身份标记；只把以下部分换成当前形象：%s。上文没有提到的部分与基础形象一致。'
RELIGHT = '{{%s}}是同一空间的母版画面。保持空间结构、墙地材质、陈设种类与位置、取景方位完全一致；'
GUIDE = ('把每个空字符串、空列表填上内容，写完存成 JSON（可以分几个文件），再跑 project.py fill。'
         '「参考·」开头的是解析结果，只读，不用改。资产风格句、风格句从 README.md 复制。'
         '角色：族裔肤色、骨相照 asset-extraction.md 第 4 节；身份标记一条一个、没有就留空列表；音色照第 5 节；'
         '易混差异照 asset-extraction.md 第 3 节（和谁像、靠哪两三处拉开）；主体段照 character-sheet.md 第 4 节；造型.变化 只写和默认不同的部分（asset-extraction.md 2.3），跨年龄填 true；'
         '非人：说话的动物、机器人、精怪本相这类不是人形穿衣的角色填 true，fill 会换成正面、侧面、背面三视图模板（character-sheet.md 第 2 节）。'
         '场景：锚点物、默认初始状态照 asset-extraction.md 6.2，先看「参考·原文所见」；主体段照 scene-plate.md 第 2 节；'
         '版本.光照 写本版本的光源技术句，状态、观感没变就留空，版本.主体段 是本版本完整主体段（光和状态按本版本）。')


def split_sections(text):
    """[开头, '## 名\\n…', …]；开头是注释和标题。"""
    return re.split(r'(?m)^(?=## )', text)


def section_name(part):
    return part.split('\n', 1)[0][3:].strip()


def setting_value(text, key):
    m = re.search(rf'(?m)^- {re.escape(key)}：(.*)$', text)
    return m.group(1).strip() if m else None


def set_setting(text, key, value, after=None):
    """「## 设定」里这一行是空的才填；没有这一行就插在 after 那行后面。"""
    if not value:
        return text
    m = re.search(rf'(?m)^- {re.escape(key)}：(.*)$', text)
    if m:
        if m.group(1).strip() and not m.group(1).strip().startswith('（'):
            return text
        return text[:m.start(1)] + value + text[m.end(1):]
    m = re.search(rf'(?m)^- {re.escape(after)}：.*$', text) if after else None
    if m:
        return text[:m.end()] + f'\n- {key}：{value}' + text[m.end():]
    return text


def fixed_part(section):
    """造型、版本小节里从第一个【】固定段到结尾。"""
    m = re.search(r'(?m)^【', section)
    return section[m.start():] if m else ''


def fill_section(section, style, body, marks=None, name=None):
    lines = []
    for line in section.split('\n'):
        s = line.strip()
        if PLACEHOLDER.fullmatch(s) and '风格句' in s and style:
            line = style
        elif PLACEHOLDER.fullmatch(s) and '主体段' in s and body:
            line = body
        elif PLACEHOLDER.fullmatch(s) and s.startswith('<<身份标记') and marks:
            line = '\n'.join(marks)
        if name:
            line = line.replace('{{<<场景名>>}}', '{{%s}}' % name)
        lines.append(line)
    out = '\n'.join(lines)
    if marks is not None and not marks:
        out = re.sub(r'(?m)^【标志性身份特征[^\n]*\n<<身份标记[^\n]*>>\n[^\n]*(?:\n|$)', '', out)
    return out.rstrip('\n') + '\n\n'


LIST_TAIL = re.compile(r'^(基于|变化|出场|E\d)')


def list_items(value):
    """造型清单、版本清单「名字（说明）：说明；…」→ [(名字, 说明)]；「基于默认」「变化：…」「E03–E05」接在上一项后面。"""
    items = []
    for raw in re.split(r'[；;]', value or ''):
        x = raw.strip()
        if not x:
            continue
        m = re.match(r'([^：:（(]{1,12}?)\s*(?:[（(]([^）)]*)[）)])?\s*(?:[：:]\s*(.*))?$', x)
        if items and (LIST_TAIL.match(x) or not m):
            items[-1] = (items[-1][0], f'{items[-1][1]}；{x}'.strip('；'))
        elif m:
            items.append((m.group(1).strip(), (m.group(3) or m.group(2) or '').strip()))
    return items


def cast_kind(text):
    if setting_value(text, '外观白描') is not None or setting_value(text, '音色') is not None:
        return 'role'
    if setting_value(text, '锚点物') is not None or setting_value(text, '版本清单') is not None:
        return 'scene'
    return None


def cast_targets(project):
    """要写小节的角色、场景。以 cast 文件为准：造型、版本取 `## 设定` 里的造型清单、版本清单，
    没有剧本解析结果也能用（先做角色、后写剧本）。有解析结果时补上参考信息；解析里有、还没建文件的带 missing。"""
    cast = project / 'cast'
    bd = project / '.breakdown'
    chars, scenes = [], []
    if (bd / 'characters.md').is_file() and (bd / 'scenes.md').is_file():
        _, chars, scenes = read_breakdown(bd)
    chars = [c for c in chars if c['tier'] != '龙套']
    by_file = {}
    for e in chars + scenes:
        f = existing_file(cast, e) if cast.is_dir() else None
        if f:
            by_file.setdefault(f.resolve(), e)
        else:
            e['missing'] = True
    people, places = [], []
    for f in sorted(cast.glob('*.md')) if cast.is_dir() else []:
        text = read_text(f)
        kind = cast_kind(text)
        if not kind:
            continue
        m = re.search(r'(?m)^# (.+)$', text)
        e = by_file.get(f.resolve(), {})
        entry = {'name': m.group(1).strip() if m else f.stem, 'path': f}
        if kind == 'role':
            states = e.get('states') or []
            main = states[0] if states else {}
            listed = setting_value(text, '造型清单')
            variants = {n: (re.search(r'变化[：:]([^；]*)', rest) or [None, rest])[1].strip()
                        for n, rest in list_items(listed) if n != '默认'} if listed is not None else \
                       {s['name']: s['design'] or s['look'] for s in states[1:]}
            for s in states[1:]:
                if s['name'] in variants and not variants[s['name']]:
                    variants[s['name']] = s['design'] or s['look']
            people.append({**entry, 'variants': variants,
                           'gender': plain(setting_value(text, '性别')) or e.get('gender', ''),
                           'age': plain(setting_value(text, '年龄段')) or main.get('age', ''),
                           'look': plain(setting_value(text, '外观白描')) or main.get('design') or main.get('look', '')})
        else:
            listed = setting_value(text, '版本清单')
            if listed is not None:
                versions = {n: rest for n, rest in list_items(listed) if n != '默认'}
            else:
                versions = {}
                for o in [x.strip() for x in re.split(r'[；;]', e.get('other') or '') if x.strip()]:
                    tm, _, shot = o.partition('：')
                    versions[TIME_LABEL.get(tm.strip(), tm.strip())] = shot.strip()
            places.append({**entry, 'versions': versions,
                           'shot': plain(setting_value(text, '描述')) or e.get('shot') or e.get('desc', ''),
                           'seen': e.get('seen', '') if e.get('seen') != '无' else ''})
    missing = [{'name': e['name'], 'path': cast / f'{e["name"]}.md', 'missing': True} for e in chars + scenes if e.get('missing')]
    return people, places, missing


def todo(project, out):
    people, places, _ = cast_targets(project)
    plan = {'说明': GUIDE, '资产风格句': '', '风格句': '', '角色': {}, '场景': {}}
    for c in people:
        path = c['path']
        text = read_text(path)
        parts = {section_name(p): p for p in split_sections(text)[1:]}
        entry = {}
        for key in ('族裔肤色', '骨相', '音色', '易混差异'):
            v = setting_value(text, key)
            if not v or v.startswith('（'):
                entry[key] = ''
        default = parts.get('默认', '')
        if PLACEHOLDER.search(default):
            entry['主体段'] = ''
            if '【三视图】' not in default:
                entry['非人'] = False
        if not (setting_value(text, '身份标记') or '') or '<<身份标记' in default:
            entry['身份标记'] = []
        variants = {n: {'变化': '', '跨年龄': False, '参考·外观': ref}
                    for n, ref in c['variants'].items() if n not in parts}
        if variants:
            entry['造型'] = variants
        if entry:
            plan['角色'][c['name']] = {'参考·文件': str(path.relative_to(project)), '参考·外观白描': c['look'],
                                      '参考·性别': c['gender'], '参考·年龄段': c['age'], **entry}
    for s in places:
        path = s['path']
        text = read_text(path)
        parts = {section_name(p): p for p in split_sections(text)[1:]}
        entry = {}
        for key in ('锚点物', '默认初始状态'):
            if not (setting_value(text, key) or ''):
                entry[key] = ''
        if any(PLACEHOLDER.search(p) for p in parts.values()):
            entry['主体段'] = ''
        versions = {v: {'光照': '', '状态': '', '观感': '', '主体段': '', '参考·空镜': shot}
                    for v, shot in s['versions'].items() if v not in parts}
        if versions:
            entry['版本'] = versions
        if entry:
            plan['场景'][s['name']] = {'参考·文件': str(path.relative_to(project)), '参考·空镜': s['shot'],
                                      **({'参考·原文所见': s['seen']} if s['seen'] else {}), **entry}
    out.parent.mkdir(parents=True, exist_ok=True)
    write_text(out, json.dumps(plan, ensure_ascii=False, indent=1) + '\n')
    print(json.dumps({'todo': str(out), 'characters': len(plan['角色']), 'scenes': len(plan['场景'])}, ensure_ascii=False))


def creature_section(section):
    """人形模板的 ## 默认 换成同媒介的非人模板（正面、侧面、背面三视图）；认不出媒介返回 None。"""
    tpl = templates_dir()
    for m in ('photoreal', 'anime2d', 'cg3d'):
        human, creature = (tpl / f'cast-character.{m}.md', tpl / f'cast-creature.{m}.md') if tpl else (None, None)
        if not (human and human.is_file() and creature.is_file()):
            continue
        hs = {section_name(x): x for x in split_sections(read_text(human))[1:]}.get('默认', '')
        if fixed_part(hs).strip() and fixed_part(hs).strip() == fixed_part(section).strip():
            cs = {section_name(x): x for x in split_sections(read_text(creature))[1:]}['默认']
            return cs.rstrip('\n') + '\n\n'
    return None


def merged_bodies(files):
    plan = {'资产风格句': '', '风格句': '', '角色': {}, '场景': {}}
    for f in files:
        d = json.loads(read_text(Path(f)))
        for k in ('资产风格句', '风格句'):
            plan[k] = d.get(k) or plan[k]
        for k in ('角色', '场景'):
            for name, v in (d.get(k) or {}).items():
                plan[k].setdefault(name, {}).update(v)
    return plan


def fill(project, files):
    plan = merged_bodies(files)
    # 清单分几个文件写时，风格句只要有一个文件带着就行；一个都没有就先停，不写出缺风格句的小节
    lack = [k for k, part in (('资产风格句', '角色'), ('风格句', '场景')) if plan[part] and not plan[k].strip()]
    if lack:
        raise SystemExit(json.dumps({'ok': False, 'error': f'清单里没有{"、".join(lack)}：从 README.md 复制到清单顶层的同名字段（分几个文件写时至少一个文件带上），再跑 fill'}, ensure_ascii=False))
    people, places, _ = cast_targets(project)
    report = {'filled': [], 'missing': [], 'notes': []}
    for c in people:
        d = plan['角色'].get(c['name'])
        path = c['path']
        if d is None:
            continue
        text = read_text(path)
        marks = [m.strip() for m in d.get('身份标记') or [] if m.strip()] if '身份标记' in d else None
        text = set_setting(text, '族裔肤色', d.get('族裔肤色', ''), after='外观白描')
        text = set_setting(text, '骨相', d.get('骨相', ''), after='族裔肤色' if setting_value(text, '族裔肤色') is not None else '外观白描')
        text = set_setting(text, '身份标记', '；'.join(marks) if marks else ('无' if marks is not None else ''))
        text = set_setting(text, '音色', d.get('音色', ''))
        text = set_setting(text, '易混差异', d.get('易混差异', ''))
        parts = split_sections(text)
        out = [parts[0]]
        base = None
        for p in parts[1:]:
            if section_name(p) == '默认' and d.get('非人') and '【三视图】' not in p:
                swapped = creature_section(p) if PLACEHOLDER.search(p) else None
                if swapped:
                    p = swapped
                else:
                    report['notes'].append(f'{c["name"]}：## 默认 已写好或认不出媒介，没换成非人三视图；要换就把这一节换成 templates/cast-creature.<媒介>.md 的 ## 默认 再 fill')
            if section_name(p) == '默认' and PLACEHOLDER.search(p):
                p = fill_section(p, plan['资产风格句'], d.get('主体段', ''), marks)
            if section_name(p) == '默认':
                base = p
            out.append(p)
        have = {section_name(p) for p in parts[1:]}
        for name, v in (d.get('造型') or {}).items():
            change = (v.get('变化') if isinstance(v, dict) else v) or ''
            if name in have or not change or base is None or PLACEHOLDER.search(base):
                continue
            prefix = VARIANT % (c['name'], change.rstrip('。'))
            if isinstance(v, dict) and v.get('跨年龄'):
                # 年龄会改骨相、五官比例和体型，整句换掉，只留认人的部分
                prefix = prefix.replace('严格保留其骨相、五官比例、瞳色、肤色、体型与身份标记', '保留五官的辨识特征、瞳色、肤色与身份标记')
            out.append(f'## {name}\n\n{plan["资产风格句"]}\n\n{prefix}\n\n{fixed_part(base).rstrip()}\n\n')
        write_text(path, ''.join(out).rstrip('\n') + '\n')
        report['filled'].append(str(path.relative_to(project)))
    for s in places:
        d = plan['场景'].get(s['name'])
        path = s['path']
        if d is None:
            continue
        text = read_text(path)
        text = set_setting(text, '锚点物', d.get('锚点物', ''))
        text = set_setting(text, '默认初始状态', d.get('默认初始状态', ''))
        parts = split_sections(text)
        out = [parts[0]]
        base = None
        for p in parts[1:]:
            if PLACEHOLDER.search(p) and section_name(p) != '设定':
                p = fill_section(p, plan['风格句'], d.get('主体段', ''), name=s['name'])
            if base is None and section_name(p) != '设定':
                base = p  # 第一个版本小节是母版（## 默认）
            out.append(p)
        have = {section_name(p) for p in parts[1:]}
        for name, v in (d.get('版本') or {}).items():
            if name in have or not isinstance(v, dict) or not v.get('主体段') or base is None or PLACEHOLDER.search(base):
                continue
            light = RELIGHT % s['name']
            clauses = []
            if v.get('光照'):
                clauses.append(f'只把时段与光照改为：{v["光照"].rstrip("。")}，阴影、反光与窗外亮度随之改变')
            if v.get('状态'):
                clauses.append(f'状态改为：{v["状态"].rstrip("。")}')
            if v.get('观感'):
                clauses.append(f'整张画面的观感改为：{v["观感"].rstrip("。")}')
            light += '；'.join(clauses) + '。'
            out.append(f'## {name}\n\n{plan["风格句"]}\n\n{light}\n\n{v["主体段"]}\n\n{fixed_part(base).rstrip()}\n\n')
        write_text(path, ''.join(out).rstrip('\n') + '\n')
        report['filled'].append(str(path.relative_to(project)))
    for k, names in (('角色', [c['name'] for c in people]), ('场景', [s['name'] for s in places])):
        report['missing'] += [f'{k}：{n}' for n in names if n not in plan[k]]
    report['problems'] = check(project, quiet=True)
    print(json.dumps(report, ensure_ascii=False))


def body_of(section):
    """造型、版本小节里固定段之前的正文（去掉风格句）字数。"""
    head = section.split('\n', 1)[1] if '\n' in section else ''
    m = re.search(r'(?m)^【', head)
    paras = [p.strip() for p in (head[:m.start()] if m else head).split('\n\n') if p.strip()]
    return max((len(p) for p in paras[1:]), default=0)


def check(project, quiet=False):
    people, places, missing = cast_targets(project)
    problems = [{'file': str(e['path'].relative_to(project)), 'problem': '剧本解析里有，没有 cast 文件'} for e in missing]
    for kind, entities in (('角色', people), ('场景', places)):
        for e in entities:
            path = e['path']
            rel = str(path.relative_to(project))
            text = read_text(path)
            body_lines = text.split('\n')
            start = 1 if body_lines and body_lines[0].startswith('<!--') else 0
            left = sorted({m.group(0) for line in body_lines[start:] for m in PLACEHOLDER.finditer(line)})
            if left:
                problems.append({'file': rel, 'problem': '还有没填的占位：' + '、'.join(left)})
            parts = {section_name(p): p for p in split_sections(text)[1:]}
            for name, p in parts.items():
                if name != '设定' and fixed_part(p) and not PLACEHOLDER.search(p) and body_of(p) < 80:
                    problems.append({'file': rel, 'problem': f'## {name} 的主体段只有 {body_of(p)} 字'})
            wanted = list(e['variants'] if kind == '角色' else e['versions'])
            miss = [w for w in wanted if w not in parts]
            if miss:
                problems.append({'file': rel, 'problem': '清单里有、还没写小节：' + '、'.join(miss)})
    if not quiet:
        print(json.dumps({'problems': problems, 'ok': not problems}, ensure_ascii=False))
    return problems


# ---------- 画布同步 ----------
CLI = os.environ.get('JIMENG_NOVEL_BIN', 'jimeng-novel')
SYNC_FILE = '.canvas-sync.json'


def jn(project, *args):
    # Windows 上 npm 装的 CLI 是 jimeng-novel.cmd，直接按名字起进程找不到，先用 which 按 PATHEXT 解析成完整路径；
    # CLI 输出 UTF-8，不按系统编码解。
    exe = shutil.which(CLI) or CLI
    r = subprocess.run([exe, *args, '-j'], cwd=project, capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        env = json.loads(r.stdout)
    except ValueError:
        env = {'status': 'error', 'error': {'message': (r.stdout + r.stderr).strip()[-400:]}}
    env['ok'] = env.get('status') in ('ok', 'success')
    if not env['ok'] and not env.get('error'):
        env['error'] = {'message': (r.stderr or r.stdout).strip()[-400:]}
    return env


def plain(v):
    v = (v or '').strip()
    return '' if not v or v.startswith('（') or '<<' in v else v


def canvas_items(project):
    """本地要上画布的东西：文本节点、角色卡、场景卡，每项带 key、type、name、要同步的字段、分组。"""
    items = []
    story = project / 'story'
    for stem, name in (('setting', '故事设定'), ('outline', '分集大纲')):
        f = story / f'{stem}.md'
        if f.exists():
            items.append({'key': f'story/{stem}', 'type': 'text', 'fields': {'name': name, 'text': read_text(f).strip()}, 'group': '剧本'})
    eps = sorted((f for f in story.glob('E*.md') if re.fullmatch(r'E\d+', f.stem)), key=lambda f: int(f.stem[1:]))
    for f in eps:
        n = int(f.stem[1:])
        items.append({'key': f'story/{f.stem}', 'type': 'text', 'fields': {'name': f'第{n}集剧本', 'text': read_text(f).strip()}, 'group': '剧本'})
    for f in sorted((project / 'cast').glob('*.md')):
        text = read_text(f)
        kind = cast_kind(text)
        if not kind:
            continue
        m = re.search(r'(?m)^# (.+)$', text)
        title = m.group(1).strip() if m else f.stem
        first = None
        for part in split_sections(text)[1:]:
            sec = section_name(part)
            if sec == '设定':
                continue
            first = first or sec
            # 默认造型、母版就叫资产名本身；其他造型、版本才带后缀
            fields = {'name': title if sec == first else f'{title}·{sec}'}
            if kind == 'role':
                if plain(setting_value(text, '外观白描')):
                    fields['description'] = plain(setting_value(text, '外观白描'))
                if plain(setting_value(text, '音色')):
                    fields['voice'] = {'mode': 'description', 'description': plain(setting_value(text, '音色'))}
            else:
                if plain(setting_value(text, '描述')):
                    fields['description'] = plain(setting_value(text, '描述'))
                fields['viewName'] = fields['name']  # 场景卡标题显示的是 viewName
            items.append({'key': f'cast/{title}.{sec}', 'type': kind, 'fields': fields, 'group': '角色' if kind == 'role' else '场景'})
    return items


def managed(config, fields):
    """画布节点上由本工具管的那几个字段。"""
    out = {}
    for k in fields:
        v = config.get(k)
        if k == 'voice':
            v = {'mode': (v or {}).get('mode'), 'description': (v or {}).get('description')} if v else None
        out[k] = v.strip() if isinstance(v, str) else v
    return out


def digest(d):
    return hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def canvas_nodes(project):
    nodes, cursor = {}, None
    while True:
        env = jn(project, 'node', 'list', '--full', '--config', '--limit', '100', *(['--cursor', cursor] if cursor else []))
        if not env.get('ok'):
            raise SystemExit(json.dumps({'ok': False, 'error': env.get('error')}, ensure_ascii=False))
        data = env['data']
        for it in data.get('items') or []:
            if it.get('key'):
                nodes[it['key']] = it
        cursor = data.get('nextCursor')
        if not cursor:
            return nodes


def canvas_sync(project, mode, force=False, relayout=False):
    if not (project / '.jimeng/config.json').exists():
        raise SystemExit(json.dumps({'ok': False, 'error': '剧目录还没绑定画布：先在剧目录下 jimeng-novel init'}, ensure_ascii=False))
    state_path = project / SYNC_FILE
    state = json.loads(read_text(state_path)) if state_path.exists() else {}
    items = canvas_items(project)
    nodes, groups, doc = canvas_view(project)  # node list 一次带回每张卡的内容
    report = {'pushed': [], 'unchanged': [], 'conflicts': [], 'canvas_changed': [], 'missing': [], 'errors': []}
    batch, pending = [], {}
    for it in items:
        key, local = it['key'], it['fields']
        lh = digest(local)
        node = nodes.get(key)
        ch = None
        if node:
            if node.get('type') != it['type']:
                report['errors'].append({'key': key, 'error': f'画布上这个 key 是 {node.get("type")} 节点，不是 {it["type"]}'})
                continue
            canvas = managed(node.get('config') or {}, local)
            ch = digest(canvas)
        last = state.get(key)
        edited = node is not None and last is not None and ch != last
        if mode == 'diff':
            if node is None:
                report['missing'].append(key)
            elif edited or (last is None and ch != lh):
                entry = {'key': key, 'fields': [k for k in local if canvas.get(k) != local.get(k)]}
                if it['type'] == 'text' and canvas.get('text') is not None:
                    pulled = project / '.canvas-pull' / f'{key}.md'
                    pulled.parent.mkdir(parents=True, exist_ok=True)
                    write_text(pulled, canvas['text'] + '\n')
                    entry['canvas_copy'] = str(pulled.relative_to(project))
                elif canvas.get('description') is not None:
                    entry['canvas_description'] = canvas.get('description')
                report['canvas_changed'].append(entry)
            continue
        if node is not None and ch == lh:
            state[key] = lh
            report['unchanged'].append(key)
            continue
        if node is not None and lh == last and not force:  # 本地没改、画布上被改过：推送不动它，提示去 diff 合回本地；--force 照样用本地覆盖
            report['unchanged'].append(key)
            report['canvas_changed'].append({'key': key})
            continue
        if node is not None and not force and (edited or last is None):
            report['conflicts'].append({'key': key, 'why': '画布上这一项在上次推送之后被改过' if edited else '画布上已有这一项、内容和本地不同，且没有推送记录'})
            continue
        batch.append({'key': key, **({'type': it['type']} if node is None else {}), **local})
        pending[key] = lh
    if batch:
        # 新建和更新的卡一条 node batch 写完：读一次画布、一个事务，要么全写要么都不写
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump({'nodes': batch}, f, ensure_ascii=False)
        try:
            env = jn(project, 'node', 'batch', '--input-file', f.name)
        finally:
            os.unlink(f.name)
        if env.get('ok'):
            for n in (env.get('data') or {}).get('nodes') or []:
                state[n['key']] = pending[n['key']]
                report['pushed'].append(n['key'])
                if n.get('created'):
                    nodes[n['key']] = {'key': n['key'], 'nodeId': n.get('nodeId'), 'type': n.get('type')}
        else:
            report['errors'].append({'keys': sorted(pending), 'error': (env.get('error') or {}).get('message')})
    if mode == 'push':
        report['groups'] = canvas_groups(project, items, state, relayout, (nodes, groups, doc))
        write_text(state_path, json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True))
    out = {k: v for k, v in report.items() if v}
    if mode == 'push' and report['canvas_changed']:
        out['canvas_changed'] = [x['key'] for x in report['canvas_changed']]
        out['hint'] = 'canvas_changed 里的卡在画布上被改过、本地没改，这次没动；跑 canvas diff 看改了什么，合回本地 md；确认不要画布上的改动就加 --force'
    # 排版建组失败也算没完成（比如 CLI 超时），退出码非 0，重跑 push 会接着做
    out['ok'] = not report['conflicts'] and not report['errors'] and all(g.get('ok', True) for g in report.get('groups') or [])
    print(json.dumps(out, ensure_ascii=False))
    return out


GAP, FRAME_GAP = 40, 200  # 组内格子间距；组框与组框的间距
# 每组一行最多几个：剧本节点多（短剧常 60–80 集），一行 5 个；角色、场景、道具一行 3 个（一个场景的时段版本通常 1–3 个，正好一行）
ROW_SLOTS = {'剧本': 5}
ROW_SLOTS_DEFAULT = 3
# 每集分镜组一行 6 个：一集 60–90 秒通常 4–8 段，只有视频时一两行；有分镜图时图和视频成对，一行 3 段
SHOT_COLUMNS = 6
GROUP_COLUMNS = (('剧本',), ('角色',), ('场景', '道具'))  # 最右一列是各集分镜
# 每种节点的最小格子（有图的卡的尺寸），卡上出图变大后也不会挤到旁边；画布上更大的 CLI 按实际尺寸算
SLOT = {'text': (420, 360), 'scene': (420, 372), 'role': (362, 468)}
SHOT_KEY = re.compile(r'E(\d+)/(.+)|shots/E(\d+)\.(.+)')  # 片段视频 E01/S01、分镜图 shots/E01.S01
SHOT_GROUP = re.compile(r'第(\d+)集分镜')
FINAL_SEG = '成片'  # 一集的成片 E01/成片，排在这一集分镜组的第一个
FULL_KEY, FULL_GROUP = re.compile(r'全剧/.+'), '全剧成片'  # 全剧合成 全剧/成片，单独一组，排在各集分镜组上面


def natural(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def shot_groups(nodes):
    """分镜按集分组：{'第1集分镜': [keys]}，这一集的成片 E01/成片 排第一个，其余按段排；同一段的分镜图在前、视频在后。"""
    eps = {}
    for k in nodes:
        m = SHOT_KEY.fullmatch(k)
        if m:
            ep, seg = (int(m.group(1)), m.group(2)) if m.group(1) else (int(m.group(3)), m.group(4))
            eps.setdefault(ep, []).append((seg != FINAL_SEG, natural(seg), not k.startswith('shots/'), k))
    return {f'第{ep}集分镜': [k for *_, k in sorted(eps[ep])] for ep in sorted(eps)}


def chunks_of(group, keys):
    """组里哪些节点要挨着放：同一角色的造型、同一场景的版本、同一段的分镜图和视频；剧本、道具连成一串。"""
    chunks = {}
    for k in keys:
        if group in ('角色', '场景'):
            tag = k.rsplit('.', 1)[0]
        elif SHOT_GROUP.fullmatch(group):
            m = SHOT_KEY.fullmatch(k)
            tag = m.group(2) or m.group(4)
        else:
            tag = group
        chunks.setdefault(tag, []).append(k)
    return list(chunks.values())


def canvas_view(project):
    """画布现状：有 key 的节点、分组、文档里每个节点的位置和尺寸。"""
    nodes = canvas_nodes(project)
    env = jn(project, 'canvas', 'get', '--full')
    if not env.get('ok'):
        raise SystemExit(json.dumps({'ok': False, 'error': env.get('error')}, ensure_ascii=False))
    data = env.get('data') or {}
    return nodes, data.get('groups') or [], (data.get('document') or {}).get('nodes') or {}


def arrange_group(project, name, keys, types, group_id, x, y):
    is_shots = name == FULL_GROUP or bool(SHOT_GROUP.fullmatch(name))
    cells = [SLOT[t] for t in {types.get(k) for k in keys} if t in SLOT]
    columns = SHOT_COLUMNS if is_shots else ROW_SLOTS.get(name, ROW_SLOTS_DEFAULT)
    spec = {'name': name, 'columns': columns, 'origin': {'x': x, 'y': y}, 'gap': GAP,
            'nodes': [c if len(c) > 1 else c[0] for c in chunks_of(name, keys)]}
    if cells:
        spec['cellWidth'], spec['cellHeight'] = max(w for w, _ in cells), max(h for _, h in cells)
    if group_id:
        spec['groupId'] = group_id
    # JSON 走文件：放在命令行里经过 Windows 的 .cmd 包装时，引号会被 cmd.exe 吃掉
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(spec, f, ensure_ascii=False)
    try:
        return jn(project, 'group', 'arrange', '--input-file', f.name)
    finally:
        os.unlink(f.name)


def canvas_groups(project, items, state, relayout=False, view=None):
    """分组：剧本（设定、大纲、各集剧本）、角色、场景；有道具图再加「道具」；分镜按集一组（「第1集分镜」：成片 E01/成片 排第一个，再是片段视频 E01/S01、分镜图 shots/E01.S01）；全剧合成 全剧/成片 进「全剧成片」。
    每组一条 group arrange。场景和道具共用角色右边的一列，各集分镜与全剧成片在最右一列。同一角色的造型、同一场景的版本、同一段的分镜图和视频挨着，放不下整串换行。
    排版起点第一次排时定下（画布上别的东西右边），记在推送记录里，--layout 重新定。"""
    nodes, groups, doc = view or canvas_view(project)  # 推送开头读到的画布；这次新建的卡已补进 nodes
    managed_keys = {it['key'] for it in items}
    types = {key: node.get('type') for key, node in nodes.items()}
    types.update({it['key']: it['type'] for it in items})
    wanted = {}
    for it in items:
        if it['key'] in nodes:
            wanted.setdefault(it['group'], []).append(it['key'])
    group_names = {g['groupId']: g.get('name') for g in groups}
    card_groups = {'role': '角色', 'scene': '场景'}
    for key, node in sorted(nodes.items()):
        group = card_groups.get(node.get('type'))
        if not group or key in managed_keys or not re.fullmatch(r'cast/[^/]+\.[^/]+', key):
            continue
        # 续作或直接在画布建的卡可以没有对应 md。只整理散卡和本组已有的卡，保留用户的其他分组。
        card = doc.get(node.get('nodeId'))
        if card and (not card.get('parentId') or group_names.get(card['parentId']) == group):
            wanted.setdefault(group, []).append(key)
    props = sorted(k for k, n in nodes.items() if k.startswith('cast/') and k not in managed_keys and n.get('type') == 'image')
    if props:
        wanted['道具'] = props
    full = sorted(k for k in nodes if FULL_KEY.fullmatch(k))
    shot_wanted = ({FULL_GROUP: full} if full else {}) | shot_groups(nodes)
    wanted.update(shot_wanted)
    ours = {k for keys in wanted.values() for k in keys}
    ours_ids = {nodes[k].get('nodeId') for k in ours if k in nodes}
    # 我们的分组：名字是这几组之一（分镜删光后留下的空「第N集分镜」也算），成员都是我们的节点
    mine = [g for g in groups if (g.get('name') in wanted or SHOT_GROUP.fullmatch(g.get('name') or ''))
            and set(g.get('members') or []) <= ours | ours_ids]
    done, keep = [], {}
    for g in mine:
        name = g.get('name')
        if name in wanted and name not in keep:
            keep[name] = g['groupId']
        elif not g.get('members'):  # 空分组 group arrange 管不到；有成员的旧分组，成员被移走后 CLI 自动删
            env = jn(project, 'group', 'dissolve', '--group-id', g['groupId'])
            done.append({'group': name, 'action': 'dissolve', 'ok': env.get('ok')})
    if relayout or 'layout_origin' not in state:
        mine_ids = {g['groupId'] for g in mine}
        others = [v for v in doc.values() if not v.get('parentId') and v.get('id') not in ours_ids | mine_ids]
        state['layout_origin'] = [max((v.get('x', 0) + v.get('w', 0) for v in others), default=-FRAME_GAP) + FRAME_GAP, 0]
    x, top = state['layout_origin']
    for group_names_in_column in (*GROUP_COLUMNS, tuple(shot_wanted)):
        column = [name for name in group_names_in_column if name in wanted]
        if not column:
            continue
        right, y = x, top
        for name in column:
            keys = wanted[name]
            if name not in keep and name in group_names.values():
                done.append({'group': name, 'action': 'arrange', 'ok': False, 'error': '同名分组含有其他节点，请先区分组名'})
                return done
            env = arrange_group(project, name, keys, types, keep.get(name), x, y)
            if not env.get('ok'):
                # 下一组接在这一组的框后面，这组没排成就停；重跑 push 会接着排
                done.append({'group': name, 'action': 'arrange', 'ok': False, 'error': (env.get('error') or {}).get('message')})
                return done
            d = env.get('data') or {}
            if d.get('changed'):
                done.append({'group': name, 'action': 'create' if d.get('created') else 'arrange', 'keys': len(keys), 'ok': True})
            f = d['frame']
            right = max(right, f['x'] + f['width'])
            y = f['y'] + f['height'] + FRAME_GAP
        x = right + FRAME_GAP
    return done


def main():
    utf8_stdio()
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=('apply', 'todo', 'fill', 'check', 'canvas'))
    p.add_argument('action', nargs='?', choices=('push', 'diff'), help='canvas：push 或 diff')
    p.add_argument('--force', action='store_true', help='canvas push：画布上改过的也覆盖')
    p.add_argument('--layout', action='store_true', help='canvas push：把剧本、角色、场景重新排整齐（会覆盖手动挪过的位置）')
    p.add_argument('--project', type=Path, required=True)
    p.add_argument('--source', type=Path)
    p.add_argument('--media', choices=('photoreal', 'anime2d', 'cg3d'), default='photoreal')
    p.add_argument('--out', type=Path, help='todo：清单写到哪，默认 <剧目录>/.breakdown/cast-todo.json')
    p.add_argument('--bodies', type=Path, nargs='+', help='fill：填好的清单，可以几个文件，默认 <剧目录>/.breakdown/cast-todo.json')
    a = p.parse_args()
    if a.command == 'apply':
        apply(a.project, a.source, a.media)
    elif a.command == 'todo':
        todo(a.project, a.out or a.project / '.breakdown/cast-todo.json')
    elif a.command == 'fill':
        fill(a.project, a.bodies or [a.project / '.breakdown/cast-todo.json'])
    elif a.command == 'canvas':
        if not a.action:
            p.error('canvas 要跟 push 或 diff')
        raise SystemExit(0 if canvas_sync(a.project, a.action, a.force, a.layout)['ok'] else 1)
    else:
        check(a.project)


if __name__ == '__main__':
    main()
