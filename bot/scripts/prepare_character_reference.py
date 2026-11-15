"""Prepare a local character reference, never a validated/trained voice model."""
from __future__ import annotations
import argparse,hashlib,json,os,subprocess,tempfile,wave
from pathlib import Path

def prepare(source,folder,character,transcript,*,start=0,duration=6):
    import av
    if character not in ('arona','plana'):raise ValueError('未知角色')
    source=Path(source).expanduser().resolve()
    if not source.is_file():raise ValueError('参考素材不存在')
    if not transcript.strip():raise ValueError('请填写与所选片段完全一致的台词')
    if not 0<=start or not 3<=duration<=10:raise ValueError('参考片段应为3–10秒，起点不能为负数')
    with av.open(str(source)) as media:
        if not media.streams.audio:raise ValueError('该文件没有音轨，无法提取参考配音；请提供带声音的素材')
    import imageio_ffmpeg
    folder=Path(folder).expanduser().resolve()/character;folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
    with tempfile.TemporaryDirectory(dir=folder,prefix='prepare-') as temp:
        audio=Path(temp)/'reference.wav'
        result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-v','error','-i',str(source),
            '-ss',str(start),'-t',str(duration),'-map','0:a:0','-ac','1','-ar','32000','-c:a','pcm_s16le',str(audio)],capture_output=True,timeout=40)
        if result.returncode:raise RuntimeError('参考音轨解码失败')
        with wave.open(str(audio),'rb') as w:
            seconds=w.getnframes()/w.getframerate()
            if not 3<=seconds<=10.1:raise ValueError('实际有效音频不足3秒或超过10秒')
        report={'character':character,'transcript':transcript,'source':str(source),'start':start,'seconds':seconds,
            'reference_sha256':hashlib.sha256(audio.read_bytes()).hexdigest(),'validated':False,
            'status':'reference_only_requires_model_synthesis_validation'}
        destination=folder/'reference.wav';audio.replace(destination)
        (folder/'reference.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--character',choices=('arona','plana'),required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--transcript',required=True)
    p.add_argument('--start',type=float,default=0);p.add_argument('--duration',type=float,default=6)
    p.add_argument('--folder',type=Path,default=Path.home()/'Library/Application Support/WemacAuto/Arona/character_voice/references')
    args=p.parse_args()
    try:print(json.dumps(prepare(args.source,args.folder,args.character,args.transcript,start=args.start,duration=args.duration),ensure_ascii=False))
    except (ValueError,RuntimeError) as error:p.exit(2,str(error)+'\n')
