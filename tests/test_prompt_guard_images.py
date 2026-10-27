import json
import pytest
from backend import models
from backend.prompt_guard_images import collect_images
from backend.api_errors import ApiError
from backend.routers import llm_gateway as gateway
from tests.test_prompt_guard_semantic import setup_guard

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII='
def messages(url=PNG):
    return [{'role':'user','content':[{'type':'text','text':'Describe this image jane@example.com'}, {'type':'image_url','image_url':{'url':url}}]}]

def setup_image(tmp_path, monkeypatch):
    client, token, factory, model_id = setup_guard(tmp_path, monkeypatch)
    with factory() as db:
        db.get(models.ModelEndpoint,model_id).supports_multimodal = True
        db.commit()
    assert client.put('/v1/prompt-guard/config',json={'enabled':True,'model_id':model_id,'image_model_id':model_id}).status_code==200
    return client,token,factory,model_id

@pytest.mark.parametrize('mode,blocked',[('block',True),('warn',False),('log',False)])
def test_image_findings_and_audit(tmp_path,monkeypatch,mode,blocked):
    client,token,factory,model_id=setup_image(tmp_path,monkeypatch)
    with factory() as db:
        db.query(models.LlmApiKey).first().prompt_guard_mode=mode;db.commit()
    seen=[]
    async def fake(db,model,payload,**kwargs):
        content=payload['messages'][-1]['content']
        if kwargs.get('prompt_guard_review'):
            assert 'jane@example.com' not in json.dumps(payload)
            if isinstance(content,list):
                seen.append(content)
                assert content[1]['image_url']['url']==PNG
                result={'findings':[{'category':'prompt_injection','severity':'MEDIUM','image_index':0,'evidence':'Visible override instruction','reason':'Image contains malicious instructions'}]}
            else: result={'findings':[]}
            return {'choices':[{'message':{'content':json.dumps(result)}}],'usage':{'total_tokens':10}}
        return {'choices':[{'message':{'role':'assistant','content':'ok'}}]}
    monkeypatch.setattr(gateway,'_call_upstream',fake)
    result=client.post('/v1/prompt-guard/test',json={'mode':mode,'messages':messages()}).json()
    assert result['image_status']=='completed' and result['blocked']==blocked
    assert result['findings'][0]['severity']=='HIGH' and result['findings'][0]['model_severity']=='MEDIUM'
    assert result['findings'][0]['image_index']==0 and 'snippet' not in result['findings'][0]
    assert result['llm_usage']['total_tokens']==20
    response=client.post('/v1/chat/completions',headers={'Authorization':f'Bearer {token}'},json={'model':'mock-model','messages':messages()})
    assert response.status_code==(403 if blocked else 200),response.text
    with factory() as db:
        saved=json.loads(db.query(models.LlmRequestAudit).first().prompt_guard_result_json)
    assert saved['image_status']=='completed' and PNG not in json.dumps(saved)

@pytest.mark.parametrize('url',['https://127.0.0.1/private','data:image/svg+xml;base64,AAAA','data:image/png;base64,aaaa','data:image/png;base64,***'])
def test_reject_unsupported_images(url):
    with pytest.raises(ApiError):collect_images(messages(url))

def test_image_count_limit():
    with pytest.raises(ApiError):collect_images(messages()*4)

@pytest.mark.parametrize('case',['missing_model','invalid_output','bad_index','unsupported_model'])
def test_image_failure_is_not_safe(tmp_path,monkeypatch,case):
    client,_,factory,model_id=setup_image(tmp_path,monkeypatch)
    if case=='missing_model':
        client.put('/v1/prompt-guard/config',json={'enabled':True,'model_id':model_id})
    if case=='unsupported_model':
        with factory() as db:
            db.get(models.ModelEndpoint,model_id).supports_multimodal=False;db.commit()
    async def fake(db,model,payload,**kwargs):
        image=isinstance(payload['messages'][-1]['content'],list)
        raw='not json' if image else '{"findings":[]}'
        if image and case=='bad_index':raw=json.dumps({'findings':[{'category':'prompt_injection','severity':'HIGH','image_index':5,'evidence':'test','reason':'test'}]})
        return {'choices':[{'message':{'content':raw}}]}
    monkeypatch.setattr(gateway,'_call_upstream',fake)
    result=client.post('/v1/prompt-guard/test',json={'mode':'block','messages':messages()}).json()
    assert result['image_status']=='failed' and result['action']=='error' and result['llm_status']=='failed'
