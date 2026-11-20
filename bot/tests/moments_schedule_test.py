"""Independent, immediate Moments scheduling and failure isolation."""
from types import SimpleNamespace
from unittest.mock import Mock
from app.service import BotService
from app.moments_reader import MomentsReader
import time

def main():
 diary=SimpleNamespace(tick=Mock())
 reader=SimpleNamespace(tick=Mock())
 s=SimpleNamespace(diary=diary,moments_reader=reader)
 BotService._moments_tick(s);reader.tick.assert_called_once();diary.tick.assert_not_called()
 event=Mock();event.is_set.return_value=False;event.wait.return_value=True
 tick=Mock();loop=SimpleNamespace(_running=True,_stop_event=event,_moments_tick=tick)
 BotService._moments_loop(loop)
 tick.assert_called_once();event.wait.assert_called_once_with(25)
 now=time.time();reader=MomentsReader(None)
 post={'id':'1','username':'friend','text':'周二好','create_time':now-10}
 assert reader.eligible([post],'self',now)==[post]
 assert not reader.eligible([{**post,'username':'self'}],'self',now)
 assert not reader.eligible([{**post,'create_time':now-90000}],'self',now)
 print('MOMENTS IMMEDIATE SCHEDULING AND FAILURE ISOLATION PASSED')
if __name__=='__main__':main()
