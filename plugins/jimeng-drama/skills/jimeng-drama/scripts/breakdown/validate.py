#!/usr/bin/env python3
"""校验三个 md：逐行格式、分集、引用（结构），以及角色设计和场景空镜的硬性要求（设计）。"""
import argparse
import json
from pathlib import Path
import re
import sys
from textio import read_text, utf8_stdio


def sections(path,pattern):
    text=read_text(path)
    matches=list(re.finditer(pattern,text,re.M))
    return [(m, text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]) for i,m in enumerate(matches)]


def field(body,key):
    m=re.search(r'^- '+re.escape(key)+r'：[ \t]*([^\n]*)$',body,re.M)
    if not m:return None
    value=m[1].strip()
    # 只有 **、__、` 这类 Markdown 符号的字段算空。
    return value if re.sub(r'[\s*_`~]+','',value) else ''


def items(s):
    return [] if s in ('无','',None) else [v.strip() for v in s.split('、') if v.strip()]


class Source:
    """原文：一个文件（行号写 L12），或者一个目录（自己写好的剧本，每集一个 E01.md，行号写 E01:L12）。"""
    def __init__(self,path):
        self.dir=path.is_dir()
        if self.dir:
            self.files={f.stem:read_text(f).splitlines() for f in sorted(path.glob('*.md'))}
            self.episodes=sorted(int(m[1]) for k in self.files if (m:=re.fullmatch(r'E(\d+)',k)))
            if not self.episodes:raise ValueError(f'{path} 里没有 E01.md 这样的分集文件')
            self.lines=[l for k in self.files for l in self.files[k]]
        else:
            self.lines=read_text(path).splitlines()

    def refs(self,text):
        """text 里有效的原文行号。"""
        if not self.dir:
            return {int(x) for x in re.findall(r'L(\d+)',text or '') if 1<=int(x)<=len(self.lines)}
        return {(k,int(n)) for k,n in re.findall(r'([^\s、，,；;（(：:]+)[:：]L(\d+)',text or '') if k in self.files and 1<=int(n)<=len(self.files[k])}

    def ref_hint(self):
        return '写成 E03:L12' if self.dir else '写成 L12'


def check_story_episodes(out,src):
    """输入是分好集的目录时不交 episodes.md，只查出现集是不是都有对应的分集文件。"""
    errors=[];have=set(src.episodes)
    for fname in ('characters.md','scenes.md'):
        for m,body in sections(out/fname,r'^## ([^\n]+)\n'):
            for _,v in re.findall(r'^- (出现)：(.*)$',body,re.M):
                bad=sorted(episode_set(v)-have)
                if bad:errors.append(f'「{m[1].strip()}」的出现集 {bad} 没有对应的分集文件')
    return errors


