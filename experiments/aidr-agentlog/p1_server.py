"""Isolated P1 acceptance server using production auth/client/AIDR routers.

Only loopback, an explicit temporary database and synthetic identities are used.
The deterministic captcha and minimal branding responses are test fixtures.
"""
import argparse
import asyncio
import json
import os
import pathlib
import secrets
import sys
import time
from contextlib import asynccontextmanager, suppress

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
parser = argparse.ArgumentParser()
parser.add_argument("--state-dir", required=True)
parser.add_argument("--port", type=int, default=41873)
parser.add_argument("--fault-marker", help="Optional private file naming an allowed GET route or PUT /api/system/aidr-redaction for bounded browser failure acceptance")
parser.add_argument("--runtime-client-id", default="aidr-p1-acceptance", help="Owned runtime-governance fixture device for exact GET fault injection")
parser.add_argument("--runtime-policy-owner-fixture", action="store_true", help="Create a separate fictional super-admin for default-policy acceptance; never change existing account roles")
parser.add_argument("--delay-marker", help="Optional private file naming one exact test approval route to delay by eight seconds")
parser.add_argument("--delay-seconds", type=int, choices=range(1, 31), default=8, help="Bounded delay for the owned approval browser race probe")
parser.add_argument("--delay-client-id", choices=("aidr-p1-acceptance", "aidr-p3-ui-second"), default="aidr-p1-acceptance", help="Owned fixture device whose exact approval route may be delayed")
args = parser.parse_args()
state = pathlib.Path(args.state_dir).resolve()
state.mkdir(parents=True, exist_ok=True, mode=0o700)
os.environ["SQLITE_PATH"] = str(state / "platform.db")
key_file = state / "session-signing-key"
try:
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    if key_file.is_symlink() or key_file.stat().st_mode & 0o077:
        raise RuntimeError("acceptance_key_permissions_invalid")
else:
    with os.fdopen(fd, 'w') as output:
        output.write(secrets.token_urlsafe(48))
os.environ["SECRET_KEY"] = key_file.read_text().strip()

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from backend import auth, iam, models
from backend.api_errors import ApiError, api_error_handler, http_error_handler, validation_error_handler
from backend.routers import aidr, aidr_enforcement, auth as auth_routes, clients, iam as iam_routes, access_tokens, system, external_ai_gateways, agents, llm_gateway
from backend.routers.access_tokens import _hash_token
from backend.sqlite_db import Base, SessionLocal, engine

