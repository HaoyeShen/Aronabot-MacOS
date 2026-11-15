"""DeepSeek's documented speech endpoint using the existing Keychain profile."""
from __future__ import annotations
import json,urllib.parse,urllib.request
from .tts import AudioClip

class DeepSeekTTS:
    def synthesize(self,text,voice):
        import numpy as np
        import miniaudio
        from .config_store import ConfigStore
        from .model_client import ModelClient
        config=ConfigStore();profiles=[config.active_profile(),*config.data.get('model_profiles',[])]
        selected=next((p for p in profiles if urllib.parse.urlsplit(p.get('base_url','')).hostname=='api.deepseek.com' and p.get('api_key_enc')),None)
        if selected is None:raise RuntimeError('DeepSeek 语音需要已保存的官方 API 配置。')
        if voice.voice not in ('stella','tide'):raise ValueError('DeepSeek 音色必须是 stella 或 tide。')
        if voice.rate not in ('+0%','0%') or voice.pitch not in ('+0Hz','0Hz'):
            raise ValueError('DeepSeek 语音暂不支持语速和音调调整，请设为 0。')
        if not text.strip() or len(text)>500:raise ValueError('语音正文为空或过长。')
        client=ModelClient(selected)
        if not client.api_key:raise RuntimeError('无法从钥匙串取得 DeepSeek 凭据。')
        request=urllib.request.Request('https://api.deepseek.com/v1/tools/tts',
            data=json.dumps({'text':text,'voice_id':voice.voice,'format':'pcm','filter_markdown':False},ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+client.api_key,'Content-Type':'application/json'},method='POST')
        with client._opener().open(request,timeout=45) as response:
            content=response.read(8*1024*1024+1)
        if not content or len(content)>8*1024*1024 or len(content)%2:raise RuntimeError('语音响应不完整或超过大小限制。')
        data=miniaudio.convert_frames(miniaudio.SampleFormat.SIGNED16,1,24000,content,miniaudio.SampleFormat.FLOAT32,1,48000)
        samples=np.frombuffer(data,dtype='<f4').copy()
        samples*=max(0,min(2,1+float(voice.volume.rstrip('%'))/100))
        return AudioClip(samples,48000,text)
