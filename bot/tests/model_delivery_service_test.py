"""Native model choices survive persistence; uncertain voice never duplicates a send."""
from pathlib import Path
import json,tempfile
from unittest.mock import Mock,patch
import numpy as np
from PIL import Image
from app.config_store import ConfigStore,PersonaStore,StickerStore
from app.memory import MemoryStore
from app.training import TrainingStore
from app.service import BotService
from app.wechat_adapter import BaseWeChatAdapter,IncomingMessage,SendResult
from app.model_client import LLMResult
from app.tts import AudioClip
from tests.tool_protocol_test import DSML

class Adapter(BaseWeChatAdapter):
    model_delivery=True
    def __init__(self,config):
        super().__init__(config,lambda _:None);self.connected=True;self.self_name='阿洛娜';self.sent=[]
        self.voice_result=SendResult(True,status='acknowledged')
    def send_text(self,chat,text):self.sent.append(('text',text));return SendResult(True,status='acknowledged')
    def send_voice(self,chat,path):self.sent.append(('voice',str(path)));return self.voice_result
    def send_image(self,chat,path):self.sent.append(('image',str(path)));return SendResult(True,status='acknowledged')
    def send_native_sticker(self,chat,entry,**kwargs):self.sent.append(('sticker',entry['id']));return SendResult(True,status='acknowledged')
    def fetch_recent(self,*_):return []
    def stop(self):self.connected=False

