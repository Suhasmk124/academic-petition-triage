"""Separate simulated model/workflow service with realistic delays and real local tools."""
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from assessment import PetitionRequest
from auth import key_matches
from runtime_config import secret
from safety import check_input, PolicyViolation
from telemetry import span


@asynccontextmanager
async def lifespan(app):
    import torch
    torch.set_num_threads(int(os.getenv('TORCH_THREADS','1')))
    if os.getenv('STUB_SKIP_WARMUP','false') != 'true':
        from retrieval import resources
        await asyncio.to_thread(resources)
    app.state.ready = True
    yield


app = FastAPI(title='Simulated model service', lifespan=lifespan)
slots = asyncio.Semaphore(int(os.getenv('STUB_CONCURRENCY','8')))


@app.get('/health')
async def health():
    return {'ready':getattr(app.state,'ready',False),'simulated':True,'hosted_requests':0}


@app.post('/generate')
async def generate(request: Request):
    if secret() and not key_matches(request.headers.get('authorization','').removeprefix('Bearer ')):
        return JSONResponse(status_code=401,content={'error':'AUTHENTICATION_REQUIRED'})
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>16384: return JSONResponse(status_code=413,content={'error':'BODY_TOO_LARGE'})
    try:
        payload = PetitionRequest.model_validate_json(data)
        check_input(payload.petition)
    except (ValueError, PolicyViolation):
        return JSONResponse(status_code=422,content={'error':'INVALID_REQUEST'})
    from stub_model import run_stub
    with span('stub.workflow',parent=request.headers.get('traceparent')):
        async with slots:
            return await asyncio.to_thread(run_stub,payload.petition,float(os.getenv('TRIAGE_STUB_DELAY_SECONDS','.15')))
