"""Tool-call wrappers execute internally and never become WeChat bubbles."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.agent import AgentRunner,AgentTool,_action
from app.model_client import LLMResult
from app.tool_protocol import internal_output,parse_action
from app.prompting import parse_reply
from app.wechat_adapter import NativeWeChatAdapter,IncomingMessage
from app.config_store import ConfigStore,PersonaStore,StickerStore
from app.memory import MemoryStore
from app.training import TrainingStore
from app.service import BotService
from tests.service_test import FakeAdapter


def result(text):return LLMResult(text,'fixture','mock',1)


DSML = '''<｜DSML｜function_calls>
<｜DSML｜invoke name="choose_reply_medium">
<｜DSML｜parameter name="arguments" string="false">{"kind":"voice"}</｜DSML｜parameter>
</｜DSML｜invoke>
</｜DSML｜function_calls>'''


def main():
    body={'action':'tool','tool':'search_web','arguments':{'query':'蔚蓝档案 国服 官方 最新公告 2026年11月'}}
    wrapped='<tool_call>'+json.dumps(body,ensure_ascii=False)+'</tool_call>'
    variants=[wrapped,'```json\n'+json.dumps(body)+'\n```','<tool_call>'+json.dumps({'name':'search_web','arguments':body['arguments']})+'</tool_call>']
    for value in variants:
        assert internal_output(value) and _action(value)['tool']=='search_web'
        assert parse_reply(value,[])==('',None)
        execute=Mock(return_value='实际网页结果')
        call=Mock(side_effect=[result(value),result('{"action":"final","text":"国服公告已经更新。"}')])
        run=AgentRunner().run(call,[], '',[AgentTool('search_web','query','搜索',execute,True)])
        assert run.result.text=='国服公告已经更新。' and execute.call_count==1
    call=Mock(side_effect=[result(json.dumps({'action':'final','text':wrapped})),result('这次先核对公告日期。')])
    assert AgentRunner().run(call,[],'',[]).result.text=='这次先核对公告日期。'
    native=NativeWeChatAdapter({},lambda _:None)
    assert not native.send_text('test',wrapped).ok
    assert not native.send_quoted_text('test',wrapped,quote_text='原消息').ok
    double=DSML.replace('｜DSML｜','｜｜DSML｜｜').replace('function_calls','calls')
    # Exact escaped, line-wrapped syntax reported from a real chat bubble.
    escaped='''<｜｜DSML｜｜ calls>\\
<｜｜DSML｜｜ invoke name\\
\\="choose_reply_medium">\\
<｜｜DSML｜｜ parameter\\
name="arguments"\\
string="false">{"kind":\\
"voice"}\\</｜｜DSML｜｜\\
parameter>\\
\\</｜｜DSML｜｜ invoke>\\
\\</｜｜DSML｜｜ calls>'''
    request_param=DSML.replace('name="arguments"','name="request"')
    direct=DSML.replace('name="arguments" string="false">{"kind":"voice"}',
                        'name="kind" string="true">voice')
    for value in [DSML,double,escaped,request_param,direct,DSML.replace('｜','|')]:
        assert internal_output(value)
        assert parse_reply(value,[])==('',None)
        assert not native.send_text('test',value).ok
        assert not native.send_quoted_text('test',value,quote_text='原消息').ok
        execute=Mock(return_value='语音已准备，等待最终正文。')
        call=Mock(side_effect=[result(value),result('{"action":"final","text":"老师，你好呀！"}')])
        run=AgentRunner().run(call,[],'',[
            AgentTool('choose_reply_medium','request','选择回复形式',execute)])
        assert run.status=='completed' and run.result.text=='老师，你好呀！',value
        execute.assert_called_once()
        assert json.loads(execute.call_args.args[0])=={'kind':'voice'}
    # A DSML search keeps the exact registered query string signature.
    search=DSML.replace('choose_reply_medium','search_web').replace('{"kind":"voice"}','{"query":"公开主题"}')
    assert parse_action(search,tool_arguments={'search_web':'query'})['arguments']=={'query':'公开主题'}
    malformed=[DSML[:-10],DSML+'额外正文','先做这些：'+DSML,
               DSML.replace('</｜DSML｜invoke>','<｜DSML｜parameter name="arguments">重复</｜DSML｜parameter></｜DSML｜invoke>'),
               DSML.replace('</｜DSML｜function_calls>',DSML.split('\n',1)[1]),
               '<!DOCTYPE calls>'+DSML]
    for value in malformed:
        assert internal_output(value) and parse_action(value)=={'action':'invalid'}
        assert not native.send_text('test',value).ok
        call=Mock(side_effect=[result(value),result('老师，你好呀！')])
        execute=Mock()
        run=AgentRunner().run(call,[],'',[AgentTool('choose_reply_medium','request','选择',execute)])
        assert run.result.text=='老师，你好呀！'
        execute.assert_not_called()
    # Even a final JSON response cannot smuggle a tool envelope into a bubble.
    call=Mock(side_effect=[result(json.dumps({'action':'final','text':DSML})),result('你好！')])
    assert AgentRunner().run(call,[],'',[]).result.text=='你好！'
    call=Mock(return_value=result(DSML))
    assert AgentRunner().run(call,[],'',[],max_steps=1).result is None
    assert not internal_output('工具会查询公开网页，再根据正文回答。')
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder);config=ConfigStore(root/'config.json');config.add_target('test','group','arona')
        config.bot.update(auto_sticker=False,voice_enabled=False,reply_delay_min=0,reply_delay_max=0,global_cooldown=0)
        service=BotService(config,PersonaStore(root/'p.json'),StickerStore(root/'s.json'),MemoryStore(root/'m.db'),TrainingStore(root/'t.db',root/'files'),admin_state_path=root/'admin.json')
        adapter=FakeAdapter(config.wechat,lambda _:None);service._adapter=adapter;service._running=True
        incoming=IncomingMessage('test','群友','@ARONA 国服有消息吗',chat_type='group')
        try:
            row=service._store_user(incoming,incoming.content)
            with patch.object(service,'_model_reply',return_value=(result(wrapped),{},'',{})):
                service._generate_and_send(incoming,config.target_by_name('test'),row,incoming.content,True)
            assert adapter.sent and all(not internal_output(text) for _,text in adapter.sent)
            assert all('tool_call' not in text and 'arguments' not in text for _,text in adapter.sent)
        finally:service._running=False;service.memory.close();service.training.close()
    print('INTERNAL TOOL PROTOCOL LEAK TESTS PASSED')


if __name__=='__main__':main()
