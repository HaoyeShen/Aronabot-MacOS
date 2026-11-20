"""Choose readable chat pauses without clipping the answer or adding words."""
from __future__ import annotations

import re
import unicodedata


_PAUSES = '。！？!?；;，,：:—…'
_CLOSING = '。！？!?；;，,：:、）》】」』”’)]}…'
_OPENING = '（《【「『“‘([{'
_CONNECTIVE = re.compile(r'不过|但是|所以|然后|而且|因为|如果|其实|另外|也可以|还可以|这样|不如|要不|至于')
_DANGLING = re.compile(r'(?:因为|所以|但是|然后|如果|虽然|而且|或者|以及|并且|一个|这个|那个|把|被|的|地|很|太|跟|和|给|让|在|能|要)$')
_URL_PATTERN = r'https?://[^\s<>"，。！？；]+'
_URL = re.compile(_URL_PATTERN, re.I)


def _map_prose(text: str, transform) -> str:
    """Apply a prose-only rewrite without modifying URL characters."""
    parts = []
    start = 0
    for match in _URL.finditer(text):
        parts.extend((transform(text[start:match.start()]), match.group()))
        start = match.end()
    parts.append(transform(text[start:]))
    return ''.join(parts)


_TOKEN = re.compile(_URL_PATTERN + r'|\d+(?:\.\d+)?(?:%|℃|分钟|小时|公斤|毫升|公里|个|岁|元|秒|天|年|米)|[A-Za-z0-9_]+(?:[-./:@][A-Za-z0-9_]+)*')


_INTERJECT = r'(?:嘿嘿|哈哈|唔|诶|欸|嗯|哦|哈|哎|唉)'


def trim_interjections(text: str) -> str:
    """Drop leading/trailing filler interjections such as "嘿嘿" or "唔".

    Only standalone interjections at clause boundaries are removed, so a name
    like "哈尔滨" or an interjection inside a sentence is left alone.
    """
    value = str(text or '').strip()
    if not value:
        return value
    value = re.sub(
        rf'^(?:(?:{_INTERJECT})(?:[，,。.!！、\s]*(?:{_INTERJECT}))*)'
        rf'(?=[，,。.!！、\s]|$)[，,。.!！、\s]*', '', value)
    value = re.sub(rf'[，,。.!！、\s]*(?:{_INTERJECT})[。.!！~～\s]*$', '', value)
    value = re.sub(rf'[，,。.!！、]\s*(?:{_INTERJECT})\s*(?=[，,。.!！、]|$)', '', value)
    return value.strip()


_OFFER = re.compile(
    r'(?:有什么(?:事|需要|想做的|想聊的)?[^。！？!?，,]{0,10}(?:都|就|尽管)?(?:可以)?'
    r'(?:跟我说|告诉阿洛娜|交给阿洛娜|找阿洛娜|交给我)'
    r'|交给我吧|需要的时候(?:直接)?(?:告诉|找)我|随时(?:可以)?(?:找我|告诉我)'
    r'|我来帮你|有需要(?:随时)?(?:告诉|找)我|尽管(?:交给|告诉)我|我帮你(?:看看|处理|改|弄)?吧)')


def normalize_punctuation(text):
    """Replace em/en dashes with a plain space; chat style avoids them."""
    return _map_prose(str(text or ''), lambda part: re.sub(r'[–—]+', ' ', part)).strip()


def strip_leading_address(text, address, names=()):
    """Drop a redundant leading address from a short reply.

    "Harry昊昊老师 阿洛娜在" -> "阿洛娜在"; a longer reply keeps the
    address so the user is still occasionally called by name.
    """
    value = str(text or '').strip()
    if not value:
        return value
    candidates = [str(item).strip() for item in (address, *names) if str(item or '').strip()]
    for candidate in sorted(set(candidates), key=len, reverse=True):
        if len(candidate) < 2 or not value.startswith(candidate):
            continue
        suffix = value[len(candidate):]
        rest = suffix.lstrip('，,。.!！?？:：、 \t\n')
        if rest != suffix and rest and len(rest) <= 12:
            return rest
        break
    return value


def strip_service_offers(text: str) -> str:
    """Remove "交给我吧 / 有什么事都可以跟我说" style service offers."""
    value = str(text or '').strip()
    if not value or not _OFFER.search(value):
        return value
    clauses = re.split(r'(?<=[，,。！？!?；;\n])', value)
    kept = [part for part in clauses
            if part.strip() and not _OFFER.search(part)]
    value = ''.join(kept).strip()
    value = re.sub(r'[，,、；;：:\s]+$', '', value).strip()
    return value


_QUESTION_TAIL = re.compile(
    r'(?:好不好|行不行|可不可以|要不要|吗|嘛|(?<![什怎这那多么])么)[。！!…～~]*$')
_QUESTION_START = re.compile(
    r'^(?:你想|你要|你有|你能|你是|是否|要不要|想不想|要我|需要我|能不能|'
    r'可不可以|请问|想查|想聊|想看|是.{1,24}还是)')
_SENTENCE_SPLIT = re.compile(r'(?<=[。！？!?；;\n])')
_CLAUSE_SPLIT = re.compile(r'(?<=[，,、：:])')


def _question_clause(clause: str) -> bool:
    value = str(clause or '').strip()
    if not value:
        return False
    if value.rstrip().endswith(('？', '?')):
        return True
    return bool(_QUESTION_TAIL.search(value.rstrip('。！!…～~ \t')))