def validate(input_path,out,episodes=None):
    errors=[]
    src=Source(input_path);lines=src.lines
    characters={};scenes=set()
    for m,body in sections(out/'characters.md',r'^## ([^\n]+)\n'):
        name=m[1].strip()
        if name in characters:errors.append('duplicate character '+name)
        states=re.findall(r'^### ([^\n]+)$',body,re.M)
        characters[name]=set(states)
        errors+=name_errors('角色',name)+[e for s in states for e in name_errors(f'角色「{name}」的状态',s.strip())]
        if not states:errors.append('no state '+name)
        for f in ('级别','别名','简介'):
            if not field(body,f):errors.append('missing character field '+f+': '+name)
        if field(body,'级别') not in ('主角','重要配角','配角','龙套'):errors.append('bad tier '+name)
        if len(states)> (4 if field(body,'级别')=='主角' else 2):errors.append('too many states '+name)
        for sm,sbody in sections_text(body,r'^### ([^\n]+)\n'):
            for f in ('外形','出现'):
                if not field(sbody,f):errors.append('missing state field '+f+': '+name)
    for m,body in sections(out/'scenes.md',r'^## ([^\n]+)\n'):
        name=m[1].strip()
        if name in scenes:errors.append('duplicate scene '+name)
        scenes.add(name)
        errors+=name_errors('场景',name)
        for f in ('别名','描述','出现'):
            if not field(body,f):errors.append('missing scene field '+f+': '+name)
    lengths=[]
    if src.dir:
        errors+=check_story_episodes(out,src)
        n_eps=len(src.episodes)
    else:
        eps=sections(out/'episodes.md',r'^## 第(\d+)集：([^\n]+)\n')
        n_eps=len(eps)
        if not eps:errors.append('no episodes')
        if episodes is not None and len(eps)!=episodes:errors.append('requested episode count mismatch')
        last=0;numbers=[]
        for m,body in eps:
            number=int(m[1]);numbers.append(number)
            for f in ('原文','梗概','钩子','角色','场景'):
                if not field(body,f):errors.append(f'episode {number} missing {f}')
            sentence_count=len(re.findall(r'[。！？]',field(body,'梗概') or ''))
            if not 2<=sentence_count<=4:errors.append('synopsis must have 2..4 sentences '+str(number))
            anchor=re.fullmatch(r'L(\d+)-L(\d+)',field(body,'原文') or '')
            if not anchor:errors.append('bad range '+str(number));continue
            start,end=map(int,anchor.groups())
            if start!=last+1 or end<start or end>len(lines):errors.append('nonpartition range '+str(number))
            last=end
            lengths.append(sum(len(l) for l in lines[start-1:end]))
            for x in items(field(body,'角色')):
                c=re.fullmatch(r'(.+?)(?:\[([^\]]+)\])?',x)
                if not c or c[1] not in characters:errors.append('unknown character '+x)
                elif c[2] and c[2] not in characters[c[1]]:errors.append('unknown state '+x)
            for x in items(field(body,'场景')):
                if x not in scenes:errors.append('unknown scene '+x)
        if last!=len(lines):errors.append('not cover entire input')
        # 原文有集标题时，集号和每集起点照原文。
        from headings import episode_starts
        original=[(e['number'],e['line']) for e in episode_starts(lines)]
        if original:
            expected=[(n,1 if j==0 else start) for j,(n,start) in enumerate(original)]
            actual=[(int(m[1]),int(re.search(r'L(\d+)-',field(b,'原文') or 'L0-')[1])) for m,b in eps]
            if expected!=actual:errors.append('original episode boundaries/numbers changed')
        elif numbers!=list(range(1,len(eps)+1)):errors.append('episode numbers not sequential')
        if not original and any(n>8000 for n in lengths):errors.append('episode exceeds 8000 characters')
    errors+=format_errors(out,('characters.md','scenes.md') if src.dir else ('episodes.md','characters.md','scenes.md'))
    errors+=tier_errors(out)
    d=design_errors(src,out)
    errors+=d
    return {'valid':not errors,'errors':errors,'notes':tier_notes(src,out),'design_errors':len(d),'episodes':n_eps,'characters':len(characters),'scenes':len(scenes),'episode_lengths':lengths}

DESIGN_TIERS=('主角','重要配角','配角')
NOTE_MENTIONS=12
GENDERS=('男','女','未知')
AGE_BANDS=('幼儿','儿童','少年','青年','中年','中老年','老年')
TIMES=('清晨','白天','黄昏','夜晚')
BIO_LEN={'主角':(150,300),'重要配角':(150,300),'配角':(60,150)}
BIO_LINES={'主角':3,'重要配角':3,'配角':2}
SLACK=1.2  # 字数放宽一点，免得为差几个字反复改
FORBIDDEN=re.compile(r'背景|画风|写实|3D|三维|二次元|厚涂|赛璐璐|插画风|手持|手里(?:拿|握|捧|提)|手中(?:拿|握|捧|提)|拿着|捧着|提着|握着|流泪|含泪|泪痕|眼泪|汗水|汗珠|汗湿|满头大汗|大笑|张嘴|路人脸')
STYLE_WORDS=('画风','写实','3D','三维','二次元','厚涂','赛璐璐','插画风')
SCAR=re.compile(r'疤|伤痕|伤口|旧伤|刀痕|烫伤|烧伤|淤青|瘀青|独眼|跛|木腿|假腿|断臂|断指')
PEOPLE_WORDS=re.compile(r'人物|人影|身影|众人|(?<![没无])有人')
PLACEHOLDER_WORDS=re.compile(r'待确认|待确定|尚待|待定|待补|待核|暂定|暂作|暂缺|未确定|不详|以原文为准|视.{0,8}而定')
BODY_WORDS=re.compile(r'脸|眉|眼|鼻|唇|嘴|颧|下颌|身量|身形|体态|体形|体型|身材|个子|肩|痕迹|磨|旧')


