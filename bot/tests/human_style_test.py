"""Local chat records become aggregate style guidance, never raw text."""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import human_style


def main():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / 'corpus'
        folder.mkdir()
        messages = []
        for index in range(600):
            body = 'SENTINEL_TEXT' if index == 0 else ('今天好累' if index % 3 else '知道了')
            if index % 50 == 0:
                body += '。'
            body = ('wxid_fixture_%d:\n' % index) + body
            messages.append({'direction': 'incoming', 'content': body})
        (folder / 'one.json').write_text(json.dumps(messages, ensure_ascii=False))
        (folder / 'two.json').write_text(json.dumps([
            {'direction': 'incoming', 'content': 'wxid_other:\n啊这'},
            {'direction': 'outgoing', 'content': '机器人自己的话'},
            {'direction': 'incoming', 'content': 'wxid_x:\n<?xml version="1.0"?><msg/>'},
        ], ensure_ascii=False))
        profile = human_style.analyze(folder)
        assert profile['samples'] >= 600, profile
        assert profile['median'] <= 20 and profile['under_20'] > 50
        assert profile['no_end_punct'] > 80
        assert profile['conversations'] >= 1
        block = human_style.render(profile)
        assert '本机' in block and 'SENTINEL_TEXT' not in block
        assert 'wxid_' not in block and '知道了' not in block
        cache = Path(tmp) / 'style.json'
        first = human_style.load_or_build(folder, cache)
        assert first == block and cache.exists()
        saved = cache.read_text()
        assert 'SENTINEL_TEXT' not in saved and 'wxid_' not in saved
        second = human_style.load_or_build(folder, cache)
        assert second == first
        # A new message invalidates the cache and rebuilds the aggregate.
        rows = json.loads((folder / 'two.json').read_text())
        rows.append({'direction': 'incoming', 'content': 'wxid_new:\n好的'})
        (folder / 'two.json').write_text(json.dumps(rows, ensure_ascii=False))
        time.sleep(0.02)
        third = human_style.load_or_build(folder, cache)
        assert third and third == human_style.render(human_style.analyze(folder))
        # Too little data must not produce a style block.
        empty = Path(tmp) / 'empty'
        empty.mkdir()
        (empty / 'tiny.json').write_text(json.dumps([
            {'direction': 'incoming', 'content': '你好'}], ensure_ascii=False))
        assert human_style.render(human_style.analyze(empty)) == ''
    print('HUMAN STYLE TESTS PASSED')


if __name__ == '__main__':
    main()
