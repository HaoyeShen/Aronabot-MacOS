"""Explicit typed requests deliver one verified URL through the normal reply path."""
from pathlib import Path
import tempfile
import time
from unittest.mock import Mock, patch

from app.config_store import ConfigStore, PersonaStore, StickerStore
from app.memory import MemoryStore
from app.model_client import LLMResult
from app.requested_share import ShareLink, ShareRequest, canonical_source, inspect_candidate, parse_share_request
from app.service import BotService
from app.training import TrainingStore
from app.wechat_adapter import IncomingMessage
from tests.service_test import FakeAdapter


def main():
    assert parse_share_request('@阿洛娜 发个 Python 入门视频给我看看', ['阿洛娜']) == ShareRequest('video', 'Python 入门')
    assert parse_share_request('发首周杰伦《晴天》') == ShareRequest('music', '周杰伦 晴天')
    assert parse_share_request('发一首古典音乐') == ShareRequest('music', '古典音乐')
    assert parse_share_request('给我发一条最新的航天新闻') == ShareRequest('news', '航天', 168)
    assert parse_share_request('把故宫建筑的公众号推文发给我').kind == 'article'
    for text in ('别发 Python 视频', '小王说：给我发个视频', '发视频给张三', '@小王 发一条新闻',
                 '怎么发新闻链接', '你发了一个 Python 视频', '给我发一个视频，但是不要上网搜索'):
        assert parse_share_request(text, ['阿洛娜']) is None, text

    video = 'https://www.bilibili.com/video/BV1Jgf6YvE8e/'
    assert canonical_source('video',video+'?spm=abc') == video
    assert not canonical_source('video','https://www.bilibili.com.example.org/video/BV1Jgf6YvE8e/')
    assert not canonical_source('music','https://y.qq.com/n/ryqq_v2/singer/0025NhlN2yWrP4')
    assert not canonical_source('news','https://tv.cctv.com/2026/08/20/VIDE8DhWuu0zoZGlFdY2.shtml')
    article = 'https://mp.weixin.qq.com/s?__biz=YWJjZA%3D%3D&mid=123&idx=1&sn=abcdef'
    assert canonical_source('article',article.replace('https','http',1)+'&poc_token=private') == article
    with patch('app.requested_share.fetch_public',return_value=(b'<html></html>','utf-8','https://mp.weixin.qq.com/mp/wappoc_appmsgcaptcha')):
        request = ShareRequest('article','故宫 建筑')
        row = {'title':'故宫建筑','content':'故宫建筑历史与特色。'*30,'date':'2026-11-01'}
        assert inspect_candidate(request,row,article) is None
        indexed = inspect_candidate(request,{**row,'provider_index':True},article)
        assert indexed and indexed.indexed and indexed.url == article
        assert inspect_candidate(ShareRequest('article','量子计算'),{**row,'provider_index':True},article) is None

    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp)
        cfg=ConfigStore(root/'config.json')
        cfg.add_target('fixture','group','arona')
        cfg.bot.update(group_probability_reply=False,quiet_hours_enabled=False,web_search_enabled=True)
        memory=MemoryStore(root/'memory.db')
        training=TrainingStore(root/'training.db',root/'files')
        service=BotService(cfg,PersonaStore(root/'personas.json'),StickerStore(root/'stickers.json'),
                           memory,training,admin_state_path=root/'admin.json')
        adapter=FakeAdapter(cfg,lambda _:None)
        service._adapter,service._running=adapter,True
        def incoming(text, number, sender='访客'):
            return IncomingMessage('fixture',sender,text,chat_type='group',
                                   external_id=f'wx:share:{number}',received_at=time.time())

        def answer(text):
            return LLMResult(text,'test-model','mock',0)

        try:
            model = Mock(side_effect=[
                answer('{"action":"ask","kind":"video"}'),
                answer('{"action":"search","kind":"video","topic":"蔚蓝档案","query":"Blue Archive 官方短片","freshness":"any"}'),
                answer('{"action":"select","id":2}'),
                answer('{"action":"search","kind":"video","topic":"蔚蓝档案","query":"蔚蓝档案 PV","freshness":"any"}'),
            ])
            candidates = [ShareLink('另一条','https://www.bilibili.com/video/BV1rpWjevEip/'),
                          ShareLink('蔚蓝档案官方短片',video)]
            with patch('app.model_requested_share.model_call',model), patch(
                    'app.model_requested_share.collect_shares',return_value=candidates) as lookup:
                service._handle_incoming(incoming('给我推荐一个视频吧',1))
                assert '说一下想看的' in adapter.sent[-1][1] and '？' not in adapter.sent[-1][1]
                service._handle_incoming(incoming('蔚蓝档案',2,'另一人'))
                assert model.call_count == 1 and not lookup.called
                item = incoming('蔚蓝档案',3)
                service._handle_incoming(item)
                service._handle_incoming(item)
                lookup.assert_called_once()
                assert lookup.call_args.args[1] == 'Blue Archive 官方短片'
                assert adapter.sent[-1] == ('fixture','蔚蓝档案官方短片\n'+video)
                assert model.call_count == 3
                cfg.bot['web_search_enabled']=False
                service._handle_incoming(incoming('给我推荐一个关于蔚蓝档案的视频 直接发链接',4))
                lookup.assert_called_once()
                assert '关闭了联网' in adapter.sent[-1][1]
        finally:
            memory.close()
            training.close()
    print('REQUESTED SHARE ROUTING AND SOURCE FILTERS PASSED')


if __name__ == '__main__':
    main()
