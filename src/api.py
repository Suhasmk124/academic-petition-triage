"""Async submission/polling API. Start the separate worker to process queued jobs."""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import ValidationError
from api_models import AcceptedRun, Feedback, RunView, Submission
from job_store import FeedbackUnavailable, JobStore, QueueFull
from safety import PolicyViolation, check_input
from service_config import ServiceSettings


def create_app(settings=None, store=None):
    settings = settings or ServiceSettings.from_env()
    store = store or JobStore(settings.db_path)

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        yield

    app = FastAPI(title='Academic Petition Triage', version='0.5.0', lifespan=lifespan)
    web = Path(__file__).resolve().parent / 'web'
    app.mount('/assets', StaticFiles(directory=web), name='assets')

    @app.get('/', include_in_schema=False)
    async def portal():
        return FileResponse(web / 'index.html', headers={'Cache-Control': 'no-cache'})

    @app.get('/handbook', include_in_schema=False)
    async def handbook():
        return FileResponse(web.parents[1] / 'data/raw/UG-HandBook-25-26.pdf', media_type='application/pdf')
    app.state.store = store
    app.state.settings = settings

    @app.middleware('http')
    async def correlation(request, call_next):
        request.state.correlation_id = str(uuid4())
        started = time.monotonic()
        response = await call_next(request)
        response.headers['X-Correlation-ID'] = request.state.correlation_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path == '/' or request.url.path.startswith('/assets/'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        print(json.dumps({'event': 'http_request', 'correlation_id': request.state.correlation_id,
                          'method': request.method, 'status': response.status_code,
                          'latency_seconds': round(time.monotonic() - started, 4)}), flush=True)
        return response

    async def quarantine(request, body, errors, status=422, truncated=False, error='INVALID_REQUEST'):
        identifier = await asyncio.to_thread(store.quarantine, body, request.state.correlation_id, errors, truncated)
        return JSONResponse(status_code=status, content={'error': error, 'quarantine_id': identifier,
                            'correlation_id': request.state.correlation_id, 'details': errors,
                            'workflow_started': False})

    async def validated_body(request, model):
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
            validated = model.model_validate(payload)
        except (ValueError, UnicodeDecodeError) as exc:
            errors = exc.errors(include_input=False, include_context=False, include_url=False) if isinstance(exc, ValidationError) else [{'type': 'malformed_json'}]
            return await quarantine(request, bytes(body), errors)
        request.state.validated_body = bytes(body)
        return validated

    async def policy_gate(request, text):
        try:
            check_input(text)
        except PolicyViolation as exc:
            return await quarantine(request, request.state.validated_body,
                                    [{'type': reason} for reason in exc.reasons], 403, error='CONTENT_REQUIRES_REVIEW')

    @app.post('/petitions', response_model=AcceptedRun, status_code=202, openapi_extra={
        'requestBody': {'required': True, 'content': {'application/json': {'schema': Submission.model_json_schema()}}}})
    async def submit(request: Request):
        submission = await validated_body(request, Submission)
        if isinstance(submission, JSONResponse):
            return submission
        rejected = await policy_gate(request, submission.petition)
        if rejected is not None:
            return rejected
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

    @app.get('/runs/{run_id}/feedback')
    async def get_feedback(run_id: UUID):
        if await asyncio.to_thread(store.get, str(run_id)) is None:
            raise HTTPException(404, 'Run not found')
        return {'feedback': await asyncio.to_thread(store.get_feedback, str(run_id))}

    @app.put('/runs/{run_id}/feedback', openapi_extra={
        'requestBody': {'required': True, 'content': {'application/json': {'schema': Feedback.model_json_schema()}}}})
    async def feedback(run_id: UUID, request: Request):
        payload = await validated_body(request, Feedback)
        if isinstance(payload, JSONResponse):
            return payload
        rejected = await policy_gate(request, payload.comment)
        if rejected is not None:
            return rejected
        try:
            saved = await asyncio.to_thread(store.save_feedback, str(run_id), payload.rating, payload.category, payload.comment.strip())
        except KeyError:
            raise HTTPException(404, 'Run not found')
        except FeedbackUnavailable:
            raise HTTPException(409, 'Feedback requires a completed run')
        return {'feedback': saved}

    @app.get('/quality-samples')
    async def quality_samples(limit: int = Query(default=20, ge=1, le=100)):
        return {'policy': 'All failures, escalations and negative feedback prioritized; stable 10% of other completed runs.',
                'samples': await asyncio.to_thread(store.quality_samples, limit)}

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
