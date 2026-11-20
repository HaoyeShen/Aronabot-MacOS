"""Strip provider-injected safety classification envelopes from model text.

Some OpenAI-compatible providers prepend or replace the assistant content with
an internal classification block such as::

    <ds_safety>[用户未成年]否
    [分类]其他
    [判定]...
    [规则]无</ds_safety>Safe

That block is protocol metadata, never a chat message.  It must not be parsed
as prose, executed as a tool call, spoken aloud or written into WeChat.
"""
from __future__ import annotations

import re

_ENVELOPE = re.compile(
    r'<\s*ds_safety\b[^>]*>.*?<\s*/\s*ds_safety\s*>\s*(?:Safe\b)?', re.I | re.S)
_UNCLOSED = re.compile(r'<\s*ds_safety\b[^>]*>.*\Z', re.I | re.S)
_ORPHAN = re.compile(r'<\s*/?\s*ds_safety\b[^>]*>\s*(?:Safe\b)?', re.I)
_CLASS_LINE = re.compile(
    r'^[ \t]*\[(?:用户未成年|分类|判定|规则)\][^\n]*(?:\n|$)', re.M)
_ENVELOPE_TAG = re.compile(r'<\s*/?\s*ds_safety\b', re.I)


def contains_provider_envelope(value) -> bool:
    """True when text still carries a provider classification block."""
    text = str(value or '')
    return bool(_ENVELOPE_TAG.search(text) or _CLASS_LINE.search(text))


def strip_provider_envelope(value) -> str:
    """Remove the classification block, keeping any real reply or tool JSON.

    A complete block loses its trailing ``Safe`` marker.  An unclosed block is
    dropped to the end of the text because the closing tag cannot be trusted;
    that is safer than sending partial classifier output.
    """
    text = str(value or '')
    if not contains_provider_envelope(text):
        return text
    text = _ENVELOPE.sub('', text)
    text = _UNCLOSED.sub('', text)
    text = _ORPHAN.sub('', text)
    text = _CLASS_LINE.sub('', text)
    return text.strip()
