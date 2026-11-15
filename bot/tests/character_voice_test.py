"""Offline contracts for the optional local voice and its worker protocol."""
import io
import json
import queue
import sys
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.character_voice import CharacterTTS, CharacterVoiceClient, PaddedTTS, make_tts, clarify_voice, character_speech_text
from app.voice_presets import VoicePresetStore
from scripts.character_voice_worker import synthesize, load_reference


def main():
    import numpy as np
    class Pipeline:
        def run(self, request):
            self.request = request
            yield 32000, (np.sin(np.arange(16000) * .1) * 30000).astype('<i2')
    pipeline = Pipeline()
    wav = synthesize(pipeline, '老师，我是普拉娜。', .92)
    assert pipeline.request['prompt_text'] == '老师，生物认证完毕。'
    assert pipeline.request['speed_factor'] == .92
    assert pipeline.request['text'] == '老师，我是普拉娜。'
    assert pipeline.request['top_k']==15 and pipeline.request['temperature']==1
    with wave.open(io.BytesIO(wav)) as handle:
        assert handle.getnchannels() == 1 and handle.getframerate() == 32000
        assert handle.getnframes() == 16000
    for text in ('', '老师，API 已启动。', '字' * 121):
        try:
            synthesize(pipeline, text)
        except ValueError:
            pass
        else:
            raise AssertionError('invalid or unsupported input must retain text fallback')
    class SilentTail:
        def __init__(self):self.seeds=[]
        def run(self,request):
            self.seeds.append(request['seed'])
            yield 32000,np.concatenate((np.full(16000,3000,dtype='<i2'),np.zeros(128000,dtype='<i2')))
    silent=SilentTail()
    try:synthesize(silent,'老师，这是完整的一句话。')
    except ValueError:pass
    else:raise AssertionError('mostly silent speech must not be reported as a completed voice reply')
    assert silent.seeds==[42,43], 'local retry must be bounded before any upload'
    class RetrySpeech(SilentTail):
        def run(self,request):
            if request['seed']==42:
                yield from super().run(request)
            else:
                self.seeds.append(request['seed'])
                yield from Pipeline().run(request)
    retry=RetrySpeech()
    assert synthesize(retry,'老师，这是完整的一句话。').startswith(b'RIFF')
    assert retry.seeds==[42,43]
    client = Mock()
    client.synthesize.return_value = wav
    tts = CharacterTTS(48000, client)
    clip = tts.synthesize('你好。', SimpleNamespace(rate='-8%', volume='+10%'))
    client.synthesize.assert_called_once_with('你好。', .92, character='plana')
    assert clip.sample_rate == 48000 and abs(clip.duration - .5) < .01
    assert float(abs(clip.samples).max()) <= .90001
    # Equal loudness, unchanged pitch/duration, less low-mid dominance.
    sr=48000;t=np.arange(sr,dtype=np.float64)/sr
    original=(.15*np.sin(2*np.pi*420*t)+.06*np.sin(2*np.pi*2500*t)).astype(np.float32)
    untouched=original.copy();clean=clarify_voice(original,sr,.75)
    assert len(clean)==len(original) and np.array_equal(original,untouched)
    assert np.array_equal(clarify_voice(original,sr,0),original)
    assert np.isfinite(clean).all() and float(abs(clean).max())<=.90001
    before=abs(np.fft.rfft(original));after=abs(np.fft.rfft(clean))
    assert after[420]/after[2500]<.85*(before[420]/before[2500])
    assert np.argmax(after)==np.argmax(before)==420
    assert abs(float(np.sqrt(np.mean(clean**2))/np.sqrt(np.mean(original**2)))-1)<.02
    client.synthesize.reset_mock()
    tts.synthesize('API 已启动。', SimpleNamespace(rate='+0%', volume='+0%'))
    client.synthesize.assert_called_once_with('诶，皮，艾 已启动。',1.0,character='plana')
    assert character_speech_text('Alex小明老师，你好。',nickname='Alex小明')=='小明老师，你好。'
    assert character_speech_text('老师，API可以用了。')=='老师，诶，皮，艾可以用了。'
    assert character_speech_text('老师，你好。')=='老师，你好。'
    try:character_speech_text('<tool_call>{"name":"search_web"}</tool_call>')
    except ValueError:pass
    else:raise AssertionError('tool output must never be spelled out as speech')
    client.synthesize.side_effect = RuntimeError('offline')
    try:
        tts.synthesize('你好。', SimpleNamespace(rate='+0%', volume='+0%'))
    except RuntimeError:
        pass
    else:
        raise AssertionError('model failure must propagate to existing text fallback')
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        local = CharacterVoiceClient(root)
        with patch('app.character_voice.subprocess.Popen') as start:
            for settings in (None, {'validated': False}):
                if settings is not None:
                    (root / 'profile.json').write_text(json.dumps(settings), encoding='utf-8')
                try:
                    local.synthesize('你好。')
                except RuntimeError:
                    pass
                else:
                    raise AssertionError('unconfigured character model must not launch')
            start.assert_not_called()
        local._responses = Mock()
        local._responses.get.side_effect = queue.Empty
        with patch.object(local, 'close') as close:
            try:
                local._receive(0)
            except RuntimeError:
                pass
            else:
                raise AssertionError('timeout must fail')
            close.assert_called_once()
        local._responses = queue.Queue()
        local._read_responses(SimpleNamespace(stdout=io.StringIO('[]\n')), local._responses)
        with patch.object(local, 'close') as close:
            try:
                local._receive(0)
            except RuntimeError:
                pass
            else:
                raise AssertionError('malformed protocol must terminate the worker')
            close.assert_called_once()
        store = VoicePresetStore(root / 'voices.json')
        preset = store.get('plana')
        preset.update(engine='gpt_sovits', label='普拉娜（国服中文）', rate='+0%', pitch='+0Hz')
        store.upsert(preset)
        assert VoicePresetStore(root / 'voices.json').get('plana')['engine'] == 'gpt_sovits'
        assert isinstance(make_tts(preset).backend, CharacterTTS)
        assert not isinstance(make_tts(store.get('arona')).backend, CharacterTTS)
        arona = {**store.get('arona'), 'engine': 'gpt_sovits'}
        assert make_tts(arona).backend.character == 'arona'
        assert make_tts({**arona,'clarity':.75}).backend.clarity==.75
        assert make_tts(preset).backend.clarity==0,'Plana must retain its original tone'
        with patch.object(client, 'synthesize', return_value=wav) as synth:
            CharacterTTS(client=client, character='arona').synthesize(
                '你好。', SimpleNamespace(rate='+0%', volume='+0%'))
            synth.assert_called_once_with('你好。', 1.0, character='arona')
        # Separate assets and transcripts; old Plana profiles remain readable.
        import hashlib
        from scripts import character_voice_worker as worker
        (root / 'profiles').mkdir()
        for character in ('arona', 'plana'):
            ref = root / f'{character}-reference.wav'
            ref.write_bytes(wav)
            weights = root / 'models' / character
            weights.mkdir(parents=True)
            for name in (f'{character}-e15.ckpt', f'{character}_e8_s232.pth'):
                (weights / name).write_bytes(b'weights')
            profile = {'character': character, 'transcript': f'我是{character}',
                       'reference_sha256': hashlib.sha256(wav).hexdigest()}
            if character == 'arona':
                profile.update(t2s_weights='models/arona/arona-e15.ckpt',
                               vits_weights='models/arona/arona_e8_s232.pth')
            path = root / ('profile.json' if character == 'plana' else 'profiles/arona.json')
            path.write_text(json.dumps(profile), encoding='utf-8')
            # Exercise equivalent noncanonical paths without local model files.
            with patch.object(worker, 'ROOT', root / '..' / root.name):
                loaded = load_reference(character)
                assert loaded['reference_audio'] == str(ref.resolve())
                assert loaded['transcript'] == f'我是{character}'
                if character == 'arona':
                    pipeline._arona_reference_text = loaded['transcript']
                    pipeline._arona_reference_audio = loaded['reference_audio']
                    synthesize(pipeline, '老师你好。')
                    assert pipeline.request['ref_audio_path'] == str(ref.resolve())
                    profile['reference_sha256'] = 'changed'
                    path.write_text(json.dumps(profile), encoding='utf-8')
                    try:
                        load_reference(character)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError('changed reference must not be silently accepted')
        # Switching character replaces the resident worker rather than loading
        # both large models, and can never reuse the other speaker's process.
        active = CharacterVoiceClient(root)
        active._process = SimpleNamespace(poll=lambda: None)
        active._character = 'plana'
        with patch.object(active, 'close') as close:
            active._start('plana')
            close.assert_not_called()
            try:
                active._start('arona')
            except RuntimeError:
                pass
            close.assert_called_once()
        from app.tts import AudioClip
        samples = np.array([.1, .2, -.3], dtype=np.float32)
        backend = Mock()
        backend.synthesize.return_value = AudioClip(samples, 48000, '你好')
        padded = PaddedTTS(backend).synthesize('你好', None)
        assert np.array_equal(padded.samples[:len(samples)], samples)
        assert len(padded.samples) == len(samples) + 28800
        assert not padded.samples[len(samples):].any()
    print('CHARACTER VOICE TESTS PASSED')


if __name__ == '__main__':
    main()
