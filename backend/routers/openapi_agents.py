"""External Agent registration, connection verification and evaluation APIs."""
import json

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from .. import models
from ..api_errors import ApiError, request_locale
from ..external_access import link_external_resource, require_openapi_scope
from ..external_access_models import ExternalResultEvent, ExternalGatewayEvent
from ..openapi_contract import success
from ..services import openapi_agents as service
from ..sqlite_db import get_db

router = APIRouter(prefix="/openapi/v1", tags=["openapi-agents"])
manage = require_openapi_scope("openapi:agent-manage")
read = require_openapi_scope("openapi:agent-read")
connect = require_openapi_scope("openapi:connection-test")
submit = require_openapi_scope("openapi:evaluation-submit")
evaluation_read = require_openapi_scope("openapi:evaluation-read")


def link_agent(request, row):
    link_external_resource(request, "agent", row.managed_agent_id, row.department_id)


@router.post("/agents", status_code=201)
def register(body: service.RegistrationCreate, request: Request, context=Depends(manage), db: Session = Depends(get_db)):
    row = service.save_registration(db, body, context)
    link_agent(request, row)
    return success(request, service.registration_response(db, row))


@router.put("/agents/{agent_id}")
def update(agent_id: service.AgentID, body: service.RegistrationUpdate, request: Request,
           context=Depends(manage), db: Session = Depends(get_db)):
    row = service.save_registration(db, body, context, agent_id=agent_id)
    link_agent(request, row)
    return success(request, service.registration_response(db, row))


@router.get("/agents/{agent_id}")
def registration(agent_id: service.AgentID, request: Request, context=Depends(read), db: Session = Depends(get_db)):
    service.begin_write(db)
    row = service.owned_registration(db, agent_id, context)
    link_agent(request, row)
    result = service.registration_response(db, row)
    db.commit()
    return success(request, result)


@router.post("/agents/{agent_id}/connection-tests", status_code=202)
def connection_test(agent_id: service.AgentID, body: service.ConnectionRequest, request: Request,
                    context=Depends(connect), db: Session = Depends(get_db)):
    service.begin_write(db)
    row = service.owned_registration(db, agent_id, context)
    service.check_revision(row, body.target_revision)
    job = service.create_job(db, row, context)
    link_agent(request, row)
    return success(request, {"test_id": job.task_id, "agent_id": job.agent_id, "target_revision": job.target_revision,
                             "status": "pending", "created_at": service.iso(job.created_at)})


@router.get("/connection-tests/{test_id}")
def connection_result(test_id: service.Identifier, request: Request, context=Depends(connect), db: Session = Depends(get_db)):
    service.begin_write(db)
    row = service.owned_job(db, test_id, context, "connection")
    task = db.query(models.SecurityScanTask).filter_by(task_id=row.task_id).one()
    service.sync_job(db, task)
    registration = service.owned_registration(db, row.agent_id, context)
    link_agent(request, registration)
    checks = json.loads(row.report_json) if row.report_json else {key: "pending" for key in ("network", "tls", "authentication", "protocol")}
    result = {"test_id": row.task_id, "agent_id": row.agent_id, "target_revision": row.target_revision, "status": row.status,
              "checks": checks, "ready": service.connection_ready(row, registration), "checked_at": service.iso(row.checked_at),
              "expires_at": service.iso(row.expires_at), "error": service.error(row, request_locale(request) == "en-US")}
    db.commit()
    return success(request, result)


@router.post("/agent-evaluations", status_code=202)
def evaluate(body: service.EvaluationRequest, request: Request, context=Depends(submit), db: Session = Depends(get_db)):
    service.begin_write(db)
    registration = service.owned_registration(db, body.agent_id, context)
    service.check_revision(registration, body.target_revision)
    row = service.create_job(db, registration, context, body=body)
    link_external_resource(request, "evaluation", row.task_id, row.department_id, row.business_request_id)
    return success(request, {"task_id": row.task_id, "business_request_id": row.business_request_id, "agent_id": row.agent_id,
        "target_revision": row.target_revision, "profile_id": row.profile_id, "profile_version": json.loads(row.profile_json)["version"],
        "evaluation_sequence": row.evaluation_sequence, "status": "pending", "created_at": service.iso(row.created_at)})