Base.metadata.create_all(engine)
from backend.aidr_migrations import upgrade_aidr_schema
upgrade_aidr_schema(engine)
with SessionLocal() as db:
    iam.initialize(db)
    if not db.query(models.User).filter_by(username="aidr-review").first():
        password = secrets.token_urlsafe(18)
        user = models.User(username="aidr-review", hashed_password=auth.get_password_hash(password), role="admin")
        db.add(user)
        db.flush()
        fixture = {"username": user.username, "password": password, "captcha": "aidr", "client_id": "aidr-p1-acceptance"}
        db.add(models.ManagedClient(client_id=fixture["client_id"], name="AIDR P1 acceptance", hostname="isolated-local-test", os="darwin", arch="arm64", client_version="p1-local", registered_by=user.username))
        db.add(models.AidrDevice(client_id=fixture["client_id"], created_by=user.username))
        token = secrets.token_urlsafe(36)
        db.add(models.AccessToken(name="AIDR acceptance only", token_type="client", token_hash=_hash_token(token), token_prefix=token[:8], scopes_json='["aidr:heartbeat","aidr:report-events"]', bound_client_id=fixture["client_id"], created_by=user.username))
        db.commit()
        (state / "fixture.json").write_text(json.dumps(fixture))
        (state / "device-token").write_text(token)
        (state / "fixture.json").chmod(0o600)
        (state / "device-token").chmod(0o600)
    if args.runtime_policy_owner_fixture and not db.query(models.User).filter_by(username="aidr-runtime-policy-owner").first():
        password = secrets.token_urlsafe(18)
        db.add(models.User(username="aidr-runtime-policy-owner", hashed_password=auth.get_password_hash(password), role="super_admin"))
        db.commit()
        owner_fixture = state / "runtime-policy-owner.json"
        fd = os.open(owner_fixture, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            json.dump({"username":"aidr-runtime-policy-owner","password":password,"captcha":"aidr"}, output)

@asynccontextmanager
async def lifespan(_):
    from backend.aidr_retention import retention_loop
    task = asyncio.create_task(retention_loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

app = FastAPI(lifespan=lifespan)

@app.middleware("http")
async def acceptance_fault(request, call_next):
    if args.delay_marker:
        marker = pathlib.Path(args.delay_marker)
        delayed = marker.read_text().strip() if marker.is_file() else ''
        prefix = f'/api/v1/clients/{args.delay_client_id}/aidr/hook-approvals/'
        suffix = request.url.path.removeprefix(prefix)
        ident = suffix.removesuffix('/decision')
        supported = (request.method == 'GET' and suffix == ident) or (request.method == 'POST' and suffix == ident + '/decision')
        if (supported and request.url.path.startswith(prefix) and len(ident) == 32
                and all(c in '0123456789abcdef' for c in ident) and delayed == request.url.path):
            witness = marker.with_suffix('.events.jsonl')
            def note(phase):
                with witness.open('a') as output:
                    output.write(json.dumps({'phase': phase, 'method': request.method,
                        'path': request.url.path, 'monotonic': time.monotonic()}) + '\n')
                witness.chmod(0o600)
            note('delay_started')
            await asyncio.sleep(args.delay_seconds)
            note('delay_finished')
    if args.fault_marker and request.method in {'GET', 'PUT'}:
        marker = pathlib.Path(args.fault_marker)
        failed_path = marker.read_text().strip() if marker.is_file() else ''
        allowed_faults = (
            '/api/v1/external-ai-gateways', '/api/v1/clients/governance/default',
            '/api/v1/clients/aidr-p1-acceptance/governance',
            '/api/v1/clients/aidr-p1-acceptance/aidr/hook-policy',
            '/api/v1/clients/aidr-p1-acceptance/aidr/hook-approvals',
            f'/api/v1/clients/{args.runtime_client_id}/runtime-governance',
        )
        approval_prefix = '/api/v1/clients/aidr-p1-acceptance/aidr/hook-approvals/'
        approval_id = request.url.path.removeprefix(approval_prefix)
        detail_fault = (failed_path == approval_prefix + '*'
                        and request.url.path.startswith(approval_prefix)
                        and len(approval_id) == 32
                        and all(c in '0123456789abcdef' for c in approval_id))
        read_fault = request.method == 'GET' and (
            (failed_path in allowed_faults and request.url.path == failed_path) or detail_fault)
        save_fault = (request.method == 'PUT'
                      and failed_path == 'PUT /api/system/aidr-redaction'
                      and request.url.path == '/api/system/aidr-redaction')
        if read_fault or save_fault:
            return JSONResponse({'error_code': 'acceptance.injected_unavailable'}, status_code=503)
    return await call_next(request)

app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
auth_routes.generate_captcha_text = lambda: "aidr"
app.include_router(auth_routes.router, prefix="/api")
app.include_router(clients.router, prefix="/api")
app.include_router(aidr.router, prefix="/api")
app.include_router(aidr_enforcement.router, prefix="/api")
app.include_router(iam_routes.router, prefix="/api")
app.include_router(access_tokens.router, prefix="/api/v1")
app.include_router(system.router, prefix="/api")
app.include_router(external_ai_gateways.router, prefix="/api")
app.include_router(agents.router, prefix="/api")
app.include_router(llm_gateway.admin_router, prefix="/api")

@app.get("/_test/ready")
def ready():
    return {"ready": True, "scope": "isolated P1 acceptance"}

@app.get("/api/system/capabilities")
def capabilities():
    return {"features": {}}

@app.get("/api/system/branding")
def branding():
    return {"name": "AIDR P1 acceptance"}

app.mount("/assets", StaticFiles(directory=ROOT / "web/dist/assets"), name="assets")

@app.get("/{path:path}")
def page(path: str):
    if path.startswith("api/"):
        raise HTTPException(404)
    candidate = ROOT / "web/dist" / path
    if candidate.is_file() and candidate.resolve().is_relative_to(ROOT / "web/dist"):
        return FileResponse(candidate)
    return FileResponse(ROOT / "web/dist/index.html")

uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
