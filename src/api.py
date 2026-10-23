"""Async submission/polling API. Start the separate worker to process queued jobs."""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import ValidationError
from api_models import AcceptedRun, RunView, Submission
from job_store import JobStore, QueueFull
from service_config import ServiceSettings


def create_app(settings=None, store=None):
    settings = settings or ServiceSettings.from_env()
    store = store or JobStore(settings.db_path)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        yield

    app = FastAPI(title='Academic Petition Triage', version='0.4.0', lifespan=lifespan)
    web = Path(__file__).resolve().parent / 'web'
    app.mount('/assets', StaticFiles(directory=web), name='assets')

    @app.get('/', include_in_schema=False)
    async def portal():
        return FileResponse(web / 'index.html', headers={'Cache-Control': 'no-cache'})
    app.state.store = store
    app.state.settings = settings

    @app.middleware('http')
    async def correlation(request, call_next):
        request.state.correlation_id = str(uuid4())
        started = time.monotonic()
        response = await call_next(request)
        response.headers['X-Correlation-ID'] = request.state.correlation_id
        print(json.dumps({'event': 'http_request', 'correlation_id': request.state.correlation_id,
                          'method': request.method, 'status': response.status_code,
                          'latency_seconds': round(time.monotonic() - started, 4)}), flush=True)
        return response

    async def quarantine(request, body, errors, status=422, truncated=False):
        identifier = await asyncio.to_thread(store.quarantine, body, request.state.correlation_id, errors, truncated)
        return JSONResponse(status_code=status, content={'error': 'INVALID_REQUEST', 'quarantine_id': identifier,
                            'correlation_id': request.state.correlation_id, 'details': errors,
                            'workflow_started': False})

    @app.post('/petitions', response_model=AcceptedRun, status_code=202, openapi_extra={
        'requestBody': {'required': True, 'content': {'application/json': {'schema': Submission.model_json_schema()}}}})
    async def submit(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            remaining = settings.max_body_bytes - len(body)
            if len(chunk) > remaining:
                body.extend(chunk[:remaining])
                return await quarantine(request, bytes(body), [{'type': 'body_too_large'}], 413, True)
            body.extend(chunk)
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            return await quarantine(request, bytes(body), [{'type': 'json_content_type_required'}], 415)
        try:
            def reject_constant(value):
                raise ValueError('Non-standard JSON numeric constant')
            payload = json.loads(bytes(body).decode('utf-8'), parse_constant=reject_constant)
            submission = Submission.model_validate(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            errors = exc.errors(include_input=False, include_context=False, include_url=False) if isinstance(exc, ValidationError) else [{'type': 'malformed_json'}]
            return await quarantine(request, bytes(body), errors)
        try:
            run_id = await asyncio.to_thread(store.submit, submission.petition, settings.mode,
                                             request.state.correlation_id, settings.queue_capacity)
        except QueueFull:
            return JSONResponse(status_code=503, headers={'Retry-After': '1'},
                                content={'error': 'QUEUE_FULL', 'workflow_started': False})
        return AcceptedRun(run_id=run_id, mode=settings.mode, correlation_id=request.state.correlation_id,
                           poll_url=f'/runs/{run_id}')

    @app.get('/runs/{run_id}', response_model=RunView)
    async def get_run(run_id: UUID):
        result = await asyncio.to_thread(store.get, str(run_id))
        if result is None:
            raise HTTPException(status_code=404, detail='Run not found')
        return result

    @app.get('/health')
    async def health():
        return {'status': 'ok', 'mode': settings.mode, **await asyncio.to_thread(store.health)}

    @app.get('/ready')
    async def ready():
        state = await asyncio.to_thread(store.health)
        if not state['active_workers']:
            return JSONResponse(status_code=503, content={'status': 'not_ready', 'reason': 'NO_RECENT_WORKER_HEARTBEAT'})
        return {'status': 'ready', 'mode': settings.mode}

    return app

app = create_app()