def evaluation_job(db, task_id, context, request):
    service.begin_write(db)
    row = service.owned_job(db, task_id, context, "evaluation")
    task = db.query(models.SecurityScanTask).filter_by(task_id=task_id).one()
    service.sync_job(db, task)
    db.commit()
    link_external_resource(request, "evaluation", row.task_id, row.department_id, row.business_request_id)
    return row, task


@router.get("/agent-evaluations/{task_id}")
def progress(task_id: service.Identifier, request: Request, context=Depends(evaluation_read), db: Session = Depends(get_db)):
    from .security_scans import _task_response
    row, task = evaluation_job(db, task_id, context, request)
    raw = _task_response(task).progress
    observed = max(0, int(raw.get("observed_total", 0)))
    completed = min(observed, max(0, int(raw.get("completed", 0))))
    running = min(observed - completed, max(0, int(raw.get("running", 0))))
    errors = min(completed, max(0, int(raw.get("errors", 0))))
    terminal = row.status in service.TASK_TERMINAL_STATUSES
    if terminal and row.cases_json:
        cases = json.loads(row.cases_json)
        observed = completed = len(cases)
        running, errors = 0, sum(c["status"] == "error" for c in cases)
    stage = "finished" if terminal else "pending" if task.status == "pending" else "evaluating"
    callback = db.query(ExternalResultEvent).filter_by(task_id=task_id).first()
    gateway = db.get(ExternalGatewayEvent, task_id)
    return success(request, {"task_id": task_id, "agent_id": row.agent_id, "business_request_id": row.business_request_id,
        "status": row.status, "result_ready": row.report_json is not None,
        "progress": {"stage": stage, "percent": None, "observed_total": observed, "completed": completed, "running": running, "errors": errors},
        "callback": service.delivery(callback), "gateway_sync": service.delivery(gateway, gateway=True),
        "created_at": service.iso(row.created_at), "updated_at": service.iso(task.updated_at),
        "completed_at": service.iso(row.completed_at), "error": service.error(row, request_locale(request) == "en-US")})


def require_report(row):
    if row.status not in service.TASK_TERMINAL_STATUSES:
        raise ApiError(409, "RESULT_NOT_READY", "评测结果尚未生成", "The evaluation result is not ready")
    if not row.report_json:
        raise ApiError(409, "REPORT_UNAVAILABLE", "本次报告不可用", "The report is unavailable")


@router.get("/agent-evaluations/{task_id}/result")
def result(task_id: service.Identifier, request: Request, context=Depends(evaluation_read), db: Session = Depends(get_db)):
    row, _ = evaluation_job(db, task_id, context, request)
    require_report(row)
    return success(request, json.loads(row.report_json))


@router.get("/agent-evaluations/{task_id}/cases")
def cases(task_id: service.Identifier, request: Request, cursor: str | None = Query(None, max_length=1024),
          limit: int = Query(50, ge=1, le=200), context=Depends(evaluation_read), db: Session = Depends(get_db)):
    row, _ = evaluation_job(db, task_id, context, request)
    require_report(row)
    return success(request, service.report_page(row, "cases", cursor, limit))


@router.get("/agent-evaluations/{task_id}/findings")
def findings(task_id: service.Identifier, request: Request, cursor: str | None = Query(None, max_length=1024),
             limit: int = Query(50, ge=1, le=200), context=Depends(evaluation_read), db: Session = Depends(get_db)):
    row, _ = evaluation_job(db, task_id, context, request)
    require_report(row)
    return success(request, service.report_page(row, "findings", cursor, limit))
