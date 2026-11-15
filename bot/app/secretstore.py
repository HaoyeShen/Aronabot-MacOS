"""API keys stored in macOS Keychain; config contains opaque references only."""
from __future__ import annotations
import base64,os,uuid

PREFIX_KEYCHAIN='keychain:'
PREFIX_DPAPI='dpapi:'
PREFIX_OBF='obf:'
SERVICE='com.wemac.auto.arona.api'


def _backend():
    from keyring.backends.macOS import Keyring
    return Keyring()


def protect(secret):
    if not secret:return ''
    identity=uuid.uuid4().hex
    try:_backend().set_password(SERVICE,identity,secret)
    except Exception as exc:raise RuntimeError('无法将 API Key 保存到 macOS 钥匙串，请检查钥匙串权限。') from exc
    return PREFIX_KEYCHAIN+identity


def unprotect(value):
    if not value:return ''
    if value.startswith(PREFIX_KEYCHAIN):
        try:return _backend().get_password(SERVICE,value[len(PREFIX_KEYCHAIN):]) or ''
        except Exception:return ''
    if value.startswith(PREFIX_DPAPI):return ''  # Windows ciphertext must be re-entered on this Mac.
    if value.startswith(PREFIX_OBF):
        try:
            raw=base64.b64decode(value[len(PREFIX_OBF):],validate=True)
            key=(os.environ.get('ARONA_LOCAL_SALT','arona-schale-local')*3).encode()
            return bytes(b^key[i%len(key)] for i,b in enumerate(raw)).decode()
        except (ValueError,UnicodeError):return ''
    return value if ':' not in value else ''


def masked(secret,visible=4):
    if not secret:return '未设置'
    return '•'*len(secret) if len(secret)<=visible*2 else secret[:visible]+'••••••••'+secret[-visible:]
