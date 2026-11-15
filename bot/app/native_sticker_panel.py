"""Compatibility boundary: native stickers are submitted through the SDK."""

def send(adapter,chat,entry,*,allowed=lambda:True):
    if not allowed():raise RuntimeError('表情发送任务已取消')
    return adapter.send_native_sticker(chat,entry,allowed=allowed)
