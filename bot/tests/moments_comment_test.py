"""Exact native post checks, cancellation and previews perform no write."""
from unittest.mock import Mock
from app.wechat_adapter import NativeWeChatAdapter

def main():
    adapter=NativeWeChatAdapter({},lambda _:None);adapter._session=Mock()
    post={'id':'1','username':'friend','text':'原文'}
    adapter._session.get_moment.return_value={'status':'acknowledged','post':{'post_id':'1','owner_id':'friend','text':'原文'}}
    adapter._session.comment_moment.return_value={'status':'acknowledged','interaction_confirmed':True}
    assert adapter.comment_moment(post,'测试',dry_run=True).ok
    adapter._session.comment_moment.assert_not_called()
    assert not adapter.comment_moment(post,'测试',allowed=lambda:False).ok
    adapter._session.comment_moment.assert_not_called()
    assert not adapter.comment_moment({**post,'text':'同作者另一条'},'测试').ok
    adapter._session.comment_moment.assert_not_called()
    assert adapter.comment_moment(post,'测试').ok
    adapter._session.comment_moment.assert_called_once_with('1','测试')
    print('NATIVE MOMENTS COMMENT TESTS PASSED')

if __name__=='__main__':main()