KEY_BAD=re.compile(r'[\s./\\:*?"<>|\x00-\x1f]')
# Windows 不许用作文件名的设备名（带扩展名也不行，CON.md 照样建不出来），不分大小写
WIN_RESERVED={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}


def name_errors(kind,name,foreign_hint=True):
    """名字会成为 cast/ 的文件名和画布节点 key（cast/<名>.<造型>）：CLI 不收带空白的 key，「.」「/」会把 key 拆错；
    「\ : * ? " < > |」和 CON、NUL 这类设备名在 Windows 上建不出文件（全角的「：」「？」可以用）。"""
    bad=sorted({'空格' if c.isspace() else ('控制字符' if ord(c)<32 else f'「{c}」') for c in KEY_BAD.findall(name)})
    if name.strip().upper() in WIN_RESERVED:
        return [f'{kind}名「{name}」是 Windows 的设备名，在 Windows 上建不出这个文件：换个叫法，原名写进别名']
    if not bad:return []
    hint='。外文名用原文最常用的单个称呼（名或姓），全名写进别名' if foreign_hint else ''
    return [f'{kind}名「{name}」里有{"、".join(bad)}：名字会用作文件名和画布节点 key，不能有空格、「.」「/」「\\」「:」「*」「?」「"」「<」「>」「|」（全角的可以）{hint}']


def size(text):
    return len(re.sub(r'\s','',text or ''))


def within(n,lo,hi):
    return lo/SLACK<=n<=hi*SLACK


def episode_set(text):
    """「第1、2、5集」「第3-6集」→ 集号集合。"""
    out=set()
    for a,b in re.findall(r'(\d+)\s*(?:[-–—~至到]\s*(\d+))?',text or ''):
        a=int(a);b=int(b) if b else a
        out|=set(range(a,min(b,a+500)+1))
    return out


def format_errors(out,files=('episodes.md','characters.md','scenes.md')):
    """逐行查格式：# 只在开头，条目用 ##、角色状态用 ###，其余每行都是「- 字段：内容」或缩进的续行，字段不重复。
    说明、待确认、备注这类内容不写进这三个文件（写进最后的回复）；下游按字段逐行读，多出来的行会被当成格式错误。"""
    errors=[]
    for fname in files:
        path=out/fname
        if not path.is_file():continue
        entry=None;target=None;field_open=False;fields=set()
        for ln,raw in enumerate(read_text(path).splitlines(),1):
            line=raw.strip()
            if not line or line.startswith('<!--'):continue
            h=re.match(r'^(#{1,6})\s*(.*?)\s*#*$',line)
            if h:
                depth=len(h[1]);field_open=False
                if depth==1:
                    if entry:errors.append(f'{fname} 第 {ln} 行：「#」标题只能放在文件开头；说明、待确认这类内容写进最后的回复，不写进这个文件')
                    continue
                if depth==2:
                    entry=target=h[2];fields=set()
                    if fname=='episodes.md' and not re.fullmatch(r'第\d+集：.+',h[2]):errors.append(f'{fname} 第 {ln} 行：分集标题写成「## 第1集：标题」')
                    continue
                if depth==3 and fname=='characters.md' and entry:
                    target=entry+'/'+h[2];fields=set();continue
                errors.append(f'{fname} 第 {ln} 行：标题层级错误；条目用 ##，角色状态用 ###');continue
            body=re.sub(r'^(?:[-+*•●▪·]|\d+[.)、])\s*','',line).replace('**','')
            m=re.match(r'^([^:：]{1,12})\s*[:：]\s*(.*)$',body)
            if m:
                if target is None:errors.append(f'{fname} 第 {ln} 行：「{m[1].strip()}」前面没有 ## 条目；说明、备注不写进这个文件');continue
                key=m[1].strip()
                if key in fields:errors.append(f'{fname} 第 {ln} 行：「{target}」重复字段「{key}」，合并成一行')
                fields.add(key);field_open=True
            elif target is not None and field_open and raw[:1].isspace():
                continue
            else:
                errors.append(f'{fname} 第 {ln} 行：无法解析「{line[:30]}」；每行写成「- 字段：内容」，说明、备注不写进这个文件')
    return errors