def main():
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp);config=ConfigStore(root/'config.json')
  config.data['model_profiles']=[{'id':'fixture','provider':'openai','model':'fixture','supports_vision':True}]
  config.data['active_profile_id']='fixture'
  config.bot.update(auto_sticker=True,native_sticker_enabled=True,web_search_enabled=False,
     reply_delay_min=0,reply_delay_max=0,global_cooldown=0,per_chat_cooldown=0,max_reply_chars=23,max_sentence_chars=23)
  config.add_target('test','group','arona');target=config.target_by_name('test')
  memory=MemoryStore(root/'memory.db');training=TrainingStore(root/'training.db',root/'files')
  service=BotService(config,PersonaStore(root/'personas.json'),StickerStore(root/'stickers.json'),memory,training,admin_state_path=root/'admin.json')
  adapter=Adapter(config.data);service._adapter=adapter;service._running=True
  path=root/'preview.png';Image.new('RGB',(160,160),'blue').save(path)
  entry={'id':'wxemote_fixture','name':'挥手','kind':'wechat_native','enabled':True}
  stickers=Mock();stickers.entries={entry['id']:entry}
  stickers.catalog.return_value={'complete':True,'pages':[{'items':[{'id':entry['id']}]}],'page_count':1}
  stickers.preview_strip.return_value=(path,entry,False);adapter.native_stickers=lambda:stickers
  incoming=IncomingMessage('test','昵称','给我表情包',chat_type='group')
  actions=[{'action':'tool','tool':'list_native_stickers','arguments':{'query':'挥手'}},
    {'action':'tool','tool':'preview_native_stickers','arguments':{'ids':entry['id']}},
    {'action':'tool','tool':'choose_native_sticker','arguments':{'request':json.dumps({'id':entry['id'],'style':'chibi','reason':'Q版挥手问候'})}},
    {'action':'final','text':'挥挥手～'}]
  client=Mock();client.chat.side_effect=[LLMResult(json.dumps(v,ensure_ascii=False),'fixture','openai',1) for v in actions]
  try:
   _,_,_,info=service._agent_reply(client,[{'role':'user','content':incoming.content}],'',
       {'provider':'openai','supports_vision':True},incoming,incoming.content,persona=service.personas.get('arona'),network_enabled=False,kind='reply',require_running=True)
   assert info['native_sticker']['id']==entry['id']
   assert isinstance(info['native_sticker']['preview_path'],str)
   json.dumps(info) # Actual history persistence must accept every selected field.
   def turn(text,delivery,**metadata):
    adapter.sent.clear();msg=IncomingMessage('test','昵称',text,chat_type='group')
    row=service._store_user(msg,text)
    result=LLMResult('这次测试成功。','fixture','openai',1)
    outcome=(result,{'total':0},'',{'agent':{'status':'completed'},'delivery':delivery,**metadata})
    with patch.object(service,'_model_reply',return_value=outcome),patch('app.service.make_tts') as factory,patch('app.native_voice.encode_clip',return_value=root/'voice.amr'):
     factory.return_value.synthesize.return_value=AudioClip(np.zeros(4800))
     service._generate_and_send(msg,target,row,text,force_reply=True)
    return [m for m in memory.recent('test',100) if m.get('role')=='assistant' and m.get('meta',{}).get('reply_to')==row]
   turn('看看图',{'kind':'image','file':str(path)})
   assert [v[0] for v in adapter.sent]==['image','text']
   turn('再来个表情',{'kind':'text'},native_sticker=info['native_sticker'])
   assert [v[0] for v in adapter.sent]==['text','sticker']
   rows=turn('请用语音',{'kind':'voice'})
   assert [v[0] for v in adapter.sent]==['voice'] and rows[-1]['meta']['voice_sent']
   # Reproduce the real provider's DSML envelope through the actual agent,
   # planner and delivery path, without contacting WeChat or a cloud model.
   voice_msg=IncomingMessage('test','昵称','发个语音打招呼',chat_type='group')
   client.chat.side_effect=[LLMResult('老师，我在哦，能听到吗？','fixture','openai',1),
                           LLMResult(DSML,'fixture','openai',1),
                           LLMResult('{"action":"final","text":"老师，你好呀！"}','fixture','openai',1)]
   outcome=service._agent_reply(client,[{'role':'user','content':voice_msg.content}],'',
       {'provider':'openai','supports_vision':True},voice_msg,voice_msg.content,
       persona=service.personas.get('arona'),network_enabled=False,kind='reply',require_running=True)
   assert outcome[3]['delivery']=={'kind':'voice'}
   assert outcome[0].text=='老师，你好呀！'
   adapter.sent.clear();row=service._store_user(voice_msg,voice_msg.content)
   with patch.object(service,'_model_reply',return_value=outcome),patch('app.service.make_tts') as factory,patch('app.native_voice.encode_clip',return_value=root/'voice.amr'):
    factory.return_value.synthesize.return_value=AudioClip(np.zeros(4800))
    service._generate_and_send(voice_msg,target,row,voice_msg.content,force_reply=True)
    assert factory.return_value.synthesize.call_args.args[0]=='老师，你好呀！'
   assert [v[0] for v in adapter.sent]==['voice']
   adapter.sent.clear()
   mixed=IncomingMessage('test','Alex小明','发个语音打下招呼吧',chat_type='group')
   row=service._store_user(mixed,mixed.content)
   mixed_outcome=(LLMResult('Alex小明老师，\n阿洛娜在这里哦，今天也请多指教。','fixture','openai',1),{},'',
                  {'agent':{'status':'completed'},'delivery':{'kind':'voice'}})
   with patch.object(service,'_model_reply',return_value=mixed_outcome),patch('app.service.make_tts') as factory,patch('app.native_voice.encode_clip',return_value=root/'voice.amr'),patch('app.voice_presets.resolve_persona_voice',return_value={'engine':'gpt_sovits','id':'arona'}):
    factory.return_value.synthesize.return_value=AudioClip(np.zeros(4800))
    service._generate_and_send(mixed,target,row,mixed.content,force_reply=True)
    speech=factory.return_value.synthesize.call_args.args[0]
    assert '小明老师' in speech and 'Alex' not in speech
    assert factory.return_value.synthesize.call_count==1
    assert '阿洛娜在这里哦' in speech
   assert [v[0] for v in adapter.sent]==['voice'], 'mixed nickname must not trigger a text fallback'
   adapter.voice_result=SendResult(False,status='unconfirmed')
   rows=turn('请用语音读另一句话',{'kind':'voice'})
   assert [v[0] for v in adapter.sent]==['voice'] and not rows
   adapter.voice_result=SendResult(False,status='rejected')
   turn('请用语音说你好',{'kind':'voice'})
   assert [v[0] for v in adapter.sent]==['voice','text']
  finally:service.shutdown()
 print('MODEL DELIVERY SERVICE AND UNCERTAIN RECEIPT TESTS PASSED')

if __name__=='__main__':main()
