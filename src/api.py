"""Async submission/polling API. Start the separate worker to process queued jobs."""
import asyncio
import json
import time
import os
from hmac import compare_digest
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import ValidationError
from api_models import AcceptedRun, Feedback, RunView, Submission, PrivateSubmission, AccountInput, OfficerReview
from job_store import FeedbackUnavailable, JobStore, QueueFull
from safety import PolicyViolation, check_input
from service_config import ServiceSettings
from operations import Operations, cache_key
from auth import authenticated, key_matches, session_cookie
from runtime_config import secret
from workspace_accounts import issue_session, session_user, password_hash, verify_password
from telemetry import HttpMetrics, span, carrier

DEMO_PASSWORD = 'pass@1234'


def create_app(settings=None, store=None):
    settings = settings or ServiceSettings.from_env()
    store = store or JobStore(settings.db_path)
    if settings.private_records and not secret():
        raise ValueError("Private records require a dedicated workspace key.")

    @asynccontextmanager
    async def lifespan(app):
        await asyncio.to_thread(store.initialize)
        if settings.role_demo:
            for role in ('student', 'reviewer'):
                encoded = await asyncio.to_thread(password_hash, DEMO_PASSWORD)
                await asyncio.to_thread(store.create_account, role, role, encoded)
        yield

    app = FastAPI(title='Academic Petition Triage', version='1.0.0', lifespan=lifespan)
    cookie_name = ('triage_showcase_session' if settings.role_demo else
                   'triage_private_session' if settings.private_records else 'triage_session')
    metrics = HttpMetrics()
    operations = Operations(store)
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
        public = request.url.path in ('/', '/health', '/ready', '/auth/session') or request.url.path.startswith('/assets/')
        if not public:
            if settings.role_accounts:
                key = secret()
                authorization = request.headers.get('authorization','')
                username = ('admin' if authorization.startswith('Bearer ') and key_matches(authorization[7:])
                            else session_user(request.cookies.get(cookie_name,''),key))
                account = (await asyncio.to_thread(store.account, username)
                           if username and username != 'admin' else None)
                if username == 'admin':
                    request.state.identity = ('admin','admin')
                elif account:
                    request.state.identity = (username,account['role'])
                else:
                    return JSONResponse(status_code=401,content={'error':'AUTHENTICATION_REQUIRED'})
                role = request.state.identity[1]
                if role == 'student':
                    segments = request.url.path.strip('/').split('/')
                    if len(segments)>=2 and segments[0]=='runs':
                        if not await asyncio.to_thread(store.owns_run,segments[1],username):
                            return JSONResponse(status_code=404,content={'detail':'Run not found'})
                    elif request.url.path not in ('/petitions/private','/workspace/me','/workspace/cases','/auth/logout','/handbook'):
                        return JSONResponse(status_code=403,content={'detail':'Staff access required'})
            elif not authenticated(request, cookie_name):
                metrics.requests.labels('authentication',401).inc()
                return JSONResponse(status_code=401, content={'error':'AUTHENTICATION_REQUIRED'})
        origin = request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin and urlsplit(origin).netloc != request.url.netloc:
            metrics.requests.labels('origin',403).inc()
            return JSONResponse(status_code=403, content={'error':'ORIGIN_REJECTED'})
        with span('http.request', parent=request.headers.get('traceparent'), correlation_id=request.state.correlation_id) as current:
            response = await call_next(request)
            route = getattr(request.scope.get('route'), 'path', '/assets' if request.url.path.startswith('/assets/') else 'unmatched')
            current.set_attribute('http.route', route)
            current.set_attribute('http.status_code', response.status_code)
            response.headers['X-Trace-ID'] = format(current.get_span_context().trace_id, '032x')
        metrics.requests.labels(route, response.status_code).inc()
        metrics.duration.labels(route).observe(time.monotonic()-started)
        response.headers['X-Correlation-ID'] = request.state.correlation_id
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if settings.private_records:
            response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Frame-Options'] = 'DENY'
        if request.url.path == '/' or request.url.path.startswith('/assets/'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        print(json.dumps({'event': 'http_request', 'correlation_id': request.state.correlation_id,
                          'method': request.method, 'status': response.status_code,
                          'latency_seconds': round(time.monotonic() - started, 4)}), flush=True)
        return response

    @app.post('/auth/session', include_in_schema=False)
    async def login(request: Request):
        try:
            allowed=await asyncio.to_thread(operations.allow, 'login:'+(request.client.host if request.client else 'local'), 10)
        except Exception:
            return JSONResponse(status_code=503,content={'error':'RATE_LIMIT_BACKEND_UNAVAILABLE'})
        if not allowed:
            return JSONResponse(status_code=429, content={'error':'RATE_LIMITED'}, headers={'Retry-After':'60'})
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>2048:
                return JSONResponse(status_code=413, content={'error':'INVALID_REQUEST'})
        try:
            credentials = json.loads(body)
            candidate = credentials.get('api_key', '')
            username = credentials.get('username','').strip().lower() if settings.role_accounts else 'admin'
            if settings.role_accounts and username != 'admin':
                account = await asyncio.to_thread(store.account, username)
                valid = bool(account and isinstance(candidate,str) and len(candidate)<=128 and
                             await asyncio.to_thread(verify_password,candidate,account['password_hash']))
            else:
                valid = isinstance(candidate, str) and (
                    compare_digest(candidate.encode(), DEMO_PASSWORD.encode()) if settings.role_demo
                    else key_matches(candidate))
        except (ValueError, AttributeError, TypeError):
            valid = False
        if secret() and not valid:
            return JSONResponse(status_code=401, content={'error':'AUTHENTICATION_REQUIRED'})
        response = JSONResponse({'authenticated':True})
        if secret():
            response.set_cookie(cookie_name, issue_session(username,secret()) if settings.role_accounts else session_cookie(), max_age=3600, httponly=True,
                                samesite='strict', secure=request.url.scheme == 'https')
        return response

    async def quarantine(request, body, errors, status=422, truncated=False, error='INVALID_REQUEST'):
        if settings.private_records:
            body = b""
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
        if settings.role_demo:
            identity(request, {'admin'})
        elif settings.private_records:
            raise HTTPException(404, 'Use the private petition endpoint in this workspace')
        submission = await validated_body(request, Submission)
        if isinstance(submission, JSONResponse):
            return submission
        rejected = await policy_gate(request, submission.petition)
        if rejected is not None:
            return rejected
        return await enqueue(request, submission)

    async def enqueue(request, submission, private=False, attachment=None):
        try:
            allowed = await asyncio.to_thread(operations.allow, request.client.host if request.client else 'local', int(os.getenv('TRIAGE_RATE_LIMIT', '0')))
        except Exception:
            return JSONResponse(status_code=503, content={'error':'RATE_LIMIT_BACKEND_UNAVAILABLE','workflow_started':False})
        if not allowed:
            return JSONResponse(status_code=429, content={'error':'RATE_LIMITED','workflow_started':False}, headers={'Retry-After':'60'})
        fingerprint = await asyncio.to_thread(cache_key, submission.petition, settings.mode) if not private and settings.mode != 'hosted' and int(os.getenv('TRIAGE_CACHE_TTL', '0')) > 0 else None
        try:
            run_id = await asyncio.to_thread(store.submit, submission.petition, settings.mode,
                                             request.state.correlation_id, settings.queue_capacity, carrier(), fingerprint,
                                             submission.facts.model_dump() if submission.facts else None, private, attachment,
                                             getattr(request.state,'identity',(None,None))[0])
        except QueueFull:
            return JSONResponse(status_code=503, headers={'Retry-After': '1'},
                                content={'error': 'QUEUE_FULL', 'workflow_started': False})
        return AcceptedRun(run_id=run_id, mode=settings.mode, correlation_id=request.state.correlation_id,
                           poll_url=f'/runs/{run_id}')

    def require_private_workspace():
        if not settings.private_records or not secret():
            raise HTTPException(404, 'Private records are disabled in this workspace')

    def identity(request, roles=None):
        if not settings.role_accounts:
            raise HTTPException(404,'Role accounts are disabled')
        user,role=request.state.identity
        if roles is not None and role not in roles:
            raise HTTPException(403,'Staff access required')
        return user,role

    @app.get('/workspace/me')
    async def workspace_me(request: Request):
        user,role=identity(request)
        return {'username':user,'role':role}

    @app.post('/auth/logout',status_code=204)
    async def logout():
        response=Response(status_code=204)
        response.delete_cookie(cookie_name)
        return response

    @app.get('/workspace/cases')
    async def workspace_cases(request: Request):
        user,role=identity(request)
        return await asyncio.to_thread(store.private_cases,user if role=='student' else None)

    @app.post('/workspace/accounts',status_code=201)
    async def create_account(request: Request):
        identity(request,{'admin'})
        if settings.role_demo:
            raise HTTPException(403, 'This demo uses the three preset accounts')
        payload=await validated_body(request,AccountInput)
        if isinstance(payload,JSONResponse):
            return payload
        if payload.username=='admin':
            raise HTTPException(409,'That username is reserved')
        encoded=await asyncio.to_thread(password_hash,payload.password)
        if not await asyncio.to_thread(store.create_account,payload.username,payload.role,encoded):
            raise HTTPException(409,'That username already exists')
        return {'username':payload.username,'role':payload.role}

    @app.put('/runs/{run_id}/officer-review')
    async def save_officer_review(run_id: UUID,request: Request):
        reviewer,_=identity(request,{'admin','reviewer'})
        payload=await validated_body(request,OfficerReview)
        if isinstance(payload,JSONResponse):
            return payload
        if not await asyncio.to_thread(store.record_officer_review,str(run_id),reviewer,payload.outcome,payload.note):
            raise HTTPException(409,'Open a completed private case before recording a review')
        return await asyncio.to_thread(store.officer_review,str(run_id))

    @app.post('/petitions/private', response_model=AcceptedRun, status_code=202)
    async def submit_private(request: Request):
        require_private_workspace()
        if settings.role_accounts:
            identity(request,{'student','admin'})
        from supporting_documents import decode_attachment, MAX_REQUEST_BYTES
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
            raise HTTPException(415,'Expected JSON')
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > MAX_REQUEST_BYTES:
                raise HTTPException(413,'Attachment must be 5 MiB or smaller')
            body.extend(chunk)
        try:
            submission = PrivateSubmission.model_validate_json(body)
        except ValueError:
            raise HTTPException(422,'Check the petition and attachment size')
        if settings.role_demo and not submission.synthetic:
            raise HTTPException(422, 'Confirm that this petition and attachment are fictional')
        try:
            check_input(submission.petition)
        except PolicyViolation:
            # Never save rejected private text or attachment bytes to quarantine.
            raise HTTPException(403,'The petition requires manual review')
        try:
            attachment = decode_attachment(submission.attachment.content) if submission.attachment else None
        except ValueError:
            raise HTTPException(422,'Attach a PDF, PNG or JPEG file up to 5 MiB')
        return await enqueue(request, submission, private=True, attachment=attachment)

    @app.get('/runs/{run_id}/attachment')
    async def download_attachment(run_id: UUID):
        require_private_workspace()
        item = await asyncio.to_thread(store.attachment, str(run_id))
        if item is None:
            raise HTTPException(404,'Attachment not found')
        extension, content = item
        return Response(content, media_type='application/octet-stream',headers={
            'Content-Disposition':f'attachment; filename="supporting-document.{extension}"',
            'Cache-Control':'no-store', 'Content-Security-Policy':"default-src 'none'; sandbox"})

    @app.delete('/runs/{run_id}/attachment',status_code=204)
    async def delete_attachment(run_id: UUID, request: Request):
        require_private_workspace()
        if settings.role_accounts:
            identity(request,{'student','admin'})
        if not await asyncio.to_thread(store.delete_attachment,str(run_id)):
            raise HTTPException(404,'Attachment not found')
        return Response(status_code=204,headers={'Cache-Control':'no-store'})

    @app.get('/runs/{run_id}', response_model=RunView)
    async def get_run(run_id: UUID):
        result = await asyncio.to_thread(store.get, str(run_id), settings.private_records)
        if result is None:
            raise HTTPException(status_code=404, detail='Run not found')
        return result

    @app.get('/runs/{run_id}/export')
    async def export_run(run_id: UUID, format: str = Query(default='json',pattern='^(json|html)$')):
        run = await asyncio.to_thread(store.get,str(run_id))
        if run is None:
            raise HTTPException(404,'Run not found')
        if run['status'] not in ('SUCCEEDED','FAILED'):
            raise HTTPException(409,'A review packet requires a completed run')
        from review_export import review_packet, review_html
        packet=review_packet(run)
        content=review_html(packet) if format=='html' else json.dumps(packet,ensure_ascii=False,indent=2)
        return Response(content,media_type='text/html' if format=='html' else 'application/json',headers={
            'Content-Disposition':f'attachment; filename="review-{run_id}.{format}"',
            'Cache-Control':'no-store','Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})

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
        return {'status': 'ok', 'mode': settings.mode, 'private_records': settings.private_records,
                'role_accounts': settings.role_accounts, 'role_demo': settings.role_demo,
                **await asyncio.to_thread(store.health)}

    @app.get('/metrics', include_in_schema=False)
    async def prometheus():
        from prometheus_client import generate_latest, CollectorRegistry, Gauge, Histogram
        def durable():
            registry = CollectorRegistry()
            jobs = Gauge('triage_jobs', 'Durable job counts', ['status'], registry=registry)
            state = store.health()
            for status in ('QUEUED','RUNNING','SUCCEEDED','FAILED'):
                jobs.labels(status).set(state['jobs'].get(status,0))
            Gauge('triage_active_workers','Worker heartbeats within 15 seconds',registry=registry).set(state['active_workers'])
            age = Gauge('triage_oldest_queued_seconds','Queue age',registry=registry)
            counts = Gauge('triage_agent_runs_total','Persisted agent invocations',['agent','success'],registry=registry)
            durations = Gauge('triage_agent_duration_seconds_sum','Persisted agent duration sum',['agent'],registry=registry)
            calls = Gauge('triage_agent_tool_calls_total','Persisted tool calls',['agent'],registry=registry)
            retries = Gauge('triage_agent_retries_total','Persisted model transport retries',['agent'],registry=registry)
            tokens = Gauge('triage_tokens_total','Persisted reported or estimated tokens',['agent','kind'],registry=registry)
            workflow = Histogram('triage_workflow_duration_seconds', 'Time from submission to worker completion',
                                 ['status'], registry=registry, buckets=(.25,.5,1,2,3,5,8,10,15,30,60,120,240))
            for status in ('SUCCEEDED', 'FAILED'):
                workflow.labels(status)
            totals = {}
            with store.connection() as con:
                queued = con.execute("SELECT MIN(created_at) FROM jobs WHERE status='QUEUED'").fetchone()[0]
                rows = con.execute("""SELECT status, updated_at - created_at AS duration, result_json
                                      FROM jobs WHERE status IN ('SUCCEEDED','FAILED')""").fetchall()
            age.set(max(0,store.clock()-queued) if queued else 0)
            for row in rows:
                workflow.labels(row['status']).observe(max(0, row['duration']))
                if row['status'] != 'SUCCEEDED' or not row['result_json']:
                    continue
                result = json.loads(row['result_json'])
                for metric in result.get('metrics',[]):
                    agent = metric['agent']; item = totals.setdefault(agent, {'ok':0,'failed':0,'duration':0,'tools':0,'input':0,'output':0,'retries':0})
                    item['ok' if metric['success'] else 'failed']+=1; item['duration']+=metric['latency_seconds']; item['tools']+=metric['tool_calls']
                    item['retries']+=metric.get('retries',0)
                for usage in result.get('usage',[]):
                    item = totals.setdefault(usage['agent'], {'ok':0,'failed':0,'duration':0,'tools':0,'input':0,'output':0,'retries':0})
                    item['input']+=usage.get('input_tokens') or 0; item['output']+=usage.get('output_tokens') or 0
            for agent,item in totals.items():
                counts.labels(agent,'true').set(item['ok']); counts.labels(agent,'false').set(item['failed'])
                durations.labels(agent).set(item['duration']); calls.labels(agent).set(item['tools'])
                retries.labels(agent).set(item['retries'])
                for kind in ('input','output'): tokens.labels(agent,kind).set(item[kind])
            return generate_latest(registry)
        return Response(generate_latest(metrics.registry)+await asyncio.to_thread(durable), media_type='text/plain; version=0.0.4')

    @app.get('/ready')
    async def ready():
        if operations.redis:
            try:
                await asyncio.to_thread(operations.redis.ping)
            except Exception:
                return JSONResponse(status_code=503,content={'status':'not_ready','reason':'REDIS_UNAVAILABLE'})
        state = await asyncio.to_thread(store.health)
        if not state['active_workers']:
            return JSONResponse(status_code=503, content={'status': 'not_ready', 'reason': 'NO_RECENT_WORKER_HEARTBEAT'})
        return {'status': 'ready', 'mode': settings.mode}

    return app

app = create_app()