def tier_errors(out):
    """级别和简介的硬性检查：出场三集以上的龙套、多人一字不差的简介。"""
    errors=[];intros={}
    for m,body in sections(out/'characters.md',r'^## ([^\n]+)\n'):
        name=m[1].strip();head=body.split('\n### ',1)[0]
        intro=field(head,'简介') or ''
        if intro:intros.setdefault(re.sub(r'\s','',intro),[]).append(name)
        if field(head,'级别')!='龙套':continue
        eps=set()
        for _,sb in sections_text(body,r'^### ([^\n]+)\n'):eps|=episode_set(field(sb,'出现'))
        if len(eps)>=3 and '职能称谓' not in intro:
            errors.append(f'角色「{name}」是龙套但出现了 {len(eps)} 集：按 extract.md，出场三集以上、不只是职能称谓的人至少是配角；这个人确实只有职能称谓（侍卫、管事这类）的，在简介里写明「只有职能称谓」')
    for intro,names in intros.items():
        if len(names)>=3:errors.append(f'{len(names)} 个角色的简介一字不差（'+'、'.join(names[:6])+('…' if len(names)>6 else '')+'）：每个人写自己的身份、关系和做了什么')
    return errors


def tier_notes(src,out):
    """不算错误的提醒：原文里被提到很多行的龙套，请再核对一次级别。"""
    rows=[]
    for m,body in sections(out/'characters.md',r'^## ([^\n]+)\n'):
        head=body.split('\n### ',1)[0]
        if field(head,'级别')!='龙套':continue
        name=m[1].strip()
        names={n for n in [name,*items(field(head,'别名'))] if len(n)>=2 and n!='无'}
        n=sum(any(x in l for x in names) for l in src.lines)
        if n>=NOTE_MENTIONS:rows.append((n,name))
    rows.sort(reverse=True)
    if not rows:return []
    return ['这些龙套在原文里被提到的行数较多（'+'、'.join(f'{name} {n} 行' for n,name in rows[:10])+('…' if len(rows)>10 else '')+'）。再核对一次级别：有名有姓、有自己的戏的是配角，要写小传和外观；只有职能称谓的保持龙套。这一条不算错误。']


