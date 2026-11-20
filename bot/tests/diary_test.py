"""Daily privacy, clock, persistent idempotency and uncertain-post recovery."""
import sys,tempfile,json
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timedelta
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.diary import DailyDiary,CHINA
from app.config_store import ConfigStore,PersonaStore
from app.memory import MemoryStore
from app.model_client import LLMResult
from app.wechat_adapter import SendResult
import threading,queue


def main():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);cfg=ConfigStore(root/'cfg.json');memory=MemoryStore(root/'memory.db')
        cfg.bot['diary_enabled']=True
        adapter=SimpleNamespace(connected=True,publish_moment=Mock(return_value=SendResult(True,'日记已发表')))
        service=SimpleNamespace(config=cfg,memory=memory,personas=PersonaStore(root/'personas.json'),
            _running=True,_reply_busy=False,_incoming=queue.Queue(),adapter=adapter,_adapter=adapter,
            _adapter_lock=threading.RLock(),_record_usage=Mock(),emit=Mock())
        diary=DailyDiary(service,root/'diary.json')
        now=datetime.now(CHINA).replace(hour=22,minute=0,second=0,microsecond=0)
        memory.add_user('私人群','私密聊天原文',sender='私密昵称')
        memory.add_assistant('私人群','真实但不能公开的回答',meta={'voice_sent':True})
        fake=Mock();fake.chat.return_value=LLMResult('今天陪老师聊了一会儿，也试着用声音回应。能把想说的话好好传达出去，阿洛娜就很开心啦。','fixture','mock',1)
        try:
            with patch('app.diary.make_client',return_value=fake):
                diary.tick(now.replace(hour=21,minute=59));adapter.publish_moment.assert_not_called()
                diary.tick(now)
                assert adapter.publish_moment.call_count==1 and fake.chat.call_count==1
                prompt=str(fake.chat.call_args.args)
                assert all(s not in prompt for s in ['私人群','私密昵称','私密聊天原文','真实但不能公开的回答'])
                assert 'voices' in prompt and 'replies' in prompt
                assert diary.load()[now.date().isoformat()]['status']=='published'
                diary.tick(now)
                DailyDiary(service,root/'diary.json').tick(now)
                assert adapter.publish_moment.call_count==1
            # State corruption must never reset the daily sent marker.
            (root/'diary.json').write_text('{broken')
            diary.retry_after=0;diary.tick(now)
            assert adapter.publish_moment.call_count==1
            # A result whose commit is uncertain is never automatically retried.
            other=DailyDiary(service,root/'other.json')
            adapter.publish_moment.return_value=SendResult(False,'结果待核对','no response',status='unconfirmed')
            with patch('app.diary.make_client',return_value=fake):
                other.tick(now);other.retry_after=0;other.tick(now)
                assert adapter.publish_moment.call_count==2
                assert other.load()[now.date().isoformat()]['status']=='uncertain'
            # Arm the schedule before 22:00, then resume the next morning
            # with the cloud unavailable and ordinary replies still queued.
            adapter.publish_moment.reset_mock()
            adapter.publish_moment.return_value=SendResult(True,'服务器已确认',metadata={'post':{'post_id':'123'}})
            overnight=DailyDiary(service,root/'overnight.json')
            dawn=now+timedelta(hours=8)
            service._reply_busy=True
            with patch('app.diary.make_client',side_effect=ConnectionError('offline')):
                assert overnight.tick(now-timedelta(minutes=1)) is None
                assert overnight.tick(dawn)['ok']
                assert overnight.load()[now.date().isoformat()]['post_id']=='123'
                assert adapter.publish_moment.call_args.args[0].startswith(f'【阿洛娜的今日日记 · {now.date()}】')
                assert overnight.tick(dawn)['already_published']
                assert adapter.publish_moment.call_count==1
            service._reply_busy=False
            first_install=DailyDiary(service,root/'new.json')
            assert first_install.tick(dawn) is None
            adapter.publish_moment.reset_mock()
            manual=DailyDiary(service,root/'manual.json');cfg.bot['diary_enabled']=False
            adapter.publish_moment.return_value=SendResult(True,'手动日记已发布')
            with patch('app.diary.make_client',return_value=fake),patch('app.diary.diary_now',return_value=now.replace(hour=10)):
                result=manual.publish_now()
                assert result['ok'] and adapter.publish_moment.call_count==1,'manual button bypasses time/automatic switch'
                assert manual.publish_now()['already_published'] and adapter.publish_moment.call_count==1
        finally:memory.close()
    print('DIARY TEST PASSED')


if __name__=='__main__':main()
