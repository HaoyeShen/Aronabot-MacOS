"""The model chooses delivery; visual observations stay image attachments."""
import json,tempfile,time
from pathlib import Path
from unittest.mock import Mock,patch
from app.agent import AgentRunner,AgentTool,AgentObservation
from app.model_client import LLMResult
from app.reply_media import ReplyMedia
from app.wechat_adapter import IncomingMessage

def answer(value):return LLMResult(value,'fixture','openai',1)

def main():
    calls=[]
    observation=AgentObservation({'role':'user','content':[{'type':'text','text':'实际候选'},
        {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,eA=='}}]})
    def model(history,system,remaining):
        calls.append(history)
        if len(calls)==1:return answer('{"action":"tool","tool":"preview","arguments":{"id":"one"}}')
        assert isinstance(history[-1]['content'],list)
        assert history[-1]['content'][1]['type']=='image_url'
        return answer('{"action":"final","text":"看看这张。"}')
    result=AgentRunner().run(model,[],'',[AgentTool('preview','id','预览',lambda *_:observation)])
    assert result.status=='completed' and len(calls)==2
    service=Mock();incoming=IncomingMessage('test','昵称','想听语音')
    planner=ReplyMedia(service,incoming,{'supports_vision':True},lambda:False,time.monotonic()+30)
    assert planner.metadata()=={'kind':'text'},'a keyword alone must not select voice'
    planner.choose('{"kind":"voice"}',20)
    assert planner.metadata()['kind']=='voice'
    planner.choose('{"kind":"text"}',20)
    assert planner.metadata()['kind']=='text','model may choose text explicitly'
    try:planner.choose('{"kind":"image","id":"invented"}',20)
    except ValueError:pass
    else:raise AssertionError('unpreviewed image accepted')
    planner.images['known']={'id':'known','file':'verified.png','source':'https://example.com/a'}
    planner.choose('{"kind":"image","id":"known"}',20)
    assert planner.metadata()['file']=='verified.png'
    with patch.object(planner,'cancelled',return_value=True):
        try:planner.choose('{"kind":"voice"}',20)
        except RuntimeError:pass
        else:raise AssertionError('cancelled model action accepted')
    print('MODEL DELIVERY AND REAL MULTIMODAL OBSERVATION TESTS PASSED')

if __name__=='__main__':main()
