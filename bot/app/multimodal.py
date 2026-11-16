"""Attach local decrypted images to the same reply/Agent request."""
import base64
import io
import re
import time
from pathlib import Path

MAX_IMAGES = 8


def reply_image_paths(incoming, history, *, max_age=300):
    """A failed new attachment must never silently become an older picture."""
    direct = [incoming.image_path, *(incoming.raw or {}).get('_model_images', [])]
    if any(direct) or incoming.msg_type in ('image', 'emotion', 'video', 'file'):
        return [str(p) for p in direct if p]
    if not re.search(r'图|照片|表情|画面|附件|第一个|第二个|第三个|上面|刚才|这个|那个|这张|那张|颜色|里面|是谁|看到了什么', incoming.content or ''):
        return []
    result = []
    for row in reversed(history):
        meta = row.get('meta') or {}
        if row.get('role') != 'user' or meta.get('manual'):
            continue
        if time.time() - float(row.get('created_at') or 0) > max_age:
            break
        sender_id = (incoming.raw or {}).get('sender_username') or (incoming.raw or {}).get('sender')
        if incoming.is_group and ((sender_id and meta.get('sender_username') != sender_id)
                                  or (not sender_id and row.get('sender') != incoming.sender)):
            continue
        paths = [meta.get('image_path'), *meta.get('image_paths', [])]
        if any(paths):
            result[0:0] = [str(p) for p in paths if p]
            if len(result) >= 3 or not re.search(r'分别|几张|两张|这些|刚才的图片', incoming.content or ''):
                break
        elif row.get('msg_type') in ('image', 'emotion'):
            break
    return list(dict.fromkeys(result))[:3]


def _samples(path):
    from PIL import Image, ImageOps
    with Image.open(path) as source:
        if source.width * source.height > 32_000_000:
            return
        frames = min(600, getattr(source, 'n_frames', 1))
        durations = []
        for index in range(frames):
            source.seek(index)
            durations.append(max(10, min(10000, int(source.info.get('duration', 100) or 100))))
        selected = {0, frames - 1}
        if frames > 1:
            total = sum(durations)
            for fraction in (.2, .4, .6, .8):
                elapsed = 0
                for index, duration in enumerate(durations):
                    elapsed += duration
                    if elapsed >= total * fraction:
                        selected.add(index)
                        break
        for index in sorted(selected):
            source.seek(index)
            image = ImageOps.exif_transpose(source).convert('RGBA')
            background = Image.new('RGBA', image.size, 'white')
            background.alpha_composite(image)
            image = background.convert('RGB')
            image.thumbnail((2048, 2048))
            image.info['_wemac_view']=('动画第 '+str(index+1)+'/'+str(frames)+' 帧' if frames>1 else '完整画面')
            yield image
        if frames == 1 and source.height > source.width * 2 and source.height > 2048:
            image = ImageOps.exif_transpose(source).convert('RGB')
            height = min(image.height, max(1024, image.width * 2))
            for y in dict.fromkeys((0, (image.height-height)//2, image.height-height)):
                crop = image.crop((0, y, image.width, y+height))
                crop.thumbnail((2048, 2048))
                crop.info['_wemac_view']='长图局部，自上而下第 '+str(y)+' 像素处'
                yield crop


def attach_images(messages, paths, profile):
    candidates = []
    for path in dict.fromkeys(str(p) for p in paths if p):
        file = Path(path)
        if not file.is_file() or file.stat().st_size > 32 * 1024 * 1024:
            continue
        try:
            candidates.append(list(_samples(file)))
        except (OSError, ValueError):
            continue
    images = []
    labels = []
    mime_types=[]
    encoded_bytes=0
    for index in range(max((len(frames) for frames in candidates), default=0)):
        for attachment,frames in enumerate(candidates,1):
            if index >= len(frames) or len(images) >= MAX_IMAGES:
                continue
            output = io.BytesIO()
            frames[index].save(output, 'PNG', optimize=True)
            mime='image/png'
            if output.tell()>3*1024*1024:
                output=io.BytesIO();frames[index].save(output,'JPEG',quality=94,optimize=True)
                mime='image/jpeg'
            data = base64.b64encode(output.getvalue()).decode('ascii')
            if data not in images and encoded_bytes+len(data)<=24*1024*1024:
                images.append(data)
                encoded_bytes+=len(data);mime_types.append(mime)
                labels.append('第 '+str(len(images))+' 幅＝附件 '+str(attachment)+'，'+frames[index].info.get('_wemac_view','视图'))
    if not images:
        return 0
    index = next((i for i in range(len(messages)-1, -1, -1) if messages[i].get('role') == 'user'), None)
    if index is None:
        messages.append({'role': 'user', 'content': '[图片]'})
        index = len(messages)-1
    message = dict(messages[index])
    text = message.get('content', '')
    if not isinstance(text, str):
        return 0  # Already attached in this reply chain.
    if len(images)>1:
        text+='\n[附图对应关系，仅用于区分图片与同一动画的不同帧]\n'+'\n'.join(labels)
    if profile.get('provider') == 'ollama':
        message.update(content=text, images=images)
    else:
        message['content'] = [{'type': 'text', 'text': text}] + [
            {'type': 'image_url', 'image_url': {'url': 'data:'+mime+';base64,' + data, 'detail': 'high'}}
            for mime,data in zip(mime_types,images)]
    messages[index] = message
    return len(images)
