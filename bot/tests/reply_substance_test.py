"""Pure acknowledgement is repaired once into a concrete, useful reply."""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.chat_bubbles import strip_leading_address, strip_questions, trim_interjections
from app.config_store import ConfigStore, PersonaStore, StickerStore
from app.memory import MemoryStore
from app.model_client import LLMResult
from app.prompting import natural_dialogue_rule
from app.reply_fallbacks import bare_opener, content_free_reply, question_only_reply
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
    assert content_free_reply('Harry昊昊老师 阿洛娜在哦 今天有什么想聊的？', ('Harry昊昊','阿洛娜'), '在吗')
    assert not content_free_reply('阿洛娜在哦 想查资料、看文件，还是聊点游戏？', ('阿洛娜',), '在吗')
    assert not content_free_reply('这首歌很好听。', (), '你觉得这首歌怎么样')
    assert '不要整条只有附和' in natural_dialogue_rule({'name': '阿洛娜'})
    assert bare_opener('在吗？') and not bare_opener('在吗，帮我看看文件')
    assert question_only_reply('想查资料、看文件 还是聊点游戏？')
    assert strip_questions('新闻我看过了，需要总结吗？') == '新闻我看过了'
    assert strip_questions('文档：https://example.com/a?x=1') == '文档：https://example.com/a?x=1'
    assert trim_interjections('嘿嘿，交给我吧。') == '交给我吧。'
    assert trim_interjections('阿洛娜一直守着消息呢 嘿嘿') == '阿洛娜一直守着消息呢'
    assert trim_interjections('哈尔滨今天降温了。') == '哈尔滨今天降温了。'
    assert strip_leading_address('Harry昊昊老师 阿洛娜在', 'Harry昊昊老师',
                                 ('Harry昊昊', '老师')) == '阿洛娜在'
    assert not question_only_reply('新闻我看过了，要总结吗？')

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
            third = IncomingMessage('test', '小明', '今天数学考试好难', chat_type='friend')
            row3 = service._store_user(third, third.content)
            echo = (LLMResult('数学考试确实难。', 'fixture', 'openai', 1), {}, '',
                    {'agent': {'status': 'completed'}})
            with patch.object(service, '_model_reply', return_value=echo), \
                 patch('app.service.model_call', return_value=LLMResult('嗯嗯，我在呢。', 'fixture', 'openai', 1)):
                service._generate_and_send(third, target, row3, third.content, force_reply=True)
            assert any('数学考试确实难' in text for _, text in adapter.sent), adapter.sent

            # A forced @/keyword reply still goes out when the optional
            # substance repair fails; it must never suppress the reply.
            adapter.sent.clear()
            fourth = IncomingMessage('test', '小明', '@阿洛娜 在吗', chat_type='group', mentions_self=True)
            row4 = service._store_user(fourth, fourth.content)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult('小明老师，阿洛娜在哦，有事吗？', 'fixture', 'openai', 1),
                                            {}, '', {'agent': {'status': 'completed'}})), \
                 patch('app.service.model_call', side_effect=TimeoutError('slow')):
                service._generate_and_send(fourth, target, row4, '在吗', force_reply=True)
            # A forced @ reply is still delivered, and it does not add a
            # proactive question when the repair is unavailable.
            joined = ' '.join(text for _, text in adapter.sent)
            assert adapter.sent and '？' not in joined and '在' in joined, adapter.sent

            # A repair that is only a question is rejected; the bare opener
            # gets a short statement without a proactive question.
            adapter.sent.clear()
            fifth = IncomingMessage('test', '小明', '在吗', chat_type='friend')
            row5 = service._store_user(fifth, fifth.content)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult('小明老师，阿洛娜在哦。', 'fixture', 'openai', 1),
                                            {}, '', {'agent': {'status': 'completed'}})), \
                 patch('app.service.model_call',
                       return_value=LLMResult('想查资料、看文件 还是聊点游戏？', 'fixture', 'openai', 1)):
                service._generate_and_send(fifth, target, row5, fifth.content, force_reply=True)
            joined = ' '.join(text for _, text in adapter.sent)
            assert joined in ('在', '在的。'), adapter.sent

            # A statement plus a clarifying question keeps the statement only.
            adapter.sent.clear()
            sixth = IncomingMessage('test', '小明', '今天数学考试好难', chat_type='friend')
            row6 = service._store_user(sixth, sixth.content)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult('数学考试确实难，是哪部分卡住了？',
                                                      'fixture', 'openai', 1),
                                            {}, '', {'agent': {'status': 'completed'}})):
                service._generate_and_send(sixth, target, row6, sixth.content, force_reply=True)
            joined = ' '.join(text for _, text in adapter.sent)
            assert joined and '？' not in joined and '数学考试确实难' in joined, adapter.sent

            # Filler interjections at the edges are removed before sending.
            adapter.sent.clear()
            seventh = IncomingMessage('test', '小明', '今天数学考试好难', chat_type='friend')
            row7 = service._store_user(seventh, seventh.content)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult('嘿嘿，数学考试确实难，先缓一缓。',
                                                      'fixture', 'openai', 1),
                                            {}, '', {'agent': {'status': 'completed'}})):
                service._generate_and_send(seventh, target, row7, seventh.content, force_reply=True)
            joined = ' '.join(text for _, text in adapter.sent)
            assert joined and '嘿嘿' not in joined and '数学考试确实难' in joined, adapter.sent

            # The local human-style summary is appended to the reply prompt.
            adapter.sent.clear()
            ninth = IncomingMessage('test', '小明', '在吗', chat_type='friend')
            row9 = service._store_user(ninth, ninth.content)
            captured = {}
            def capture(*args, **kwargs):
                captured['system'] = args[2] if len(args) > 2 else kwargs.get('system', '')
                return (LLMResult('知道了。', 'fixture', 'openai', 1), {}, '',
                        {'agent': {'status': 'completed'}})
            with patch.object(service, '_human_style_block',
                              return_value='【本机人类聊天语感】MARKER'), \
                 patch.object(service, '_model_reply', side_effect=capture):
                service._generate_and_send(ninth, target, row9, ninth.content, force_reply=True)
            assert 'MARKER' in captured.get('system', ''), captured

            # Service offers are removed before the text reaches WeChat.
            adapter.sent.clear()
            tenth = IncomingMessage('test', '小明', '今天数学考试好难', chat_type='friend')
            row10 = service._store_user(tenth, tenth.content)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult('数学考试确实难。交给我吧。', 'fixture', 'openai', 1),
                                            {}, '', {'agent': {'status': 'completed'}})):
                service._generate_and_send(tenth, target, row10, tenth.content, force_reply=True)
            joined = ' '.join(text for _, text in adapter.sent)
            assert '交给我' not in joined and '数学考试确实难' in joined, adapter.sent

            # A redundant leading address is dropped from short replies.
            adapter.sent.clear()
            eleventh = IncomingMessage('test', '小明', '配置改好了吗', chat_type='friend')
            row11 = service._store_user(eleventh, eleventh.content)
            with patch.object(service, '_model_reply',
                              return_value=(LLMResult('小明老师，改好了。', 'fixture', 'openai', 1),
                                            {}, '', {'agent': {'status': 'completed'}})):
                service._generate_and_send(eleventh, target, row11, eleventh.content, force_reply=True)
            joined = ' '.join(text for _, text in adapter.sent)
            assert joined.startswith('改好了') and '小明老师' not in joined, adapter.sent

            # Model line breaks are respected and a proper name is not cut in
            # half; a trailing comma is not left dangling in a bubble.
            sample = ('在的\n\n视频号这边阿洛娜只看得到标题，猜是才羽桃井的整活剪辑'
                      '——冻牛奶切刀听着就很游戏开发部')
            bubbles = service._split_reply_messages(sample, [], False, 30, 30)
            assert bubbles[0] == '在的', bubbles
            assert any('才羽桃井' in part for part in bubbles), bubbles
            assert not any(part.startswith('羽桃井') for part in bubbles), bubbles
            assert not any(part.endswith(('，', ',')) for part in bubbles), bubbles

            # Short replies use at most two bubbles; longer information may use more.
            short_bubbles = service._split_reply_messages('一'*20 + '，' + '二'*20, [], False, 25, 25)
            assert short_bubbles and len(short_bubbles) <= 2, short_bubbles
            long_bubbles = service._split_reply_messages(
                '一'*20 + '，' + '二'*20 + '，' + '三'*20 + '，' + '四'*20, [], False, 25, 25)
            assert len(long_bubbles) <= 4, long_bubbles
        finally:
            service.shutdown()
            memory.close()
            training.close()
    print('REPLY SUBSTANCE TESTS PASSED')


if __name__ == '__main__':
    main()