def strip_questions(text: str) -> str:
    """Drop question sentences/clauses; replies use statements only.

    A statement before a question keeps its text ("新闻我看过了，要总结吗？"
    becomes "新闻我看过了").  A sentence that starts as a question, including
    comma-separated option lists such as "你想查资料，看文件，还是聊游戏？",
    is removed as a whole so no half question is sent.
    """
    value = str(text or '').strip()
    if not value:
        return value
    # Never treat a URL query string or dash as a question clause.
    protected = {}
    def hide(match):
        key = '\x00%d\x00' % len(protected)
        protected[key] = match.group(0)
        return key
    value = _URL.sub(hide, value)
    kept = []
    for sentence in _SENTENCE_SPLIT.split(value):
        if not sentence:
            continue
        if not sentence.strip():
            # Preserve intentional line breaks/blank lines between bubbles.
            kept.append(sentence)
            continue
        clauses = _CLAUSE_SPLIT.split(sentence)
        question_at = next((index for index, clause in enumerate(clauses)
                            if _question_clause(clause)), None)
        if question_at is None:
            kept.append(sentence)
            continue
        first = clauses[0].strip()
        if question_at == 0 or (_QUESTION_START.match(first) and
                                ('还是' in sentence or sentence.rstrip().endswith(('？', '?')))):
            # The whole sentence is the question/option list.
            continue
        prefix = ''.join(clauses[:question_at]).strip()
        if prefix:
            kept.append(prefix)
    value = ''.join(kept).strip()
    value = re.sub(r'[，,、；;：:\s]+$', '', value).strip()
    value = value.replace('？', '').replace('?', '').strip()
    for key, token in protected.items():
        value = value.replace(key, token)
    return value


def split_chat_bubbles(text: str, limit: int, max_bubbles: int,
                       *, allow_soft_split: bool = True) -> list[str]:
    """Keep model line breaks; balance punctuation, clause pauses and short tails.

    Each paragraph uses a bounded path search so an earlier pleasant pause
    cannot force an orphan final word or exceed the configured bubble count.
    A URL or Latin identifier is indivisible; a too-long token needs rewriting.
    """
    # Strict callers (e.g. video captions) require complete sentences and
    # retain their original sentence-count policy.
    lines = text.splitlines() if allow_soft_split else re.split(r'(?<=[。！？!?；;])|\n',text)
    paragraphs = [line.strip() for line in lines if line.strip()]
    if not paragraphs or max_bubbles < 1:
        return []
    if sum(len(p) for p in paragraphs) > limit * max_bubbles:
        return []
    # Only dangling connectors/addresses merge with the next line.  A short
    # complete answer such as "在的" must keep its own bubble; merging it with
    # the explanation produced "在的视频号……" fragments.
    joinable = {'老师', '嗯', '唔', '诶', '那个', '然后', '所以', '但是',
                '不过', '而且', '还有', '这', '那', '就', '也'}
    for index in range(len(paragraphs)-2,-1,-1):
        if (allow_soft_split
                and paragraphs[index].strip('，,。.!！、：: ') in joinable
                and not paragraphs[index].endswith(('？','?'))):
            paragraphs[index:index+2] = [''.join(paragraphs[index:index+2])]
    output = []
    for line_number, paragraph in enumerate(paragraphs):
        # Reserve enough bubbles for every remaining explicit paragraph.
        reserved = sum((len(p)+limit-1)//limit for p in paragraphs[line_number+1:])
        budget = max_bubbles-len(output)-reserved
        if budget < 1:
            return []
        n = len(paragraph)
        if n <= limit:
            output.append(paragraph)
            continue
        blocked = set()
        for token in _TOKEN.finditer(paragraph):
            blocked.update(range(token.start()+1,token.end()))
        # A dash pair is one pause; never split between its two characters.
        for match in re.finditer(r'—{2,}', paragraph):
            blocked.update(range(match.start()+1,match.end()))
        for i in range(1,n):
            if (paragraph[i] in _CLOSING or paragraph[i-1] in _OPENING
                    or unicodedata.combining(paragraph[i])
                    or paragraph[i] in '\ufe0f\u200d' or paragraph[i-1] == '\u200d'):
                blocked.add(i)
        connective = {match.start() for match in _CONNECTIVE.finditer(paragraph)}
        penalties = {}
        for end in range(1,n+1):
            if end in blocked:
                continue
            previous = paragraph[:end].rstrip('）》】」』”’)]}')[-1:]
            if end == n or previous in '。！？!?；;':
                penalty = 0
            elif previous in '—…':
                penalty = 2
            elif previous in '，,：:':
                # Ending a bubble on a comma leaves a dangling clause; prefer
                # a dash/sentence end, but still better than cutting a word.
                penalty = 12
            elif allow_soft_split:
                penalty = 5 if previous.isspace() or end in connective else 24
            else:
                continue
            if end < n and _DANGLING.search(paragraph[:end]):
                penalty += 22
            if end < n and paragraph[end] in '的地得着':
                penalty += 16
            penalties[end] = penalty
        # (position, bubble count) -> (cost, preceding position).
        paths = {(0,0):(0.0,0)}
        for count in range(1,min(budget,n)+1):
            for end, penalty in penalties.items():
                if n-end > (budget-count)*limit:
                    continue
                best = None
                for start in range(max(0,end-limit),end):
                    preceding = paths.get((start,count-1))
                    if preceding is None or not paragraph[start:end].strip():
                        continue
                    length = len(paragraph[start:end].strip())
                    # Favor fewer meaningful bubbles over many tiny reactions.
                    cost = preceding[0]+8+penalty+max(0,6-length)*4
                    if best is None or cost < best[0]:
                        best = (cost,start)
                if best is not None:
                    paths[end,count] = best
        finals = [(value[0],count) for (end,count),value in paths.items() if end == n]
        if not finals:
            return []
        _, count = min(finals)
        parts = []
        end = n
        while count:
            start = paths[end,count][1]
            parts.append(paragraph[start:end].strip())
            end, count = start, count-1
        output.extend(reversed(parts))
    return output
