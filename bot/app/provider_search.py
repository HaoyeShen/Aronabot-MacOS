"""DeepSeek public search as an optional provider; original channels remain available."""
from __future__ import annotations
from datetime import datetime
import logging,time,urllib.parse
from .web_search import WebSearch,WebPage,normalize_query
from .web_search import _url as public_page_url
from .model_client import ModelClient
log=logging.getLogger(__name__)

class ProviderSearch(WebSearch):
    def __init__(self,profile):super().__init__();self.profile=profile
    def search(self,query,*,fresh=False,cancelled=lambda:False,timeout_seconds=20,include_baike=False,only_baike=False,selector=None):
        profile=self.profile();query=normalize_query(query)
        supported=(urllib.parse.urlsplit(profile.get('base_url','')).hostname=='api.deepseek.com' and bool(profile.get('api_key_enc')))
        if not query or cancelled():return []
        if not supported:return super().search(query,fresh=fresh,cancelled=cancelled,timeout_seconds=timeout_seconds,include_baike=include_baike,only_baike=only_baike,selector=selector)
        key=('deepseek',query,only_baike)
        with self._lock:cached=self._cache.get(key)
        if cached and not fresh and time.monotonic()-cached[0]<300:
            self._status.report=cached[2];return list(cached[1])
        try:
            client=ModelClient(profile)
            actual=('site:baike.baidu.com '+query) if only_baike else query
            data=client._request('https://api.deepseek.com/v1/tools/search','POST',
                {'query':actual[:128],'count':6,'need_content':True},timeout=max(1,min(30,int(timeout_seconds))))
            if cancelled():return []
            rows=data.get('results',[]);pages=[];candidates=[]
            for index,row in enumerate(rows):
                url=public_page_url(row.get('url',''));content=str(row.get('content') or '').strip()
                if not url or len(content)<80:continue
                page=WebPage(url,str(row.get('title') or '')[:180],content[:12000],datetime.now().astimezone().isoformat(timespec='seconds'))
                pages.append(page);candidates.append({'id':index,'url':url,'title':page.title,'text':page.content[:1800]})
            decisions=[]
            if selector and candidates:
                decisions=selector(query,'正文复核',candidates,4,max(1,timeout_seconds-2))
                allowed={d['id'] for d in decisions if d['selected']}
                pages=[page for page,candidate in zip(pages,candidates) if candidate['id'] in allowed]
            report={'channels_attempted':1,'pages':len(pages),'candidates':len(rows),'selection_mode':'model' if selector else 'provider',
                    'selection_errors':0,'blocked':0,'unreadable':len(rows)-len(candidates),'decisions':decisions,
                    'channels':{'deepseek':{'state':'results' if pages else 'empty','count':len(pages)}}}
            self._status.report=report
            if pages:
                with self._lock:self._cache[key]=(time.monotonic(),list(pages),report)
                return pages[:4]
        except Exception as exc:log.warning('DeepSeek 搜索通道未完成：%s',type(exc).__name__)
        return super().search(query,fresh=fresh,cancelled=cancelled,timeout_seconds=timeout_seconds,include_baike=include_baike,only_baike=only_baike,selector=selector)
