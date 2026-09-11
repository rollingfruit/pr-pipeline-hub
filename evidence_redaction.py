"""Sanitize exported evidence while keeping original files in private storage."""
import base64
import io
import json
import os
from pathlib import Path
import re
import zipfile

PRIVATE_KEYS={'password','passwd','api_key','apikey','authorization','cookie','set-cookie',
              'x-auth-token','x-worker-token','access_token','refresh_token','daemon_token','token'}


def known_secrets(root):
    values=set()
    def collect(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if any(part in key.lower() for part in ('password','passwd','token','api_key','secret')) and isinstance(item,str) and len(item)>5:
                    values.add(item)
                else:collect(item)
        elif isinstance(value,list):
            for item in value:collect(item)
    settings=os.environ.get('E2E_SETTINGS_FILE')
    paths=list((root/'private').glob('*.json'))
    if settings:paths.append(Path(settings))
    for p in paths:
        collect(json.loads(p.read_text()))
    for key,value in os.environ.items():
        if any(part in key.lower() for part in ('password','token','api_key')) and len(value)>5:
            values.add(value)
    return values


def sanitize(data,secrets):
    if data.startswith(b'PK\x03\x04'):
        output=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(data)) as source,zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                if info.file_size>256*1024**2:raise ValueError('Evidence member exceeds redaction budget')
                target.writestr(info,sanitize(source.read(info),secrets))
        return output.getvalue()
    try:text=data.decode('utf-8')
    except UnicodeDecodeError:return data
    for value in sorted(secrets,key=len,reverse=True):
        text=text.replace(value,'[REDACTED]')
        text=text.replace(json.dumps(value)[1:-1],'[REDACTED]')
    def clean(value):
        if isinstance(value,list):return [clean(item) for item in value]
        if not isinstance(value,dict):return value
        result={key:('[REDACTED]' if key.lower() in PRIVATE_KEYS else clean(item)) for key,item in value.items()}
        if str(value.get('name','')).lower() in PRIVATE_KEYS and 'value' in result:
            result['value']='[REDACTED]'
        return result
    lines=[]
    for line in text.splitlines(keepends=True):
        try:
            parsed=json.loads(line)
            lines.append(json.dumps(clean(parsed),ensure_ascii=False)+ ('\n' if line.endswith('\n') else ''))
        except ValueError:lines.append(line)
    text=''.join(lines)
    text=re.sub(r'data:application/zip;base64,([A-Za-z0-9+/=]+)',
        lambda match:'data:application/zip;base64,'+base64.b64encode(sanitize(base64.b64decode(match[1]),secrets)).decode(),text)
    return text.encode()
