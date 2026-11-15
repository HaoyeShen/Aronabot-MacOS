"""Administrator-only, per-group routing, keyed by stable native sender IDs."""
import re


def command(service,incoming,text):
    if text.strip().casefold()=='/endsinglechat':text='/singlechat off'
    match=re.fullmatch(r'/singlechat(?:\s+(.+))?',text.strip(),re.I)
    if not match:return False
    if not incoming.is_group or not service._admin_allowed(incoming):return True
    raw=incoming.raw if isinstance(incoming.raw,dict) else {}
    sender=str(raw.get('sender_username') or '')
    if sender and not incoming.is_self and incoming.direction!='out':
        # A display-name match alone cannot authorize a group command.
        entries=service.config.data.get('admin',{}).get('allowed',[])
        resolver=getattr(service.adapter,'_resolve_username',None)
        identities={str(e) for e in entries}
        if resolver:
            identities.update(str(resolver(e) or '') for e in entries if e!='__self__')
        if sender not in identities:return True
    value=(match[1] or '').strip()
    target=service.config.target_by_name(incoming.chat)
    if not target:return True
    if value.casefold() in {'off','exit','end','stop','退出','结束'}:
        target.pop('singlechat_user_id',None)
        service.config.save();service._send_admin_text(incoming.chat,'已退出单人必回复模式。');return True
    if not value:
        service._send_admin_text(incoming.chat,'用法：/singlechat @昵称 或 /singlechat 微信ID；退出：/singlechat off');return True
    name=value.lstrip('@').strip()
    resolver=getattr(service.adapter,'_resolve_username',None)
    identity=resolver(name) if resolver else None
    if not identity or str(identity).endswith('@chatroom'):
        service._send_admin_text(incoming.chat,'无法唯一识别该成员，请填写准确微信ID或无歧义昵称。');return True
    target['singlechat_user_id']=identity
    service.config.save();service._send_admin_text(incoming.chat,'已进入单人必回复模式，其他成员不会触发回复。')
    return True


def selected(target,incoming):
    identity=target.get('singlechat_user_id') if incoming.is_group else None
    if not identity:return None
    raw=incoming.raw if isinstance(incoming.raw,dict) else {}
    return str(raw.get('sender_username') or '')==str(identity)
