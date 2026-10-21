"""Unified Agent governance audit; source permissions remain independent."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agent_manager.api.router import get_manager
from .. import audit_trail, auth, iam
from ..sqlite_db import get_db

router = APIRouter(prefix='/v1/audit-trail', tags=['audit-trail'])


@router.get('/options')
def filter_options(db: Session = Depends(get_db), manager=Depends(get_manager),
                   user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'skills:view')
    return audit_trail.options(db, manager, user)


@router.get('')
def list_events(q: str = Query('', max_length=200), agent: str = Query('', max_length=160, pattern='^(|platform:.+|local:.+)$'),
                client_id: str = Query('', max_length=128),
                category: str = Query('', pattern='^(|identity|authorization|configuration|tasks|capability|other)$'),
                result: str = Query('', pattern='^(|' + '|'.join(audit_trail.RESULTS) + ')$'),
                days: int = Query(7, ge=0, le=365), page: int = Query(1, ge=1),
                page_size: int = Query(10, ge=1, le=100), order: str = Query('desc', pattern='^(asc|desc)$'),
                db: Session = Depends(get_db), manager=Depends(get_manager),
                user=Depends(auth.get_current_admin_user)):
    iam.check(db, user, 'skills:view')
    return audit_trail.page(db, manager, user, q=q.strip(), agent=agent, client_id=client_id,
                            category=category, result=result, days=days, page=page, page_size=page_size, order=order)
