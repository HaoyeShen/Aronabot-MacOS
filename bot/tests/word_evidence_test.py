"""Protect Word evidence past history previews and Chinese two-character recall."""
import tempfile,zipfile
import json
from pathlib import Path
from unittest.mock import Mock
from app.incoming_documents import read_document,evidence,retain_current_evidence
from app.prompting import build_context_messages,build_training_block
from app.training import TrainingStore
from app.wechat_adapter import NativeWeChatAdapter

def main():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);p=root/'sample.docx'
  with zipfile.ZipFile(p,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+('背景说明。'*600)+'关键结论：项目预算为4729元。</w:t></w:r></w:p></w:body></w:document>')
  doc=read_document(p);content='[文件] sample.docx'+evidence(doc)
  messages=build_context_messages([{'role':'user','content':content}]);retain_current_evidence(messages,content)
  assert '4729' in messages[-1]['content'] and len(messages[-1]['content'])>1600
  adapter=NativeWeChatAdapter({},lambda _:None);adapter._session=Mock();adapter._session.download_attachment.return_value=p
  raw={'chat_id':'friend','message_id':'123','sender':'friend','message_type':49,'text':'<msg><appmsg><title>没有后缀的文件名</title><type>6</type><appattach><fileext>docx</fileext></appattach></appmsg></msg>','direction':'incoming'}
  incoming=adapter._map_message(raw,{'name':'fixture'})
  assert incoming.msg_type=='file' and incoming.raw['_attachment_path']==str(p)
  store=TrainingStore(root/'training.db',root/'files')
  try:
   noise=root/'聊天导出.txt';noise.write_text('这里讨论的是哪个学校，学校附近有一家商店。'*2400)
   assert store.add_file(noise)['ok']
   archive=root/'角色.json';archive.write_text(json.dumps({'source':'public source','language':'CN','student':{'Name':'白子','School':'阿拜多斯','Age':16}},ensure_ascii=False))
   assert store.add_file(archive)['ok']
   parsed=store.search('白子 阿拜多斯',max_chars=2000)
   assert parsed and '阿拜多斯' in parsed[0]['content']
   s=root/'设定.txt';s.write_text('白子属于阿拜多斯学院，擅长骑行。白子在对策委员会活动。')
   assert store.add_file(s)['ok']
   hits=store.search('白子在哪个学校',max_chars=2000)
   assert hits and '阿拜多斯' in hits[0]['content']
   assert hits[0]['name']=='角色.json'
   block=build_training_block(hits,2000);assert '角色.json' in block and '片段1' in block
   assert not store.search('午饭煮什么')
  finally:store.close()
 print('WORD EVIDENCE, EXTENSION METADATA AND LOCAL RECALL TESTS PASSED')
if __name__=='__main__':main()
