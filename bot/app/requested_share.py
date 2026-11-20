"""Resolve explicit share requests to actual, reviewed public destinations."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from html import unescape
import logging
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .bilibili_video import SUGGESTIVE
from .link_reader import PageText, fetch_public
from .model_client import make_client
from .news_evidence import ArticleEvidence, is_recent, news_now, published_time
from .web_search import _discover, _relevant, normalize_query, search_forbidden

log = logging.getLogger(__name__)

LABELS = {'video': '视频', 'news': '新闻', 'article': '公众号推文', 'music': 'QQ 音乐'}
FORMATS = {
    'video': r'(?:哔哩哔哩|[Bb]站)?\s*(?:短视频|视频)',
    'news': r'(?:新闻报道|新闻|报道)',
    'article': r'(?:微信)?公众号(?:推文|文章)?|推文',
    'music': r'QQ\s*音乐(?:歌曲|音乐|歌)?|歌曲|音乐|首歌|歌',
}
SITE_QUERIES = {'video': 'site:bilibili.com/video', 'article': 'site:mp.weixin.qq.com/s',
                'music': 'site:y.qq.com'}
NEWS_DOMAINS = ('news.cn', 'xinhuanet.com', 'people.com.cn', 'cctv.com', 'chinanews.com.cn',
                'cnr.cn', 'gmw.cn', 'cyol.com', 'chinanews.com', 'thepaper.cn',
                'caixin.com', 'gov.cn', 'bbc.com', 'reuters.com', 'apnews.com')
REJECT = re.compile(r'点击领取|扫码加群|稳赚不赔|博彩下注|成人直播|无码色情|色情资源|破解下载|诱导下载|标题党|少走\s*\d+\s*[%％]|从小白到大神', re.I)
UNAVAILABLE = re.compile(r'安全验证|访问受限|请求过于频繁|内容已被删除|该内容已删除|该内容无法查看|内容因违规|无法播放|access denied|captcha', re.I)

@dataclass(frozen=True)
class ShareRequest:
    kind: str
    topic: str
    age_hours: int | None = None

@dataclass(frozen=True)
class ShareLink:
    title: str
    url: str
    date: str = ''
    indexed: bool = False
    evidence: str = ''


def parse_share_request(text, names=()):
    text = str(text or '').strip()
    if len(text) > 300 or '\n' in text or '<' in text or 'http' in text.casefold() or search_forbidden(text):
        return None
    if names:
        name_list = '|'.join(re.escape(name) for name in sorted(set(filter(None, names)), key=len, reverse=True))
        if name_list:
            text = re.sub(rf'^[@＠]?(?:{name_list})(?=[\s，,：:]|给我|发|推|帮我|请|能不能|可以|麻烦)[\s，,：:]*',
                          '', text, flags=re.I)
    # Anchor the speech act at the beginning, so discussion and quotations
    # that merely contain an imperative do not cause outgoing messages.
    opener = re.match(r'^(?:(?:请|麻烦|帮忙|能不能|能否|可不可以|可以|能|我想让你|我想让|帮我|给我们|给我|给大家|直接|再|你|然后)\s*){0,8}'
                     r'(?:推送|推荐|分享|转发|发(?:一下|一下子|送)?|推|来)(?:给我|给我们|给大家)?\s*', text)
    if opener:
        request = text[opener.end():]
        if request.startswith(('了', '过', '的是', '的那')):
            return None
    else:
        find_send = re.fullmatch(r'(?:(?:请|麻烦|帮我|给我|能不能|可以)\s*){0,5}(?:把|找|搜)(?:一下|一找|一搜)?(.+?)(?:然后)?(?:发|分享|推送)给(?:我们|我|大家)[吧呗吗？?。！! ]*', text)
        if not find_send:
            return None
        request = find_send.group(1)
    request = re.sub(r'[，,。\s]*(?:请)?(?:直接)?(?:发|给)(?:给我|给我们|给大家|我)?(?:个|一个)?(?:原文|播放)?链接[吧呗吗呀呢？?。！! ]*$', '', request)
    song_measure = bool(re.match(r'^一?首',request))
    request = re.sub(r'^(?:一个|一条|一篇|一部|一首|一段|个|条|篇|部|段|首|些|点)\s*', '', request)
    request = re.sub(r'(?:给我|给我们|给大家)?[吧呗吗呀呢？?。！! ]+$', '', request).strip()
    request = re.sub(r'(?:给我们|给我|给大家)(?:看看|听听|看一下|听一下)?$', '', request).strip()
    for kind, syntax in FORMATS.items():
        tail = re.search(rf'(?:的)?(?:{syntax})(?:播放)?(?:链接|网址)?$', request, re.I)
        head = re.match(rf'^(?:{syntax})(?:链接|网址)?(?:里(?:面)?|上(?:面)?|[:：\s]|关于|有关|中)', request, re.I)
        # Song requests often name QQ 音乐 before the track, with no separator.
        if kind == 'music' and not head:
            head = re.match(r'^QQ\s*音乐(?:里(?:面)?|上(?:面)?|的)?\s*', request, re.I)
        if not tail and not head and not (kind == 'music' and song_measure):
            continue
        topic = request[:tail.start()] if tail else request[head.end():] if head else request
        if kind == 'music' and re.search(r'(?:轻|纯|古典|电子|背景)音乐(?:链接)?$',request):
            topic = re.sub(r'链接$','',request)
        if tail and tail.group(0) == request and kind == 'music':
            topic = ''
        age = None
        if kind in ('news', 'video', 'article'):
            if re.search(r'今天|今日',topic):
                age=24
            elif re.search(r'最近|近期|最新|这周|本周',topic):
                age=168
            topic=re.sub(r'^(?:关于|有关)?(?:今天|今日|最近|近期|最新|这周|本周)(?:的)?', '', topic)
        topic = re.sub(r'^(?:关于|有关|和)\s*|(?:相关|有关系)?的\s*$|(?:相关|有关系)\s*$', '', topic)
        if kind == 'music' and '《' not in topic:
            topic = re.sub(r'(?<=\w)的(?=\w)', ' ', topic, count=1)
        topic = re.sub(r'《([^》]+)》',r' \1 ',topic)
        topic = re.sub(r'\s+', ' ',topic).strip(' ，,:：')
        if re.search(r'不要|别发|不用|不必|禁止|给.{1,12}(?:发|推送)|说[：:]|什么是|怎么发', topic):
            return None
        return ShareRequest(kind,topic,age)
    return None


def canonical_source(kind, raw_url):
    try:
        parts = urlsplit(str(raw_url))
        host = parts.hostname
        if (parts.scheme not in ('https','http') or not host or parts.username or parts.password or
                parts.port is not None or len(raw_url) > 1500):
            return ''
    except (ValueError, TypeError):
        return ''
    path = parts.path
    if kind == 'video':
        match = re.fullmatch(r'/(?:zh-Hans/)?video/(BV[A-Za-z0-9]{10}|av[0-9]{1,18})/?', path)
        if host != 'www.bilibili.com' or not match:
            return ''
        return 'https://www.bilibili.com/video/' + match.group(1) + '/'
    if kind == 'music':
        match = re.fullmatch(r'/(?:n/(?:ryqq(?:_v2)?/songDetail|yqq/song))/([A-Za-z0-9]{6,22})(?:\.html)?/?', path)
        if host != 'y.qq.com':
            return ''
        if match:
            return f'https://y.qq.com/n/{"ryqq_v2" if "/ryqq_v2/" in path else "ryqq"}/songDetail/{match.group(1)}'
        if re.fullmatch(r'/n/ryqq(?:_v2)?/playlist/\d{4,20}/?',path):
            return 'https://y.qq.com' + path.rstrip('/')
        return ''
    if kind == 'article':
        if host != 'mp.weixin.qq.com':
            return ''
        if re.fullmatch(r'/s/[A-Za-z0-9_-]{8,110}/?',path):
            return 'https://mp.weixin.qq.com' + path.rstrip('/')
        fields = dict(parse_qsl(parts.query))
        if path == '/s' and all(re.fullmatch(r'[A-Za-z0-9_=+-]{1,150}', fields.get(key,'')) for key in ('__biz','mid','idx','sn')):
            return 'https://mp.weixin.qq.com/s?' + urlencode({key:fields[key] for key in ('__biz','mid','idx','sn')})
        return ''
    if kind != 'news' or not any(host == d or host.endswith('.'+d) for d in NEWS_DOMAINS):
        return ''
    if re.search(r'/(?:video|videos|live|playlist)(?:/|$)|(?:VIDE|VIDA)[A-Za-z0-9]{8}',path,re.I):
        return ''
    query = [(k,v) for k,v in parse_qsl(parts.query) if k.casefold() in ('id','articleid','docid','idtype')]
    if len(path.strip('/')) < 8 and not query:
        return ''
    return urlunsplit(('https',host,path,urlencode(query),''))


def search_candidates(profile, query, timeout, cancelled):
    if urlsplit(profile.get('base_url','')).hostname == 'api.deepseek.com':
        try:
            result = make_client(profile)._request('https://api.deepseek.com/v1/tools/search', 'POST',
                 {'query':query, 'count':8, 'need_content':True}, timeout=min(timeout,8))
            rows = result.get('results') or []
            if rows:
                return [{**row,'provider_index':True} for row in rows if isinstance(row,dict)]
        except Exception as exc:
            log.info('请求分享检索入口未返回结果 · %s', type(exc).__name__)
    if cancelled():
        return []
    return [{'url':u, 'title':t} for u,t,_ in _discover(query,'html',timeout=3)]


def inspect_candidate(request, row, url, *, model_review=False):
    data, charset, destination = fetch_public(url, timeout=4, include_final_url=True)
    final_url = canonical_source(request.kind, destination)
    challenged = (request.kind == 'article' and urlsplit(destination).hostname == 'mp.weixin.qq.com'
                  and urlsplit(destination).path == '/mp/wappoc_appmsgcaptcha')
    if challenged and row.get('provider_index'):
        title = str(row.get('title') or '')
        body = str(row.get('content') or '')
        date = published_time(row.get('date'))
        return review_candidate(request,title,body,url,date,indexed=True,model_review=model_review)
    if not final_url:
        return None
    # QQ Music may redirect to its new presentation of the same track.
    if final_url != url and not (request.kind == 'music' and final_url.rsplit('/',1)[-1] == url.rsplit('/',1)[-1]):
        return None
    document = data.decode(charset,'replace')
    article = ArticleEvidence()
    article.feed(document)
    date, body = article.evidence()
    fallback_title = re.search(r'<title(?:\s[^>]*)?>([^<]{2,240})</title>',document,re.I)
    title = unescape(article.title or (fallback_title.group(1) if fallback_title else '')).strip()
    title = re.split(r'\s*[-|｜_]\s*(?:QQ音乐|哔哩哔哩|bilibili|新华网|人民网|央视网).*$',title,flags=re.I)[0]
    if request.kind == 'video' and not ('videoData' in document or '__INITIAL_STATE__' in document):
        return None
    if request.kind == 'article':
        page = PageText()
        page.feed(document)
        body = ' '.join(page.main_parts)
        if len(body.strip()) < 80 or UNAVAILABLE.search(body[:120]):
            return None
    if request.kind == 'news' and (len(body.strip()) < 100 or not (date or published_time(row.get('date')))):
        return None
    date = date or published_time(row.get('date'))
    if request.kind == 'video' and row.get('provider_index'):
        body += ' ' + str(row.get('content') or '')[:1800]
    return review_candidate(request,title,body,final_url,date,model_review=model_review)


def review_candidate(request, title, body, url, date, *, indexed=False, model_review=False):
    title = ' '.join(title.split())
    if (not title or 'http' in title.casefold() or UNAVAILABLE.search(title)
            or REJECT.search(title) or SUGGESTIVE.search(title)):
        return None
    if indexed and (len(body.strip()) < 160 or UNAVAILABLE.search(body[:240])):
        return None
    if request.age_hours and not is_recent(date,news_now(),request.age_hours):
        return None
    evidence = title if request.kind == 'music' and '/songDetail/' in url else title+' '+body[:3000]
    if REJECT.search(body[:1800]) or (not model_review and not _relevant(request.topic,evidence)):
        return None
    return ShareLink(title[:125],url,date[:10],indexed,body[:1000])


def collect_shares(request, query, profile, *, cancelled=lambda:False, timeout=12):
    """Execute the model's search using the selected format's public sources."""
    deadline=time.monotonic()+timeout
    topic = query + (' 最新' if request.age_hours else '')
    if cancelled():
        return []
    if request.kind != 'news':
        rows = search_candidates(profile, f'{SITE_QUERIES[request.kind]} {topic}', max(1,timeout-5), cancelled)
    else:
        # Topic-first search yields article URLs. An alternate publisher query
        # covers searches dominated by news homepages and aggregate feeds.
        rows = search_candidates(profile, topic+' 新闻', max(1,timeout-5), cancelled)
        if (not any(canonical_source('news', row.get('url','')) for row in rows)
                and not cancelled() and deadline-time.monotonic()>5):
            rows = search_candidates(profile, topic+' 新华网 新闻报道', deadline-time.monotonic()-3, cancelled)
    if cancelled():
        return []
    entries={}
    for row in rows:
        url=canonical_source(request.kind,row.get('url',''))
        if url and url not in entries:
            entries[url]=row
    if not entries or time.monotonic()>=deadline:
        return []
    candidates = []
    pool=ThreadPoolExecutor(max_workers=5)
    try:
        jobs=[pool.submit(inspect_candidate,request,row,url,model_review=True)
              for url,row in list(entries.items())[:6]]
        done,_=wait(jobs,timeout=max(0,deadline-time.monotonic()))
        for job in jobs:
            if cancelled():
                return []
            if job not in done:
                continue
            try:
                candidate=job.result()
            except (OSError,ValueError,LookupError):
                continue
            if candidate and all(item.url != candidate.url for item in candidates):
                candidates.append(candidate)
    finally:
        pool.shutdown(wait=False,cancel_futures=True)
    return candidates
