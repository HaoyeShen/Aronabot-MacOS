"""Provider safety envelopes never reach bubbles, tools, voice or WeChat."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent_runtime import RUNTIME
from app.model_client import ModelError, make_client
from app.prompting import parse_reply
from app.provider_text import contains_provider_envelope, strip_provider_envelope
from app.tool_protocol import internal_output, parse_action

LEAK = ("\n\n<ds_safety>[用户未成年]否\n[分类]其他\n"
        "[判定]用户仅请求发送一个微信原生动画表情，内容中性，不涉及政治敏感话题、人物或事件。\n"
        "[规则]无</ds_safety>Safe")
TOOL = '{"action":"tool","tool":"list_native_stickers","arguments":{"query":"开心 元气 打招呼"}}'


def main():
    assert strip_provider_envelope(LEAK) == ''
    assert contains_provider_envelope(LEAK) and not contains_provider_envelope('老师好呀。')
    assert internal_output(LEAK) and not internal_output('老师好呀。')
    # Real protocol that follows the envelope must still work.
    action = parse_action(LEAK + '\n\n' + TOOL)
    assert action == {'action': 'tool', 'tool': 'list_native_stickers',
                      'arguments': {'query': '开心 元气 打招呼'}}, action
    assert parse_reply(LEAK + '\n\n今天也要开心呀。', []) == ('今天也要开心呀。', None)
    assert parse_reply(LEAK, []) == ('', None)
    # Partial or unclosed provider metadata is dropped rather than spoken.
    assert strip_provider_envelope('前言\n<ds_safety>[分类]其他') == '前言'
    assert strip_provider_envelope('</ds_safety>Safe\n好的') == '好的'
    # The provider boundary removes the envelope before any caller sees text.
    client = make_client({'provider': 'openai', 'model': 'fixture',
                          'base_url': 'https://api.deepseek.com',
                          'api_key_enc': '', 'timeout': 5})
    payload = {'choices': [{'message': {'content': LEAK + '\n\n好的呀。'}}],
               'usage': {'prompt_tokens': 1, 'completion_tokens': 1}}
    with patch.object(client, '_with_retry', return_value=(payload, 1)):
        with RUNTIME.context('provided'):
            assert client.chat([{'role': 'user', 'content': '在吗'}]).text == '好的呀。'
    empty = {'choices': [{'message': {'content': LEAK}}], 'usage': {}}
    with patch.object(client, '_with_retry', return_value=(empty, 1)):
        with RUNTIME.context('provided'):
            try:
                client.chat([{'role': 'user', 'content': '在吗'}])
            except ModelError as exc:
                assert 'provider safety envelope' in exc.detail
            else:
                raise AssertionError('envelope-only output must not become a reply')
    print('PROVIDER TEXT TESTS PASSED')


if __name__ == '__main__':
    main()
