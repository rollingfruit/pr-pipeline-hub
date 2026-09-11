"""AgentServer outbound messages; never impersonate a desktop user or task."""
import json
import os
from datetime import datetime
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
GROUP = '1002029982597251125'
AGENT = '2b6d5bef-1a74-4e13-8638-eb64ea35e869'
WORKSPACE = 'f599cfe5-bc2b-4900-bf05-5e2dbe18a431'
ACCOUNT = '5pupqcim1qwe@cb8603490ca'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('AgentServer redirect rejected; credentials not forwarded')


def configuration():
    path = Path(os.environ.get('PIPELINE_NEWLINK_CONFIG', ROOT/'.runtime/newlink-delivery.json'))
    if not path.is_file():
        raise RuntimeError('NewLink outbound is not configured: service credential and confirmed target required')
    config = json.loads(path.read_text())
    if config.get('enabled') is not True:
        raise RuntimeError('NewLink outbound is not configured/enabled')
    if (config.get('group_id'), config.get('agent_id'), config.get('workspace_id'), config.get('agent_account')) != (GROUP,AGENT,WORKSPACE,ACCOUNT):
        raise ValueError('NewLink target differs from the approved group and bot')
    endpoint = urlsplit(config.get('base_url',''))
    if endpoint.scheme != 'https' or not endpoint.hostname or endpoint.username or endpoint.query or endpoint.fragment:
        raise ValueError('Authenticated AgentServer HTTPS URL required')
    if not config.get('tenant_id') or type(config.get('corp_id')) is not int or not config.get('enabled_after'):
        raise ValueError('Tenant, corp and activation time must be configured explicitly')
    return config


def payload(hub, item, config):
    run = item['run']
    activated = datetime.fromisoformat(config['enabled_after'].replace('Z','+00:00'))
    created = datetime.fromisoformat(run['created_at'].replace('Z','+00:00'))
    if created < activated:
        raise ValueError('Historical delivery excluded; explicit audited replay required')
    key = f"pipeline:{run['id']}:{item['phase']}"
    url = hub._run_web_url(hub.public_base_url,run['id'])
    if urlsplit(url).hostname in {None,'localhost','127.0.0.1','::1'}:
        raise ValueError('Team-visible pipeline URL required')
    text = '\n'.join([
        f"PR #{run['pr_number']} · {'已入队' if item['phase']=='queued' else '检视结果'}",
        run.get('summary','等待检视')[:140],
        '执行：本机 Codex / WSL；观察模式',
        '流水线：'+url, 'PR：'+run['pr_url']])
    if len(text)>500:
        raise ValueError('Inline group message exceeds 500 characters')
    # Webhook events have no source chat message. Do not invent one.
    source = run.get('newlink_source_message_id','')
    return {'requestId':key,'agentMsgId':key,'sourceRequestId':run['id'],
        'sourceMsgId':source,'replyToMsgId':source,'chatType':1,
        'agentAccount':config['agent_account'],'receiverAccount':'','groupId':config['group_id'],
        'tenantId':config['tenant_id'],'corpId':config['corp_id'],'teamId':config.get('team_id',''),
        'botUsername':'xiao-commitor','contentType':0,'contentMode':0,'content':text,
        'resourceList':[],'traceId':run['id'],'eventId':run['id']}


def receipt(result):
    message = result.get('imMsgId') or result.get('im_msg_id')
    if type(result.get('code')) is not int or result['code'] not in {0,2602} or not isinstance(message,str) or not message.strip():
        raise RuntimeError('AgentServer did not acknowledge a real message ID')
    return {'ok':True,'receipt_id':message,'message_delivered':True,
            'agent_execution':'not_requested','provider':'newlink-agentserver'}


def send(hub, item):
    config = configuration()
    body = payload(hub,item,config)
    token = Path(config['token_file']).read_text().strip()
    if not token:
        raise RuntimeError('AgentServer service credential is empty')
    request = urllib.request.Request(config['base_url'].rstrip('/')+'/v1/agent/messages/reply',
        json.dumps(body,ensure_ascii=False).encode(), {'Content-Type':'application/json','X-Auth-Token':token})
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:
            result = json.loads(response.read(65536))
    except urllib.error.HTTPError as error:
        raise RuntimeError('AgentServer HTTP '+str(error.code)+'; no confirmed delivery') from None
    return receipt(result)
