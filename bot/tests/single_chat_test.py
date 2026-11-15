"""Routing cannot be entered/exited by non-admins; native IDs prevent nickname spoofing."""
import tempfile
from pathlib import Path
from unittest.mock import Mock
from app.config_store import ConfigStore
from app.single_chat import command,selected
from app.wechat_adapter import IncomingMessage

def main():
 with tempfile.TemporaryDirectory() as t:
  c=ConfigStore(Path(t)/'c.json');c.add_target('群','group','arona')
  c.data['admin']['allowed']=['wxid_admin']
  s=Mock();s.config=c;s.adapter._resolve_username.return_value='wxid_fixture';s._admin_allowed.return_value=False
  msg=IncomingMessage('群','管理员','/singlechat @测试者',chat_type='group',raw={'sender_username':'wxid_admin'})
  assert command(s,msg,msg.content) and not c.target_by_name('群').get('singlechat_user_id')
  s._admin_allowed.return_value=True;command(s,msg,msg.content)
  assert c.target_by_name('群')['singlechat_user_id']=='wxid_fixture'
  c.reload();target=c.target_by_name('群');assert target['singlechat_user_id']=='wxid_fixture'
  assert selected(target,IncomingMessage('群','测试者','你好',chat_type='group',raw={'sender_username':'wxid_fake'})) is False
  assert selected(target,IncomingMessage('群','随便的昵称','你好',chat_type='group',raw={'sender_username':'wxid_fixture'})) is True
  s._admin_allowed.return_value=False;command(s,msg,'/singlechat off');assert c.target_by_name('群')['singlechat_user_id']
  s._admin_allowed.return_value=True;command(s,msg,'/singlechat off');assert not c.target_by_name('群').get('singlechat_user_id')
 print('SINGLECHAT PERMISSION AND PERSISTENCE PASSED')
if __name__=='__main__':main()
