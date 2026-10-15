from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from agent_manager.core.licensing import LicenseError, LicenseStore, MAX_FILE, canonical
from backend import auth, models
from backend.sqlite_db import get_db

router = APIRouter(prefix="/v1/license", tags=["license"])


class CustomerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    customer_id: str = Field(min_length=1, max_length=128)
    customer_name: str = Field(min_length=1, max_length=200)


@router.get("/status")
def status(db: Session = Depends(get_db), user=Depends(auth.get_current_active_user)):
    result = LicenseStore().status()
    result["registered_clients"] = db.query(models.ManagedClient).count()
    result["client_limit"] = result["current"]["limits"]["clients"] if result["current"] else None
    result["over_limit"] = result["client_limit"] is not None and result["registered_clients"] > result["client_limit"]
    return result


@router.post("/request")
def customer_request(body: CustomerRequest, user=Depends(auth.get_current_admin_user)):
    content = LicenseStore().request(body.customer_id, body.customer_name)
    return Response(canonical(content), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="customer-request.json"'})


@router.post("/import")
async def import_license(request: Request, user=Depends(auth.get_current_admin_user)):
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_FILE:
            raise LicenseError("invalid")
        content.extend(chunk)
    return LicenseStore().import_license(bytes(content), user.username)
