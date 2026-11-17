"""Opt-in routing, local boundaries, validation and failure fallback."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app.config_store import ConfigStore
from app.economy import EconomyRouter
from app.model_client import LLMResult
from app.service import BotService

def main():
 with tempfile.TemporaryDirectory() as tmp:
  config=ConfigStore(Path(tmp)/'config.json');assert config.bot['economy_enabled'] is False
  router=EconomyRouter(config);cloud={'provider':'openai'};messages=[{'role':'user','content':'@阿洛娜 在吗'}]
  with patch('app.economy.local_models') as probe:
   assert router.try_chat(cloud,messages,'only YES/NO',purpose='关键词是否对机器人说话') is None;probe.assert_not_called()
  config.bot['economy_enabled']=True;config.save();assert ConfigStore(config.path).bot['economy_enabled'] is True
  result=LLMResult('YES','qwen3.5:9b','ollama',1,usage={'prompt':10,'completion':1})
  with patch('app.economy.local_models',return_value=['qwen3.5:9b']),patch('app.economy.model_call',return_value=result) as call:
   assert router.try_chat(cloud,messages,'only YES/NO',purpose='关键词是否对机器人说话') is result
   assert router.local_tasks==1
   for purpose in ('回复消息：Agent 决策及回答','朋友圈Agent：阅读与评论判断','今日日记：当天活动总结'):
    assert router.try_chat(cloud,messages,'',purpose=purpose) is None
   assert router.try_chat(cloud,[{'role':'user','content':[{'type':'image_url'}]}],'',purpose='上下文摘要') is None
   assert router.try_chat(cloud,messages,'X'*10000,purpose='上下文摘要') is None
   assert router.try_chat(cloud,messages,'中'*5000,purpose='上下文摘要') is None
   assert call.call_count==1
  with patch('app.economy.model_call',return_value=LLMResult('not a valid classification','local','ollama',1)):
   assert router.try_chat(cloud,messages,'',purpose='关键词是否对机器人说话') is None
   assert router.fallbacks==1
  with patch('app.economy.local_models') as probe:
   assert router.try_chat(cloud,messages,'',purpose='关键词是否对机器人说话') is None;probe.assert_not_called()
  service=SimpleNamespace(economy=SimpleNamespace(try_chat=Mock(return_value=None)))
  with patch('app.service.model_call',return_value=result) as cloud_call:
   assert BotService._simple_model_chat(service,cloud,messages,'',purpose='上下文摘要') is result
   cloud_call.assert_called_once()
 print('ECONOMY DEFAULT-OFF, ALLOWLIST, LOCAL VALIDATION AND FALLBACK PASSED')
if __name__=='__main__':main()
