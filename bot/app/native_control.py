"""Same-user local maintenance calls on the bot's already-owned native session."""
import re

def handle(service, request):
    if not isinstance(request,dict):raise ValueError('Invalid native control request')
    if request.get('command')=='status':
        adapter=service.adapter
        return {'running':bool(service._running),'connected':bool(adapter and adapter.connected)}
    if request.get('command')!='native_send_text':raise ValueError('Unsupported maintenance command')
    user=request.get('user_id');text=request.get('text')
    if not isinstance(user,str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}',user):raise ValueError('Expected an exact internal recipient ID')
    if not isinstance(text,str) or not 1<=len(text)<=2048 or '\0' in text:raise ValueError('Invalid maintenance text')
    adapter=service.adapter
    if not service._running or not adapter or not adapter.connected:raise RuntimeError('Native bot is not connected')
    contact=adapter._session.get_contact(user)
    if not contact or contact['user_id']!=user or contact['type']!='friend':raise ValueError('Recipient is not a verified friend')
    with adapter._transport_lock:
        result=adapter._session.send_text(user,text)
    return {'status':result.get('status'),'server_message_id':result.get('server_message_id','')}
