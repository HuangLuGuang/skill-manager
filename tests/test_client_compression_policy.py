from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend import client_governance as governance
from backend.api_errors import ApiError
from tests.test_client_governance import db, add_client
from tests.test_client_prompt_policy import save, token


def test_compression_default_override_disable_and_inherit(db):
    add_client(db, 'one', protocol=2)
    add_client(db, 'two', protocol=2)
    one, two = token(db, 'one'), token(db, 'two')
    manual = token(db, 'one', created_by='admin', issued_by_client_token_id=None)
    save(db, 'two', None, compression={'enabled': False, 'level': 'auto'})
    save(db, governance.DEFAULT_SCOPE, None, compression={'enabled': True, 'level': 'conservative'})
    db.refresh(one); db.refresh(two); db.refresh(manual)
    assert (one.enable_compression, one.compression_level) == (True, 'conservative')
    assert not two.enable_compression and not manual.enable_compression
    save(db, 'two', None, compression=None)
    db.refresh(two)
    assert (two.enable_compression, two.compression_level) == (True, 'conservative')
    save(db, 'one', None, compression={'enabled': False, 'level': 'auto'})
    db.refresh(one)
    assert not one.enable_compression
    assert governance.policy_view(db, 'one')['compression_source'] == 'client'


def test_compression_preview_is_bound_to_settings_and_omission_preserves(db):
    add_client(db, protocol=2)
    view = save(db, 'client-1', None, compression={'enabled': True, 'level': 'aggressive'})
    view = save(db, 'client-1', {'mode': 'warn'})
    assert view['compression'] == {'enabled': True, 'level': 'aggressive'}
    change = governance.PolicyChange(expected_version=view['version'], compression={'enabled': False})
    change.preview_id = governance.preview(db, 'client-1', change)['preview_id']
    change.compression.enabled = True
    with pytest.raises(ApiError) as error:
        governance.save_policy(db, 'client-1', change, SimpleNamespace(username='admin'))
    assert error.value.code == 'client.policy_preview_required'
    db.rollback()
    with pytest.raises(ValidationError):
        governance.PolicyChange(expected_version=view['version'], compression={'level': 'invalid'})
