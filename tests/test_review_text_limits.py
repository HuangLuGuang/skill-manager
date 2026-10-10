"""审核文本长度边界和写入前拦截。"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_manager.api import router as api_router
from backend.api_errors import ApiError, api_error_handler


@pytest.mark.parametrize(
    'action,field,actor',
    [('approve', 'note', 'approver'), ('reject', 'reason', 'reviewer')],
)
@pytest.mark.parametrize(
    'text,valid',
    [('中' * 999, True), ('😀' * 1000, True),
     ('a' * 1001, False), (' ' * 1001, False)],
)
@pytest.mark.parametrize('locale', ['zh-CN', 'en-US'])
def test_review_text_limit(
    action, field, actor, text, valid, locale, monkeypatch,
):
    entry = SimpleNamespace(
        skill_id='skill', status=SimpleNamespace(value='VETTED'),
    )
    manager = Mock()
    getattr(manager, action).return_value = entry
    monkeypatch.setattr('backend.client_task_notifications.notify_all', lambda: None)
    app = FastAPI()
    app.add_exception_handler(ApiError, api_error_handler)
    app.include_router(api_router.router)
    app.dependency_overrides[api_router.get_manager] = lambda: manager
    response = TestClient(app).post(
        f'/skills/skill/{action}', json={actor: 'admin', field: text},
        headers={'Accept-Language': locale},
    )
    assert response.status_code == (200 if valid else 422)
    if valid:
        getattr(manager, action).assert_called_once_with(
            'skill', **{actor: 'admin', field: text},
        )
    else:
        getattr(manager, action).assert_not_called()
        assert response.json()['error_code'] == f'skill.review_{field}_too_long'
        assert '1000' in response.json()['detail']
        assert ('must not exceed' in response.json()['detail']) == (locale == 'en-US')


def test_empty_approval_note_remains_optional():
    assert api_router.ApproveRequest(approver='admin').note is None
