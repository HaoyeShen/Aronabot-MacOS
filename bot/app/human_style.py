"""Aggregate local chat records into a privacy-safe human speaking style.

Only counts and percentiles leave this module.  Message text, nicknames,
timestamps and conversation names are never stored in the profile or prompt.
"""
from __future__ import annotations

import json
import logging
import re
import statistics
from pathlib import Path

from .paths import DATA

log = logging.getLogger(__name__)

CORPUS = DATA / 'local_corpus/private_wechat'
CACHE = DATA / 'local_corpus/human_style.json'
PREFIX = re.compile(r'^[^\n:]{1,80}:\s*\n')
PARTICLES = ('了', '啊', '吧', '呀', '呢', '哦', '嘛', '啦', '哈', '诶', '嗯')
MIN_SAMPLES = 500


def _fingerprint(files):
    total = 0
    newest = 0
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        total += stat.st_size
        newest = max(newest, int(stat.st_mtime))
    return {'files': len(files), 'bytes': total, 'mtime': newest}


def _is_text(value):
    value = str(value or '').strip()
    return bool(value and not value.startswith('<') and 'http' not in value.casefold()
                and '\x00' not in value)


def analyze(folder: Path = CORPUS) -> dict:
    """Return aggregate style numbers; never return message text."""
    files = sorted(folder.glob('*.json')) if folder.is_dir() else []
    lengths = []
    finals = {key: 0 for key in PARTICLES}
    no_end = comma = emoji = laugh = first = second = question = inner = 0
    conversations = 0
    for path in files:
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(data, list):
            continue
        seen = 0
        for entry in data:
            if not isinstance(entry, dict) or entry.get('direction') != 'incoming':
                continue
            body = PREFIX.sub('', str(entry.get('content') or '').strip(), count=1).strip()
            if not _is_text(body) or len(body) > 200:
                continue
            lengths.append(len(body))
            seen += 1
            if '\n' in body:
                inner += 1
            if body[-1] not in '。！？!?～~…':
                no_end += 1
            if body[-1] in finals:
                finals[body[-1]] += 1
            if '，' in body or ',' in body:
                comma += 1
            if re.search(r'[\U0001F300-\U0001FAFF\u2600-\u27BF]', body):
                emoji += 1
            if '哈哈' in body:
                laugh += 1
            if '我' in body:
                first += 1
            if '你' in body:
                second += 1
            if body[-1] in '？?' or re.search(r'[？?]', body):
                question += 1
        if seen >= 20:
            conversations += 1
    count = len(lengths)
    profile = {'samples': count, 'conversations': conversations,
               'fingerprint': _fingerprint(files)}
    if count < MIN_SAMPLES:
        return profile
    ordered = sorted(lengths)

    def pct(value):
        return round(100 * value / count, 1)

    profile.update({
        'median': int(statistics.median(lengths)),
        'p25': ordered[count // 4],
        'p75': ordered[count * 3 // 4],
        'under_15': pct(sum(1 for item in lengths if item <= 15)),
        'under_20': pct(sum(1 for item in lengths if item <= 20)),
        'no_end_punct': pct(no_end),
        'comma': pct(comma),
        'emoji': pct(emoji),
        'laugh': pct(laugh),
        'first_person': pct(first),
        'second_person': pct(second),
        'question': pct(question),
        'inner_newline': pct(inner),
    })
    profile['particles'] = [key for key, value in
                            sorted(finals.items(), key=lambda item: -item[1])[:4]
                            if value / count >= 0.01]
    return profile


def render(profile: dict) -> str:
    if profile.get('samples', 0) < MIN_SAMPLES:
        return ''
    particles = '、'.join(profile.get('particles') or []) or '了、啊、吧'
    return (
        '【本机人类聊天语感（仅统计，不含原文）】\n'
        f"- 本机 {profile['samples']} 条人类消息的中位长度 {profile['median']} 字，"
        f"常见 {profile['p25']}-{profile['p75']} 字，{profile['under_20']}% 在 20 字以内；"
        "先说完一件事，再考虑补第二句。\n"
        f"- {profile['no_end_punct']}% 的消息句末不加句号，只有 {profile['comma']}% 用逗号；"
        "分句多用自然停顿或空格，少用书面标点。\n"
        f"- 句尾常见：{particles}；表情和「哈哈」很少（{profile['emoji']}% / {profile['laugh']}%）。\n"
        "- 直接说事，少用“首先/其次/总之/总的来说”等书面结构。\n"
        "模仿这种长度、断句和句尾习惯；不要复制任何具体句子、昵称或口癖，也不要为了像人硬加语气词。"
    )


def load_or_build(folder: Path = CORPUS, cache: Path = CACHE) -> str:
    """Return the cached block, rebuilding it when the corpus changes."""
    files = sorted(folder.glob('*.json')) if folder.is_dir() else []
    if not files:
        return ''
    fingerprint = _fingerprint(files)
    try:
        saved = json.loads(cache.read_text())
    except (OSError, ValueError):
        saved = {}
    if (saved.get('fingerprint') == fingerprint and isinstance(saved.get('block'), str)
            and saved.get('samples', 0) >= MIN_SAMPLES):
        return saved['block']
    profile = analyze(folder)
    block = render(profile)
    if profile.get('samples', 0) >= MIN_SAMPLES:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps({'fingerprint': profile['fingerprint'],
                                          'samples': profile['samples'],
                                          'profile': profile, 'block': block},
                                         ensure_ascii=False, indent=2))
            cache.chmod(0o600)
        except OSError as exc:
            log.warning('人类语感缓存写入失败：%s', type(exc).__name__)
        log.info('人类语感统计完成 · %d 条 · 中位 %d 字', profile['samples'], profile['median'])
    return block
