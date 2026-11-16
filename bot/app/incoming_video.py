"""Decode received video in a bounded worker, never in the WeChat process."""
import hashlib,json,math,subprocess,sys,wave
from pathlib import Path

def _worker(request):
    import av
    from PIL import ImageOps
    source=Path(request['path']).resolve();folder=Path(request['folder']).resolve()
    if not source.is_file() or not 0<source.stat().st_size<=32*1024*1024:raise ValueError('Video exceeds 32 MiB')
    folder.mkdir(parents=True,exist_ok=True);images=[];timestamps=[]
    options={'protocol_whitelist':'file,pipe','protocol_blacklist':'http,https,tcp,tls,udp,crypto,data'}
    with av.open(str(source),options=options) as media:
        if not media.streams.video:raise ValueError('No decodable video stream')
        stream=media.streams.video[0]
        duration=float(stream.duration*stream.time_base) if stream.duration is not None else float(media.duration or 0)/av.time_base
        if not math.isfinite(duration) or duration<=0:duration=30.
        sampled=min(duration,120.)
        audio=bool(media.streams.audio)
        for index,t in enumerate(sorted({0.,sampled*.25,sampled*.5,sampled*.75,max(0.,sampled-.1)})):
            media.seek(int(t/stream.time_base),stream=stream,backward=True)
            for count,frame in enumerate(media.decode(stream)):
                if frame.width*frame.height>16_000_000:raise ValueError('Video frame exceeds dimensions')
                actual=float(frame.pts*stream.time_base) if frame.pts is not None else t
                if actual+.05<t and count<180:continue
                image=frame.to_image();image.thumbnail((1600,1600));dest=folder/f'frame-{index}.png';image.save(dest,'PNG',optimize=True);dest.chmod(0o600)
                images.append(str(dest));timestamps.append(round(actual,2));break
    wav=None
    if audio:
        import imageio_ffmpeg
        destination=folder/'audio.wav'
        result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-protocol_whitelist','file,pipe','-i',str(source),'-t','120','-vn','-map','0:a:0','-ac','1','-ar','16000','-c:a','pcm_s16le','-y',str(destination)],capture_output=True,timeout=30)
        if result.returncode==0 and destination.is_file() and destination.stat().st_size<=8*1024*1024:
            with wave.open(str(destination),'rb') as check:
                if check.getnframes()>0:wav=str(destination);destination.chmod(0o600)
    if not images:raise ValueError('Video did not yield visible frames')
    return {'images':images,'timestamps':timestamps,'audio':wav,'duration':duration,'sampled_seconds':sampled,'truncated':duration>120}

def read_video(path,folder):
    source=Path(path);destination=Path(folder)/hashlib.sha256(source.read_bytes()).hexdigest()[:24]
    command=[sys.executable,'--incoming-video-worker'] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve())]
    result=subprocess.run(command,input=json.dumps({'path':str(source),'folder':str(destination)}),capture_output=True,text=True,timeout=45)
    if result.returncode:raise ValueError('原生视频资源未能解码，可能需要授权或仍有视频号加密')
    return json.loads(result.stdout)
if __name__=='__main__':print(json.dumps(_worker(json.load(sys.stdin))))
