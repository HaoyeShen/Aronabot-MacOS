"""Draft generation never submits; uncertain submission is retained as unknown."""
from unittest.mock import Mock
from app.wechat_adapter import NativeWeChatAdapter

def main():
    adapter=NativeWeChatAdapter({},lambda _:None);adapter._session=Mock()
    adapter._session.prepare_moment.return_value={'text':'测试草稿','payload':b'private'}
    assert adapter.publish_moment('测试草稿',dry_run=True).ok
    adapter._session.publish_moment.assert_not_called()
    adapter._session.publish_moment.return_value={'status':'unconfirmed','detail':'no response'}
    result=adapter.publish_moment('明确发布')
    assert not result.ok and result.status=='unconfirmed'
    adapter._session.publish_moment.assert_called_once_with('明确发布',visibility='public')
    print('NATIVE MOMENTS PUBLISH TESTS PASSED')

if __name__=='__main__':main()
