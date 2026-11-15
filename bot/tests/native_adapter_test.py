"""Native transport: exact target, account mentions, quote, origin and uncertain receipt."""
from pathlib import Path
import tempfile
from unittest.mock import Mock
from app.wechat_adapter import NativeWeChatAdapter

def main():
    adapter=NativeWeChatAdapter({},lambda _:None)
    adapter.connected=True;adapter.self_wxid='wxid_bot';adapter._session=Mock()
    adapter._aliases={'test':'room@chatroom'};adapter._by_id={'room@chatroom':{'name':'test','type':'group'}}
    ack={'status':'acknowledged','server_message_id':'99'}
    adapter._session.send_text.return_value=ack
    assert adapter.send_text('test','你好').ok
    adapter._session.send_text.assert_called_once_with('room@chatroom','你好')
    reference={'message_id':'1','chat_id':'room@chatroom','sender':'wxid_friend'}
    adapter._session.send_quote.return_value=ack
    assert adapter.send_quoted_text('test','回复',reference=reference).ok
    adapter._session.send_quote.assert_called_once_with('room@chatroom','回复',reference)
    assert not adapter.send_quoted_text('test','回复').ok
    adapter._session.send_text.return_value={'status':'unconfirmed'}
    uncertain=adapter.send_text('test','不重发')
    assert not uncertain.ok and uncertain.status=='unconfirmed'
    raw={'chat_id':'room@chatroom','message_id':'100','sender':'wxid_friend','message_type':1,'text':'@昵称 在吗',
         'direction':'incoming','source_xml':'<msgsource><atuserlist>wxid_bot</atuserlist></msgsource>'}
    incoming=adapter._map_message(raw,{'name':'test'})
    assert incoming.mentions_self and not incoming.is_self and incoming.raw['sender_username']=='wxid_friend'
    own=adapter._map_message({**raw,'direction':'outgoing','message_id':'99'},{'name':'test'})
    assert own.is_self and own.origin=='bot_echo'
    assert adapter.resolve_action_target('test')['identity']=='room@chatroom'
    original=adapter._session
    adapter.reconfigure_targets([{'name':'renamed','internal_id':'second@chatroom','type':'group'}])
    assert adapter._session is original and adapter._aliases['renamed']=='second@chatroom'
    original.connect.assert_not_called();original.close.assert_not_called()
    try:adapter.reconfigure_targets([{'name':'invalid','internal_id':'bad target'}])
    except ValueError:pass
    else:raise AssertionError('invalid target accepted')
    assert adapter._aliases['renamed']=='second@chatroom','failed update preserves previous listener'
    print('NATIVE ADAPTER TESTS PASSED')

if __name__=='__main__':main()
