"""All installed pages and byte-verified animation previews, without UI controls."""
import hashlib,tempfile
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from app.native_stickers import NativeStickers

def main():
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);gif=root/'emoji.gif'
        Image.new('RGB',(30,30),'red').save(gif,save_all=True,append_images=[Image.new('RGB',(30,30),'blue')],duration=100,loop=0)
        digest=hashlib.md5(gif.read_bytes()).hexdigest()
        session=Mock();session.get_installed_stickers.return_value={'complete':True,'pages':[
            {'id':str(i),'name':f'第{i+1}页','items':[{'md5':digest,'name':'动画'}]} for i in range(6)]}
        session.download_sticker.return_value=gif
        store=NativeStickers(session,root/'cache');catalog=store.catalog()
        assert catalog['complete'] and catalog['page_count']==6 and catalog['count']==1
        identity=catalog['pages'][-1]['items'][0]['id']
        path,entry,thumb=store.preview_strip(identity)
        assert path.is_file() and entry['md5']==digest and not thumb
        try:store.preview('unknown')
        except ValueError:pass
        else:raise AssertionError('unknown sticker accepted')
        gif.write_bytes(b'wrong cached resource')
        try:store.preview(identity)
        except ValueError:pass
        else:raise AssertionError('MD5 mismatch accepted')
    print('NATIVE STICKER ALL-PAGE AND PREVIEW TESTS PASSED')

if __name__=='__main__':main()
