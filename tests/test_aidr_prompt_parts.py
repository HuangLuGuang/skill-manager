from backend.aidr_sessions import prompt_content
from backend import models
from backend.aidr_models import AidrHookEvent
from tests.test_aidr_api import service
from tests.test_aidr_content import fragment, issue, configure
from tests.test_aidr_hooks import hook_batch, send
from tests.test_aidr_messages import message_event, issued_policy
from tests.test_aidr_operations import upload


def test_split_prompt_upload_and_independent_truncation(service):
    client, factory = service
    policy = issued_policy(client, factory)
    e = message_event('user', 'unspecified')
    e['message'].update(policy=policy, content_status='partial', contents=[
        fragment('完整问题', 'prompt', 'message.input.request'),
        dict(fragment('# Files mentioned by the user:', 'prompt', 'message.input.context'), truncated=True, source_bytes=1800),
    ])
    assert upload(client, e).status_code == 200
    assert upload(client, e).status_code == 200
    with factory() as db:
        row = db.query(models.AidrEvent).one()
        data = prompt_content(db, 'one', [-row.id])[-row.id]
        assert data['display_text'] == data['text'] == '完整问题'
        assert data['context_text'] == '# Files mentioned by the user:'
        assert data['truncations'] == [dict(part='context', stored=30, original=1800, fragment=1024, event=2048)]
    hook = hook_batch()
    hook['records'][0]['event'].update(schema_version=2, hook_event='UserPromptSubmit', kind='turn.submit',
        policy=issue(client, stream='b'*32), content_status='captured', contents=[
            fragment('完整问题', 'prompt', 'hook.prompt.request'),
            fragment('# Files mentioned by the user:\n## My request:\n', 'prompt', 'hook.prompt.context')])
    response = send(client, hook)
    assert response.status_code == 200, response.text
    assert response.json()['durable']
    with factory() as db:
        row = db.query(AidrHookEvent).one()
        data = prompt_content(db, 'one', [row.id])[row.id]
        assert data['display_text'] == '完整问题' and not data['truncations']


def test_legacy_prompt_reports_full_input_bytes(service):
    client, factory = service
    configure(factory)
    hook = hook_batch()
    text = '# Files mentioned by the user:\n/file\n## My request:\n问题'
    hook['records'][0]['event'].update(schema_version=2, hook_event='UserPromptSubmit', kind='turn.submit',
        policy=issue(client, stream='b'*32), content_status='partial',
        contents=[dict(fragment(text, 'prompt', 'hook.prompt'), source_bytes=1039, truncated=True)])
    response = send(client, hook)
    assert response.status_code == 200, response.text
    with factory() as db:
        row = db.query(AidrHookEvent).one()
        data = prompt_content(db, 'one', [row.id])[row.id]
        assert data['display_text'] == '问题' and data['text'] == text
        assert data['truncations'][0] == dict(part='input', stored=len(text.encode()), original=1039, fragment=1024, event=2048)
