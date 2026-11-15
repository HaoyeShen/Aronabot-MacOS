"""PCM synthesis previews and direct AMR-NB uploads; no recorder or virtual cable."""
from __future__ import annotations
import ctypes
import os
import subprocess
import tempfile
from pathlib import Path
from .paths import DATA, SDK_ROOT


def amr_library() -> Path:
    candidates = [Path(os.environ['ARONA_AMR_LIBRARY'])] if os.environ.get('ARONA_AMR_LIBRARY') else []
    candidates += [DATA/'lib/libopencore-amrnb.dylib', SDK_ROOT/'bot/lib/libopencore-amrnb.dylib',
                   SDK_ROOT/'research/deps/opencore-amr-master/local-build/libopencore-amrnb.dylib',
                   Path('/opt/homebrew/lib/libopencore-amrnb.dylib'), Path('/usr/local/lib/libopencore-amrnb.dylib')]
    for path in candidates:
        if path.is_file():return path.resolve()
    raise RuntimeError('尚未安装 AMR 编码器；请运行 bot/scripts/install_amr.py。')


def encode_clip(clip) -> Path:
    import numpy as np
    import miniaudio
    if not 0 < clip.duration <= 60:
        raise ValueError('原生语音长度须在 0–60 秒以内；请减小单段语音字数。')
    samples = np.asarray(clip.samples,dtype='<f4')
    if not np.isfinite(samples).all():raise ValueError('语音采样包含无效值。')
    pcm = miniaudio.convert_frames(miniaudio.SampleFormat.FLOAT32,1,int(clip.sample_rate),samples.tobytes(),
                                   miniaudio.SampleFormat.SIGNED16,1,8000)
    # Give AMR decoders/VAD a brief quiet lead-in before the first consonant.
    # Keep every original sample; short names must not start at frame zero.
    if len(pcm) <= 59.8 * 8000 * 2:
        pcm = bytes(3200) + pcm  # 200 ms of mono 8 kHz signed-16 silence.
    lib = ctypes.CDLL(str(amr_library()))
    lib.Encoder_Interface_init.argtypes=[ctypes.c_int];lib.Encoder_Interface_init.restype=ctypes.c_void_p
    lib.Encoder_Interface_Encode.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_int16),ctypes.POINTER(ctypes.c_ubyte),ctypes.c_int]
    lib.Encoder_Interface_Encode.restype=ctypes.c_int
    lib.Encoder_Interface_exit.argtypes=[ctypes.c_void_p]
    state = lib.Encoder_Interface_init(0)
    if not state:raise RuntimeError('AMR 编码器初始化失败。')
    result=bytearray(b'#!AMR\n');out=(ctypes.c_ubyte*500)()
    try:
        for offset in range(0,len(pcm),320):
            frame=(ctypes.c_int16*160).from_buffer_copy(bytes(pcm[offset:offset+320]).ljust(320,b'\0'))
            size=lib.Encoder_Interface_Encode(state,7,frame,out,0)
            if not 0<size<=500:raise RuntimeError('AMR 编码器返回无效帧。')
            result.extend(bytes(out[:size]))
    finally:lib.Encoder_Interface_exit(state)
    if len(result)>65536:raise ValueError('语音超过原生上传大小限制。')
    folder=DATA/'temp/voice';folder.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(suffix='.amr',dir=folder)
    with os.fdopen(fd,'wb') as stream:stream.write(result)
    return Path(name)


def preview(preset,text):
    from .character_voice import make_tts
    from .voices import resolve_voice
    clip=make_tts(preset).synthesize(text,resolve_voice(preset.get('voice'),rate=preset.get('rate'),pitch=preset.get('pitch'),volume=preset.get('volume')))
    folder=DATA/'temp/voice';folder.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(suffix='.wav',dir=folder);os.close(fd)
    path=Path(name)
    try:
        clip.to_wav(path)
        subprocess.run(['/usr/bin/afplay',str(path)],check=True,timeout=max(30,clip.duration+10))
    finally:path.unlink(missing_ok=True)