def design_errors(src,out):
    """主角、重要配角、配角的设计字段和场景空镜：取值、字数、依据行号、空镜里不能有人、外观不能几个人套同一句。"""
    errors=[];lines=src.lines
    chars=[]
    for m,body in sections(out/'characters.md',r'^## ([^\n]+)\n'):
        head=body.split('\n### ',1)[0]
        aliases=items(field(head,'别名'))
        chars.append((m[1].strip(),field(head,'级别'),aliases,head,sections_text(body,r'^### ([^\n]+)\n')))
    # 人名全收；别名只收 3 字以上的（「殿下」这类两字别名在空镜里常是普通词）。
    names=sorted({n for c in chars for n in [c[0],*[a for a in c[2] if len(a)>=3]] if len(n)>=2})
    mains=[]
    for name,tier,aliases,head,states in chars:
        if tier not in DESIGN_TIERS:continue
        tag=f'角色「{name}」'
        if field(head,'性别') not in GENDERS:errors.append(f'{tag} 性别只能是 男/女/未知')
        traits=items((field(head,'性格') or '').replace('，','、'))
        if not 3<=len(traits)<=5 or any(len(t)>10 for t in traits):errors.append(f'{tag} 性格要 3–5 个词，每个不超过 10 字，用、分隔')
        lo,hi=BIO_LEN[tier];n=size(field(head,'小传'))
        if not within(n,lo,hi):errors.append(f'{tag} 小传 {n} 字，{tier}要 {lo}–{hi} 字')
        refs=src.refs(field(head,'小传依据'))
        if len(refs)<BIO_LINES[tier]:errors.append(f'{tag} 小传依据至少 {BIO_LINES[tier]} 个原文行号（{src.ref_hint()}，用、分隔），现在有效的 {len(refs)} 个')
        own=[n for n in [name,*aliases] if n]
        scar_ok=any(SCAR.search(field(sb,'外形') or '') for _,sb in states) or any(SCAR.search(l) and any(n in l for n in own) for l in lines)
        for j,(sm,sb) in enumerate(states):
            st=f'{tag}状态「{sm[1].strip()}」'
            if field(sb,'年龄段') not in AGE_BANDS:errors.append(f'{st} 年龄段只能是 '+'/'.join(AGE_BANDS))
            ap=field(sb,'外观设计') or ''
            lo,hi=(80,300) if j==0 else (20,200);n=size(ap)
            if not within(n,lo,hi):errors.append(f'{st} 外观设计 {n} 字，要 {lo}–{hi} 字')
            bad=sorted(set(FORBIDDEN.findall(ap)))
            if bad:errors.append(f'{st} 外观设计不能写：'+'、'.join(bad)+'（背景、画风、手持物、一时的表情动作都不写）')
            ph=sorted(set(PLACEHOLDER_WORDS.findall(ap)))
            if ph:errors.append(f'{st} 外观设计里有占位的话（'+'、'.join(ph)+'）：要写成能直接画的样子，原文没写的按时代、身份和处境补全')
            if SCAR.search(ap) and not scar_ok:errors.append(f'{st} 原文没写这个人有伤疤伤痕残疾，外观设计里不要加')
            if re.search(r'脸型：|发型：|上装：|^\s*\d+[.、]',ap):errors.append(f'{st} 外观设计写成一段连贯的话，不分条、不加标签')
            if j==0:mains.append((name,ap))
    # 同一句写脸、五官、体态、痕迹的话在多人主状态外观里一字不差：在套模板。门槛随人数放宽。
    # 写脸、体型的短句 3 人以上（人多时五分之一）同句就算套模板；其他 8 字以上的长句 4 人以上（人多时四分之一）。
    short_limit=max(3,-(-len(mains)//5));long_limit=max(4,-(-len(mains)//4));seen={}
    for name,ap in mains:
        for c in {re.sub(r'\s','',x) for x in re.split(r'[，。；、,;]',ap)}:
            if (len(c)>=4 and BODY_WORDS.search(c)) or len(c)>=8:seen.setdefault(c,set()).add(name)
    bad=sorted(((c,n) for c,n in seen.items() if len(n)>=(short_limit if BODY_WORDS.search(c) else long_limit)),key=lambda x:-len(x[1]))
    if bad:errors.append('这些话在多人外观里一模一样，每个人要写自己的：'+'；'.join(f'「{c}」（{len(n)} 人）' for c,n in bad[:8]))
    shots=[]
    for m,body in sections(out/'scenes.md',r'^## ([^\n]+)\n'):
        name=m[1].strip();tag=f'场景「{name}」'
        t=field(body,'时段')
        if t not in TIMES:errors.append(f'{tag} 时段只能是 '+'/'.join(TIMES))
        seen_facts=field(body,'原文所见')
        if seen_facts is None or seen_facts=='':errors.append(f'{tag} 缺「原文所见」（原文写到的看得见的东西，每条带行号；原文一点没写就写「无」）')
        elif seen_facts!='无':
            bad=[x for x in re.split(r'[；;]',seen_facts) if x.strip() and not src.refs(x)]
            if bad:errors.append(f'{tag} 原文所见每条要带有效的原文行号（{src.ref_hint()}，跟在短语后面的括号里），这些没有：'+'；'.join(b.strip()[:20] for b in bad[:5]))
        shot=field(body,'空镜') or ''
        n=size(shot)
        if not within(n,60,250):errors.append(f'{tag} 空镜 {n} 字，要 60–250 字')
        other=field(body,'其他时段')
        text=shot
        if other and other!='无':
            for v in re.split(r'[；;]',other):
                if not v.strip():continue
                vm=re.match(r'\s*([^：:]+)[：:](.*)',v)
                label=vm[1].strip() if vm else ''
                # 时段（清晨/白天/黄昏/夜晚里和主时段不同的），或持续一段剧情的状态、天气（被砸之后、雨夜），见 design.md
                if not vm or label==t or len(label)>8 or not 0<size(vm[2])<=60*SLACK:
                    errors.append(f'{tag} 其他时段每条写成「时段或状态：光线和不同之处」：时段是清晨/白天/黄昏/夜晚里和主时段不同的，状态是持续一段剧情的样子或天气（被砸之后、雨夜），名字不超过 8 字，内容不超过 60 字：{v.strip()[:20]}')
                else:
                    errors+=name_errors(f'{tag} 其他时段',label,False)
                text+=v
        ph=sorted(set(PLACEHOLDER_WORDS.findall(text)))
        if ph:errors.append(f'{tag} 空镜里有占位的话（'+'、'.join(ph)+'）：要写成能直接画的样子，原文没写的按时代、地域和用途补全')
        shots.append((name,shot))
        who=[x for x in names if x in text and x not in name]
        if who or PEOPLE_WORDS.search(text):errors.append(f'{tag} 空镜里不能有人物：'+'、'.join(who or PEOPLE_WORDS.findall(text))+'（写的是物件或地名时换个说法）')
        bad=[w for w in STYLE_WORDS if w in text]
        if bad:errors.append(f'{tag} 空镜不写画风词：'+'、'.join(bad))
    limit=max(4,-(-len(shots)//4));seen={}
    for name,shot in shots:
        for c in {re.sub(r'\s','',x) for x in re.split(r'[，。；、,;]',shot)}:
            if len(c)>=8:seen.setdefault(c,set()).add(name)
    bad=sorted(((c,n) for c,n in seen.items() if len(n)>=limit),key=lambda x:-len(x[1]))
    if bad:errors.append('这些话在多个场景的空镜里一模一样，每个地方要写自己的：'+'；'.join(f'「{c}」（{len(n)} 处）' for c,n in bad[:8]))
    return errors


def sections_text(text,pattern):
    matches=list(re.finditer(pattern,text,re.M))
    return [(m,text[m.end():matches[i+1].start() if i+1<len(matches) else len(text)]) for i,m in enumerate(matches)]


def main():
    utf8_stdio()
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,default=Path('input.txt'),help='原文文件；自己写好的分集剧本给目录（里面是 E01.md、E02.md……）');p.add_argument('--out',type=Path,default=Path('out'));p.add_argument('--episodes',type=int)
    a=p.parse_args()
    try:r=validate(a.input,a.out,a.episodes)
    except (OSError,ValueError,TypeError) as e:r={'valid':False,'errors':[str(e)]}
    print(json.dumps(r,ensure_ascii=False));return 0 if r['valid'] else 1

if __name__=='__main__':sys.exit(main())
