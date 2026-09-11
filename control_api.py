"""Read-only dashboard and signed inbox. Worker API is restricted by nginx + token."""
import asyncio
import hashlib
import hmac
import json
import os
import re
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from control_store import Store
from e2e_catalog import CATALOG
from review_adapter import enrich
from share_viewer import ArchiveHub

ROOT = Path(__file__).resolve().parent
SAFE = re.compile(r'^[A-Za-z0-9-]+$')


def create_app(store=None, archive=None):
    store = store or Store(os.environ['PIPELINE_DATABASE_URL'])
    archive = archive or ArchiveHub(Path(os.getenv('PIPELINE_ARCHIVE_ROOT', '/var/lib/pr-e2e-share')))

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def authentication(request, call_next):
        path = request.url.path
        if os.environ.get('PIPELINE_AUTH_MODE')=='robot-session' and not path.startswith('/internal/'):
            from robot_session import username
            actor=await asyncio.to_thread(username,request.headers.get('cookie',''))
            # Worker read RPCs carry an internal token and never pass the public proxy.
            worker=os.environ.get('PIPELINE_WORKER_TOKEN','')
            if not actor and not (worker and hmac.compare_digest(worker,request.headers.get('x-worker-token',''))):
                return JSONResponse({'error':'请登录 Robot CI'},status_code=401)
        public_read = os.environ.get('PIPELINE_PUBLIC_READ', '').lower() == 'true' and request.method in {'GET', 'HEAD'}
        if public_read and request.query_params.get('access_token'):
            query = urlencode([(key,value) for key,value in request.query_params.multi_items() if key != 'access_token'])
            response = RedirectResponse(path + ('?' + query if query else ''), status_code=303)
            response.delete_cookie('pipeline_view_http')
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'no-referrer'
            return response
        if not public_read and path not in {'/api/health', '/webhooks/github'} and not path.startswith('/internal/'):
            token = os.environ.get('PIPELINE_VIEW_TOKEN', '')
            supplied = request.headers.get('x-pipeline-view-token') or request.query_params.get('access_token') or request.cookies.get('pipeline_view_http', '')
            if not token or not hmac.compare_digest(token, supplied):
                return JSONResponse({'error': '请使用授权分享链接打开'}, status_code=401)
            if request.query_params.get('access_token'):
                response = RedirectResponse(path, status_code=303)
                response.set_cookie('pipeline_view_http', token, httponly=True, samesite='lax', max_age=604800)
                response.headers['Cache-Control'] = 'no-store'
                response.headers['Referrer-Policy'] = 'no-referrer'
                return response
        response = await call_next(request)
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Cache-Control'] = 'no-store'
        return response

    def internal(request):
        token = os.environ.get('PIPELINE_WORKER_TOKEN', '')
        if not token or not hmac.compare_digest(token, request.headers.get('x-worker-token', '')):
            raise HTTPException(401, 'Invalid worker credential')

    def detail(run_id):
        if not SAFE.fullmatch(run_id):
            raise HTTPException(404)
        live = next(iter(store.runs(run_id)), None)
        saved = archive.get_run(run_id)
        if not saved and not live:
            raise HTTPException(404, 'Run not found')
        merged={**(saved or {}), **(live or {})}
        if saved and (saved.get('publication') or {}).get('status')=='published':
            try:
                archived=datetime.fromisoformat(saved['publication']['at'].replace('Z','+00:00'))
                previous=(live or {}).get('publication') or {}
                at=previous.get('at')
                if not at or archived>=datetime.fromisoformat(at.replace('Z','+00:00')):
                    merged['publication']=saved['publication']
            except (ValueError,KeyError,TypeError):
                pass
        return enrich(merged, archive.runs_dir)

    @app.get('/api/health')
    def health():
        state_file=archive.runs_dir.parent/'worker-state.json'
        try:worker_state=json.loads(state_file.read_text())
        except (OSError,ValueError):worker_state=None
        return {'status': 'ok', 'runner': 'Cloud control plane' if os.environ.get('PIPELINE_CLOUD_PROFILE')=='1' else 'Local WSL / ECS control plane', 'read_only': True,
                'worker_state':worker_state,
                'editor_url':os.environ.get('PIPELINE_EDITOR_URL','http://127.0.0.1:8793/'),
                'cloud_profile':os.environ.get('PIPELINE_CLOUD_PROFILE')=='1',
                'public_base_url': archive.public_base_url, 'shareable_links': True,
                'observation_mode': True, 'public_read': os.environ.get('PIPELINE_PUBLIC_READ', '').lower() == 'true'}

    @app.post('/internal/worker-state')
    async def worker_state(request: Request):
        internal(request)
        body=await request.body()
        if len(body)>8192:raise HTTPException(413)
        value=json.loads(body)
        if not isinstance(value,dict) or not isinstance(value.get('resource'),dict):raise HTTPException(400)
        from pr_pipeline_hub import atomic_json,utc_now
        saved={'worker':str(value.get('worker',''))[:100],'resource':value['resource'],'checked_at':utc_now()}
        atomic_json(archive.runs_dir.parent/'worker-state.json',saved)
        return {'ok':True}

    @app.post('/internal/artifacts')
    async def artifact_upload(request: Request):
        internal(request)
        import tempfile
        import tarfile
        from share_viewer import ingest
        total=0
        with tempfile.TemporaryFile() as stream:
            async for chunk in request.stream():
                total+=len(chunk)
                if total>2*1024**3:raise HTTPException(413,'Compressed archive exceeds 2 GiB')
                stream.write(chunk)
            stream.seek(0)
            try:return await asyncio.to_thread(ingest,archive.runs_dir.parent,stream)
            except (ValueError,OSError,tarfile.TarError,KeyError,TypeError) as error:raise HTTPException(400,'Invalid artifact archive') from error

    @app.post('/webhooks/github')
    async def webhook(request: Request):
        from cloud_config import enabled
        if not enabled('webhook'):
            return {'ignored':'automatic PR discovery disabled'}
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 2 * 1024 * 1024:
                raise HTTPException(413, 'Payload too large')
        secret = os.environ.get('PIPELINE_WEBHOOK_SECRET', '')
        expected = 'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(expected, request.headers.get('x-hub-signature-256', '')):
            raise HTTPException(401, 'Invalid signature')
        event = request.headers.get('x-github-event', '')
        delivery = request.headers.get('x-github-delivery', '')
        if event not in {'ping', 'pull_request', 'push'}:
            return {'ignored': 'event'}
        if not delivery or len(delivery) > 128:
            raise HTTPException(400, 'Invalid delivery ID')
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError('Invalid payload')
            return await asyncio.to_thread(store.receive, delivery, hashlib.sha256(body).hexdigest(), event, payload)
        except PermissionError as error:
            raise HTTPException(403, str(error))
        except (ValueError, KeyError, TypeError) as error:
            raise HTTPException(400, 'Invalid event payload') from error

    @app.get('/api/runs')
    @app.get('/api/reviews')
    def listing():
        records = {r['id']: r for r in archive.list_runs()}
        records.update({r['id']: r for r in store.runs()})
        return {'runs': sorted(records.values(), key=lambda r: r.get('created_at', ''), reverse=True)}

    @app.get('/api/e2e/suites')
    def suites():
        return {'suites': CATALOG}

    @app.get('/api/batches')
    def batches():
        return {'batches':[r for r in listing()['runs'] if r.get('kind')=='batch']}

    @app.get('/api/batches/{batch_id}')
    def batch_detail(batch_id: str):
        value=detail(batch_id)
        if value.get('kind')!='batch':raise HTTPException(404)
        return value

    @app.post('/internal/batches')
    async def batch_submit(request: Request):
        internal(request)
        from batch_store import create
        try:
            return await asyncio.to_thread(create,store,await request.json())
        except (ValueError,KeyError,TypeError) as error:
            raise HTTPException(400,str(error))

    @app.post('/internal/artifact-batches')
    async def artifact_submit(request: Request):
        internal(request)
        from artifact_batches import create
        try:
            return await asyncio.to_thread(create,store,await request.json())
        except (ValueError,KeyError,TypeError) as error:
            raise HTTPException(400,str(error))

    @app.get('/api/monitors')
    def monitors():
        return {'monitors':store.monitors()}

    @app.post('/internal/monitors/{name}')
    async def monitor_update(name: str, request: Request):
        internal(request)
        if not SAFE.fullmatch(name):
            raise HTTPException(400)
        return await asyncio.to_thread(store.set_monitor,name,await request.json())

    @app.get('/api/runs/{run_id}')
    @app.get('/api/reviews/{run_id}')
    def get_run(run_id: str):
        return detail(run_id)

    @app.get('/api/reviews/{run_id}/events')
    async def events(run_id: str, request: Request):
        detail(run_id)
        async def stream():
            last = None
            while not await request.is_disconnected():
                current = json.dumps(await asyncio.to_thread(detail, run_id), ensure_ascii=False)
                if current != last:
                    yield 'data: ' + current + '\n\n'
                    last = current
                else:
                    yield ': heartbeat\n\n'
                await asyncio.sleep(5)
        return StreamingResponse(stream(), media_type='text/event-stream')

    @app.get('/api/runs/{run_id}/stages/{stage_id}/log')
    def log(run_id: str, stage_id: str):
        detail(run_id)
        if not SAFE.fullmatch(stage_id):
            raise HTTPException(404)
        return PlainTextResponse(archive.read_log(run_id, stage_id))

    @app.get('/artifacts/{run_id}/{filename:path}')
    def artifact(run_id: str, filename: str):
        detail(run_id)
        root = (archive.runs_dir / run_id / 'artifacts').resolve()
        file = (root / filename).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise HTTPException(404)
        response = FileResponse(file)
        if os.environ.get('PIPELINE_AUTH_MODE')=='robot-session' and file.suffix.lower() in {'.html','.htm','.svg','.xml'}:
            return FileResponse(file,filename=file.name,media_type='application/octet-stream',
                                headers={'Content-Security-Policy':"sandbox; default-src 'none'"})
        # Playwright needs localStorage. Restrict network access to artifacts instead
        # of an opaque origin, which breaks its report renderer.
        if file.suffix in {'.html', '.svg'}:
            source = archive.public_base_url.rstrip('/') + '/artifacts/'
            response.headers['Content-Security-Policy'] = (
                "sandbox allow-scripts allow-same-origin allow-downloads; default-src 'none'; "
                f"script-src 'unsafe-inline' {source}; style-src 'unsafe-inline'; "
                f"img-src {source} data: blob:; media-src {source} blob:; "
                f"connect-src {source} data: blob:; worker-src blob:; font-src data:; "
                "base-uri 'none'; form-action 'none'; frame-src 'none'")
        return response

    @app.post('/internal/claim')
    async def claim(request: Request):
        internal(request)
        payload = await request.json()
        return await asyncio.to_thread(store.claim, str(payload.get('worker', 'wsl'))[:100], payload.get('repositories'))

    @app.post('/internal/deliveries/claim')
    async def delivery_claim(request: Request):
        internal(request)
        return await asyncio.to_thread(store.claim_delivery)

    @app.post('/internal/deliveries/{delivery_id}/finish')
    async def delivery_finish(delivery_id: int, request: Request):
        internal(request)
        payload = await request.json()
        try:
            return await asyncio.to_thread(store.finish_delivery, delivery_id, payload['attempts'], payload['receipt'])
        except PermissionError as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.post('/internal/runs/{run_id}/{action}')
    async def progress(run_id: str, action: str, request: Request):
        internal(request)
        if action not in {'progress', 'finish'}:
            raise HTTPException(404)
        payload = await request.json()
        try:
            return await asyncio.to_thread(store.update, run_id, payload.get('lease_token', ''), payload.get('patch', {}), action == 'finish')
        except PermissionError as error:
            raise HTTPException(409, str(error))
        except ValueError as error:
            raise HTTPException(400, str(error))

    @app.post('/internal/repositories')
    async def register(request: Request):
        internal(request)
        payload = await request.json()
        await asyncio.to_thread(store.register, int(payload['id']), payload['name'])
        return {'ok': True}

    @app.post('/internal/submit')
    async def submit(request: Request):
        internal(request)
        payload = await request.json()
        # The authenticated local caller resolves fresh metadata through GitHub.
        source = payload.get('source','local_manual')
        if source not in {'local_manual','github_poll'}:
            raise HTTPException(400,'Invalid source')
        return await asyncio.to_thread(store.receive, payload['delivery'], payload['digest'], 'pull_request', payload['event'], source)

    @app.post('/internal/recover/{run_id}')
    async def recover(run_id: str, request: Request):
        internal(request)
        try:
            return await asyncio.to_thread(store.recover, run_id, await request.json())
        except ValueError as error:
            raise HTTPException(409, str(error))

    @app.get('/assets/{filename:path}')
    def asset(filename: str):
        root = (ROOT / 'web/dist/assets').resolve()
        file = (root / filename).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise HTTPException(404)
        return FileResponse(file)

    @app.get('/')
    @app.get('/runs/{run_id}')
    @app.get('/capabilities')
    @app.get('/runners')
    @app.get('/reviews')
    @app.get('/batches')
    @app.get('/history')
    @app.get('/batches/{run_id}')
    def frontend(run_id: str = ''):
        return FileResponse(ROOT / 'web/dist/index.html', headers={'Cache-Control':'no-store'})

    return app
