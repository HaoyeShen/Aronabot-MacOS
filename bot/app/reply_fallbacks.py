"""Short, situational replies when the model cannot produce a useful answer."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from .prompting import address_name
from .understanding import cat_sound_requested


LINES = {
    'arona': {
        'unknown': ('{t}，我还不知道答案。', '{t}，这个我还不清楚。', '{t}，这部分我还需要学习。'),
        'network': ('{t}，刚才网络连接中断了。', '{t}，刚刚没连上服务。', '{t}，这次请求没成功。'),
        'search_empty': ('{t}，这次没查到可靠资料。', '{t}，你有相关来源或链接吗？', '{t}，暂时没有可核实的结果。'),
        'thinking': ('{t}，刚才没答完整，请再问一次。', '{t}，刚才回答出错了。', '{t}，这次没能给出完整答案。'),
        'clarify': ('{t}，你指的是哪一件事呀？', '{t}，能再说具体一点吗？', '{t}，我有点没听明白。'),
        'help': ('{t}，哪里需要我帮忙呀？', '{t}，说说遇到什么事啦。', '{t}，你想先解决哪件事呀？'),
        'comfort': ('{t}，我在呢，慢慢说。', '辛苦啦，{t}，我陪着你。', '{t}，我会认真听你说的。'),
        'greeting': ('{t}好呀，阿洛娜在呢。', '{t}，今天也请多关照！', '{t}，见到你真开心。'),
    },
    'plana': {
        'unknown': ('{t}，这部分我还不熟悉。', '{t}，这题还需要核实。', '{t}，这个我还不懂。'),
        'network': ('{t}，刚才连接中断了。', '{t}，暂时没连上网络。', '{t}，这次连接没有成功。'),
        'search_empty': ('{t}，还没有查到可靠说法。', '{t}，请再给我一点线索。', '{t}，目前没有查到。'),
        'thinking': ('{t}，刚才没能完整回答。', '{t}，这次回答出错了。', '{t}，请再发一次问题。'),
        'clarify': ('{t}，你指的是哪一件事？', '{t}，可以说具体一点吗？', '{t}，请补充一点信息。'),
        'help': ('{t}，哪里需要我帮忙？', '{t}，遇到了什么事？', '{t}，你想先处理哪件事？'),
        'comfort': ('{t}，我在这里。', '{t}，我会认真听你说。', '{t}，我会陪着你。'),
        'greeting': ('{t}，你好。', '{t}，我在。', '{t}，很高兴见到你。'),
    },
}


def fallback_reply(text: str, persona_id: str, reason: str, turn: int = 0,
                   sender: str = '', limit: int = 23, *, persona: dict | None = None) -> str:
    """Choose complete sentences, never truncate a name or fabricate facts."""
    requested_cat = cat_sound_requested(text)
    text = re.sub(r'@\S+\s*', '', text or '').strip()
    if re.search(r'(?:我|最近|今天|心情).{0,8}(?:难过|伤心|委屈|崩溃|痛苦|好累|失恋|失业|想哭|不好)|^(?:好难过|好伤心|想哭|好累)', text):
        reason = 'comfort'
    elif re.fullmatch(r'(?:阿洛娜|普拉娜)?[，,\s]*(?:帮帮我|帮我一下|救救我|帮个忙)[呀啊吧！!。？?\s]*', text):
        reason = 'help'
    elif len(text) <= 18 and re.search(r'^(?:阿洛娜|普拉娜)?[，,\s]*(?:你好|早上好|晚上好|在吗|嗨|哈喽)', text):
        reason = 'greeting'
    elif re.fullmatch(r'(?:这个|那个|它|这件事|那件事)(?:呢|怎么样|怎么说|怎么办)[？?。\s]*', text):
        reason = 'clarify'
    elif requested_cat:
        return '喵～'
    elif re.search(r'今天(?:是)?几(?:号|月|日)|今天星期几|今天周几', text):
        now = datetime.now().astimezone()
        line = f'今天{now.month}月{now.day}日，星期{"一二三四五六日"[now.weekday()]}。'
        if len(line) <= limit:
            return line
    # Basic arithmetic remains answerable even if every remote service is down.
    match = re.fullmatch(r'(?:算一下|算算|请问)?\s*(-?\d{1,8}(?:\.\d{1,4})?)\s*([+\-*/×÷])\s*(-?\d{1,8}(?:\.\d{1,4})?)(?:\s*[=＝？?]|等于多少|是多少)?', text)
    if match:
        try:
            a, op, b = Decimal(match[1]), match[2], Decimal(match[3])
            if op in ('/', '÷') and not b:
                line = '零不能作为除数。'
                return line if len(line) <= limit else '不能除零。'
            value = a+b if op == '+' else a-b if op == '-' else a*b if op in ('*', '×') else a/b
            answer = format(value.normalize(), 'f')
            if len(answer) + 1 <= limit:
                return answer + '。'
        except (InvalidOperation, ArithmeticError):
            pass
    builtin = (persona_id in ('arona', 'plana') and
               (persona is None or persona.get('name') in ('阿洛娜', '普拉娜')))
    choices = LINES['plana' if persona_id == 'plana' or not builtin else 'arona']
    options = choices.get(reason, choices['unknown'])
    if not builtin:
        # Without a running model, avoid inventing a custom character's title
        # or borrowing Arona's catchphrases. An explicit template is safe.
        names = [address_name(sender, persona)] if persona and persona.get('address_template') else ['']
    elif persona and persona.get('address_template'):
        names = [address_name(sender, persona), '']
    else:
        names = [address_name(sender), '老师']
    for teacher in dict.fromkeys(names):
        for offset in range(len(options)):
            line = options[(turn + offset) % len(options)].format(t=teacher).lstrip('，, ')
            if len(line) <= limit:
                return line
    return '这部分还不确定。'


_FILLER = re.compile(
    r'(?:有什么想做的|有什么想聊的|想聊点什么|想做什么|交给我吧|尽管交给我|能帮上忙|我来帮你|'
    r'需要我做什么|有什么想说的|想说的|尽管说|在听|随时说|随时找我|有什么需要|需要什么|需要帮忙|要我帮什么|'
    r'有什么事吗|有事吗|什么事|需要我|要我帮|帮忙|今天过得怎么样|最近过得怎么样|今天怎么样|最近怎么样|'
    r'过得怎么样|感觉怎么样|在忙什么|还好吗|怎么了|今天|现在|'
    r'告诉我吧|你说吧|说吧|做的吗|在的|在呢|我在|一直都在|一直|都|在|哦|呀|啊|呢|嗯|唔|诶|哈|'
    r'嘿嘿|好的|好|收到|知道了|确实|原来|是这样|听起来|辛苦了|抱抱|没事|当然|可以|对的|是的|'
    r'没错|欢迎|早上好|晚安|哈喽|你好|老师|懂了|明白了|了解了|晓得了|好嘞)')
_PUNCT = re.compile(r'[\s，。！？、,.!?~～…—\-—：:；;“”"\'（）()]+')
_MEDIA = re.compile(r'\[[^\]]+\]|[\U0001F300-\U0001FAFF\u2600-\u27BF]')
_CONFIRM = re.compile(
    r'(?:已|已经)(?:帮你|给你|为你)?(?:发送|发出|发好|完成|处理|更新|修改|改好|删除|创建|'
    r'发布|打开|关闭|备份|设好|设置|执行|搞定)|(?:搞定|办妥|弄好|完成了)')


_OPENER = re.compile(
    r'^\s*(?:在吗|在么|在嘛|在不在|你好|您好|嗨|哈喽|hi|hello|在|喂)[\s？?！!，,。.~～]*$', re.I)


def question_only_reply(text, names=()):
    """True when the reply adds nothing but a question (no statement remains)."""
    value = str(text or '')
    if not re.search(r'[？?]', value):
        return False
    clauses = re.split(r'(?<=[，,。！？!?；;])', value)
    statements = ''.join(
        part for part in clauses if not part.rstrip().endswith(('？', '?')))
    return not (statements.strip() and not content_free_reply(statements, names))


def bare_opener(text):
    """A greeting/opener that carries no topic of its own."""
    return bool(_OPENER.match(str(text or '').strip()))


def _bigrams(value):
    value = re.sub(r'[^\u4e00-\u9fa5A-Za-z0-9]', '', str(value or ''))
    return {value[index:index + 2] for index in range(len(value) - 1)}


def content_free_reply(text, names=(), user_text=''):
    """True for a reply that only acknowledges, echoes or reassures.

    A short "在的" is a valid answer to "在吗", but in normal conversation a
    whole turn of acknowledgement gives the other side nothing.  The caller
    repairs it once with a concrete fact, judgement or question; a concrete
    number/name/code or any remaining subject matter makes this False.
    """
    raw = str(text or '').strip()
    if not raw or len(raw) > 60:
        return False
    if _CONFIRM.search(raw):
        return False
    value = raw
    for name in sorted({str(item) for item in names if item and len(str(item)) >= 2},
                       key=len, reverse=True):
        value = value.replace(name, '')
    # Nicknames may be Latin; only tokens the reply itself introduces count as
    # concrete information (numbers, model names, versions, codes).
    if re.search(r'\d|[A-Za-z]{2,}', value):
        return False
    value = _MEDIA.sub('', value)
    value = _PUNCT.sub('', value)
    value = _FILLER.sub('', value)
    if len(value) <= 1:
        return True
    # A short reply made almost entirely of the other side's own words only
    # echoes the message.  Very short openers ("你好", "在吗") are exempt so a
    # normal greeting reply is not repaired.
    source = str(user_text or '').strip()
    if len(source) >= 6 and len(raw) <= 30:
        reply_grams = _bigrams(value)
        if reply_grams and len(reply_grams - _bigrams(source)) <= 1:
            return True
    return False


def vague_non_answer(text):
    return bool(re.search(r'(?:这题|这个问题)?(?:让)?(?:我)?(?:有点)?(?:迷糊|没理清|没琢磨明白|没弄明白)(?:了|啦|呀|呢|哦|。|！|!|\s)*$',str(text or '').strip()))
