"""Pure acknowledgement is repaired once into a concrete, useful reply."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config_store import ConfigStore, PersonaStore, StickerStore
from app.memory import MemoryStore
from app.model_client import LLMResult
from app.prompting import natural_dialogue_rule
from app.reply_fallbacks import content_free_reply
from app.service import BotService
from app.training import TrainingStore
from app.wechat_adapter import IncomingMessage
from tests.service_test import FakeAdapter


def main():
    assert content_free_reply('在的在的 Harry昊昊老师 阿洛娜一直都在哦', ('Harry昊昊','阿洛娜'))
    assert content_free_reply('嗯嗯，我在呢。')
    assert content_free_reply('确实，原来是这样。')
    assert not content_free_reply('听着挺憋屈的，被这样区别对待确实不舒服。')
    assert not content_free_reply('先备份 config.json，再改 active_profile_id。')
    assert not content_free_reply('今天是晴天呀。')
    assert content_free_reply('数学考试确实难。', (), '今天数学考试好难')
    assert not content_free_reply('这首歌很好听。', (), '你觉得这首歌怎么样')
    assert '不要整条只有附和' in natural_dialogue_rule({'name': '阿洛娜'})

    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        config = ConfigStore(root / 'config.json')
        config.bot.update(auto_sticker=False, web_search_enabled=False,
                          reply_delay_min=0, reply_delay_max=0,
                          global_cooldown=0, per_chat_cooldown=0,
                          max_reply_chars=40, max_sentence_chars=40)
        config.add_target('test', 'friend', 'arona')
        target = config.target_by_name('test')
        memory = MemoryStore(root / 'memory.db')
        training = TrainingStore(root / 'training.db', root / 'files')
        service = BotService(config, PersonaStore(root / 'personas.json'),
                             StickerStore(root / 'stickers.json'), memory, training,
                             admin_state_path=root / 'admin.json')
        adapter = FakeAdapter(config.data, lambda *_: None)
        service._adapter = adapter
        service._running = True
        filler = ('在的在的 小明老师 阿洛娜一直都在哦', {}, '',
                  {'agent': {'status': 'completed'}})
        try:
            incoming = IncomingMessage('test', '小明', '在吗', chat_type='friend')
            row = service._store_user(incoming, incoming.content)
            enriched = LLMResult('在的，小明老师。刚才那条 DeepSeek 新闻我看了，需要阿洛娜帮你总结重点吗？',
                                 'fixture', 'openai', 1)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult(filler[0], 'fixture', 'openai', 1), *filler[1:])), \
                 patch('app.service.model_call', return_value=enriched) as call:
                service._generate_and_send(incoming, target, row, incoming.content, force_reply=True)
            sent = ' '.join(text for _, text in adapter.sent)
            assert 'DeepSeek' in sent and '一直都在' not in sent, adapter.sent
            assert call.call_count == 1 and call.call_args.args[2] == '回复消息：补充有效信息'

            # A concrete reply is sent as-is and costs no extra model call.
            adapter.sent.clear()
            second = IncomingMessage('test', '小明', '怎么改模型配置', chat_type='friend')
            row2 = service._store_user(second, second.content)
            concrete = (LLMResult('先备份 config.json，再改 active_profile_id 就行。',
                                  'fixture', 'openai', 1), {}, '',
                        {'agent': {'status': 'completed'}})
            with patch.object(service, '_model_reply', return_value=concrete), \
                 patch('app.service.model_call') as call2:
                service._generate_and_send(second, target, row2, second.content, force_reply=True)
                assert call2.call_count == 0
            assert any('config.json' in text for _, text in adapter.sent), adapter.sent

            # A repair that is still filler keeps the original instead of losing the reply.
            adapter.sent.clear()
            third = IncomingMessage('test', '小明', '在吗', chat_type='friend')
            row3 = service._store_user(third, third.content)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult(filler[0], 'fixture', 'openai', 1), *filler[1:])), \
                 patch('app.service.model_call', return_value=LLMResult('嗯嗯，我在呢。', 'fixture', 'openai', 1)):
                service._generate_and_send(third, target, row3, third.content, force_reply=True)
            assert any('一直都在' in text for _, text in adapter.sent), adapter.sent
        finally:
            service.shutdown()
            memory.close()
            training.close()
    print('REPLY SUBSTANCE TESTS PASSED')


if __name__ == '__main__':
    main()
