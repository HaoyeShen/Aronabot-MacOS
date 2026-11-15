"""Probability precedes every semantic call; misses still build the dialogue."""
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config_store import ConfigStore, PersonaStore, StickerStore
from app.memory import MemoryStore
from app.model_client import LLMResult
from app.service import BotService
from app.training import TrainingStore
from app.wechat_adapter import IncomingMessage
from tests.service_test import FakeAdapter


def main():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        config = ConfigStore(base/'config.json')
        assert config.bot['probability_first_reply'] is True
        assert config.bot['group_reply_probability'] == .03
        group = config.add_target('test', 'group', 'arona')
        friend = config.add_target('friend', 'friend', 'arona')
        assert config.target_by_name('test')['group_reply_probability'] == .03
        assert friend['reply_probability'] == .03
        config.bot.update(per_chat_cooldown=0, global_cooldown=0, quiet_hours_enabled=False)
        memory = MemoryStore(base/'memory.db')
        training = TrainingStore(base/'training.db', base/'files')
        service = BotService(config, PersonaStore(base/'personas.json'), StickerStore(base/'stickers.json'),
                             memory, training, admin_state_path=base/'admin.json')
        adapter = FakeAdapter(config, lambda _: None)
        adapter.self_name = 'ARONA'
        service._adapter, service._running = adapter, True
        def turn(key, text='阿洛娜，在吗', **kw):
            return IncomingMessage('test', '群友', text, chat_type='group', external_id='wx:prob:'+key, **kw)
        try:
            with patch('app.service.random.random', return_value=.03) as draw, patch.object(service, '_probability_reply_allowed', side_effect=AssertionError('No model routing gate')), patch.object(service, '_keyword_addressed', side_effect=AssertionError('No semantic keyword gate')), patch.object(service, '_generate_and_send') as send:
                service._handle_incoming(turn('miss','大家好'))
                service._handle_incoming(turn('miss','大家好'))
                assert draw.call_count == 1 and not send.called
                service._handle_incoming(turn('keyword','阿洛娜，在吗'))
                assert draw.call_count == 1 and send.call_count == 1
                service._handle_incoming(turn('native-at','你好',mentions_self=True))
                assert draw.call_count == 1 and send.call_count == 2
                assert send.call_args.kwargs['force_reply'] and not send.call_args.kwargs['start_followup']
                service._followups['test']={'last_activity':time.monotonic(),'misses':0,'seen':[]}
                service._handle_incoming(turn('follow','那接下来呢'))
                assert draw.call_count == 2 and send.call_count == 2
            config.bot.update(group_probability_reply=False,per_chat_cooldown=600)
            service._last_reply_at['test']=time.time()
            with patch('app.service.random.random', return_value=.99) as draw, patch.object(service,'_generate_and_send') as send:
                service._handle_incoming(turn('at-zero','@ARONA 你好'))
                service._handle_incoming(turn('keyword-zero','arona 在吗'))
                assert send.call_count == 2 and draw.call_count == 0
                service._handle_incoming(turn('ordinary-zero','继续'))
                assert send.call_count == 2
            config.bot.update(group_probability_reply=True,per_chat_cooldown=600)
            config.target_by_name('test')['group_reply_probability']=1
            with patch('app.service.random.random',return_value=.999), patch.object(service,'_probability_reply_allowed',side_effect=AssertionError('No second veto')), patch.object(service,'_generate_and_send') as send:
                service._handle_incoming(turn('hit','大家看看这个'))
                service._handle_incoming(turn('hit2','@张三 你好'))
                assert send.call_count == 2, 'ordinary hits ignore previous-chat cooldown and audience classification'
            with patch('app.service.random.random',return_value=.029) as draw, patch.object(service,'_generate_and_send') as send:
                service._handle_incoming(IncomingMessage('friend','昵称','你好',external_id='wx:private'))
                draw.assert_called_once();send.assert_called_once()
            with patch('app.service.random.random') as draw, patch.object(service,'_generate_and_send') as send:
                config.bot['auto_reply']=False
                service._handle_incoming(turn('paused'))
                config.bot['auto_reply']=True
                with patch.object(service,'_in_quiet_hours',return_value=True):service._handle_incoming(turn('quiet'))
                service._handle_incoming(turn('stale',received_at=time.time()-3600))
                service._handle_incoming(turn('self',direction='out'))
                draw.assert_not_called();send.assert_not_called()
            # Missing fields migrate; invalid values never become 100%.
            raw = json.loads(config.path.read_text(encoding='utf-8'))
            raw['bot'].pop('probability_first_reply', None)
            raw['bot']['group_reply_probability'] = float('nan')
            raw['targets'][0]['group_reply_probability'] = float('nan')
            config.path.write_text(json.dumps(raw), encoding='utf-8')
            migrated = ConfigStore(config.path)
            assert migrated.bot['probability_first_reply'] is True
            assert migrated.bot['group_reply_probability'] == .03
            assert migrated.targets()[0]['group_reply_probability'] == .03
        finally:
            service.stop(); memory.close(); training.close()
    print('PROBABILITY REPLY TEST PASSED')


if __name__ == '__main__': main()
