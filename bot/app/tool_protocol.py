"""Recognize model-internal tools without treating them as chat text."""
import json
import re
from xml.etree import ElementTree


_DSML_MARKER = re.compile(r'[|｜]{1,2}\s*DSML\s*[|｜]{1,2}', re.I)
_DSML_TAG = re.compile(
    r'<\s*(/?)\s*[|｜]{1,2}\s*DSML\s*[|｜]{1,2}\s*([a-z_]+)([^<>]*)>', re.I)


def internal_output(text):
    value=str(text or '')
    return bool(_DSML_MARKER.search(value)
                or re.search(r'<\/?(?:tool_call|function_call|function=)|\[(?:SEARCH|搜索)\s*[:：]|"action"\s*:\s*"tool"',value,re.I)
                or re.search(r'"(?:tool|name)"\s*:\s*"(?:search_web|read_webpage|search_baike|search_knowledge|list_native_stickers|preview_native_stickers)"',value))


def _dsml_action(text, tool_arguments):
    """Decode one complete provider tool envelope, then use normal validation.

    Never execute partial/multiple calls or infer a tool from ordinary prose.
    The registered signature, rather than model output, determines whether a
    structured request may be encoded for one of our JSON-string tools.
    """
    invalid = {'action': 'invalid'}
    if len(text) > 64000 or '<!' in text:
        return invalid
    # Some providers escape newlines/tag delimiters when serializing DSML.
    # Leave JSON string escapes (e.g. \\n, \") intact.
    text = re.sub(r'\\[ \t]*\r?\n', '\n', text)
    text = re.sub(r'\\(?=[<>=])', '', text)
    xml = _DSML_TAG.sub(lambda m: '<' + m[1] + m[2].lower() + m[3] + '>', text)
    try:
        root = ElementTree.fromstring(xml)
        if (root.tag not in ('calls', 'function_calls') or root.attrib
                or (root.text or '').strip() or len(root) != 1):
            return invalid
        invoke = root[0]
        if (invoke.tag != 'invoke' or set(invoke.attrib) != {'name'}
                or (invoke.text or '').strip() or (invoke.tail or '').strip()):
            return invalid
        name = invoke.attrib['name']
        if not re.fullmatch(r'[a-zA-Z_][a-zA-Z_0-9]*', name):
            return invalid
        arguments = {}
        for parameter in invoke:
            if (parameter.tag != 'parameter' or len(parameter)
                    or set(parameter.attrib) - {'name', 'string'}
                    or 'name' not in parameter.attrib or (parameter.tail or '').strip()):
                return invalid
            key = parameter.attrib['name']
            if not key or key in arguments:
                return invalid
            value = parameter.text or ''
            is_string = parameter.attrib.get('string', 'true').lower()
            if is_string not in ('true', 'false'):
                return invalid
            arguments[key] = json.loads(value) if is_string == 'false' else value
        # Compatibility providers sometimes put the entire function argument
        # object in a parameter literally called "arguments".
        if set(arguments) == {'arguments'}:
            arguments = arguments['arguments']
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            return invalid
        expected = (tool_arguments or {}).get(name)
        if expected == 'request':
            if set(arguments) == {'request'}:
                if isinstance(arguments['request'], dict):
                    arguments = {'request': json.dumps(arguments['request'], ensure_ascii=False)}
            else:
                arguments = {'request': json.dumps(arguments, ensure_ascii=False)}
        return {'action': 'tool', 'tool': name, 'arguments': arguments}
    except (ElementTree.ParseError, ValueError, TypeError):
        return invalid


def parse_action(raw, *, tool_arguments=None):
    text=str(raw or '').strip()
    if _DSML_MARKER.search(text):
        return _dsml_action(text, tool_arguments)
    wrappers=re.findall(r'<(?:tool_call|function_call)\s*>(.*?)</(?:tool_call|function_call)\s*>',text,re.I|re.S)
    if wrappers:
        if len(wrappers)!=1:return {'action':'invalid'}
        text=wrappers[0].strip()
    if text.startswith('```') and text.endswith('```'):
        text=text.split('\n',1)[-1].rsplit('```',1)[0].strip()
    if text.startswith(('{','[')):
        try:value=json.loads(text)
        except ValueError:return {'action':'invalid'}
        if not isinstance(value,dict):return {'action':'invalid'}
        if 'action' not in value and isinstance(value.get('function'),dict):value=value['function']
        if 'action' not in value and isinstance(value.get('name'),str):
            arguments=value.get('arguments',value.get('parameters',{}))
            if isinstance(arguments,str):
                try:arguments=json.loads(arguments)
                except ValueError:return {'action':'invalid'}
            return {'action':'tool','tool':value['name'],'arguments':arguments}
        return value
    if internal_output(text):return {'action':'invalid'}
    return None
