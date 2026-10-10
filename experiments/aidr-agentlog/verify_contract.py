"""Independent Python validation of the shared local ingestion event vectors."""
import datetime,json,pathlib,re
path=pathlib.Path(__file__).resolve().parents[2]/'scanner/internal/aidr/agentlog/testdata/contracts.json'
TOKEN=re.compile(r'^[A-Za-z0-9_.:/@+-]{1,256}$')
def valid(e):
 try:
  assert type(e['schema_version']) is int and e['schema_version']==1
  for key in ['event_id','logical_event_id','source_id','source_instance_id','logical_call_id','content_digest','evidence_digest']:assert re.fullmatch('[0-9a-fA-F]{64}',e[key])
  assert e['agent'] in ['claude','codex'] and e['source']=='agent_log' and e['process_relation']=='unknown'
  for key in ['source_seq','record_offset']:assert type(e[key]) is str and re.fullmatch('[0-9]+',e[key]) and int(e[key])<=2**63-1
  assert type(e['block']) is int and e['block']>=0 and int(e['source_seq'])-int(e['record_offset'])==e['block']
  assert type(e['content_bytes']) is int and 0<e['content_bytes']<=4<<20
  assert TOKEN.fullmatch(e['native_call_id']) and len(e['agent_version'])<=80
  for key in ['observed_at','received_at']:assert datetime.datetime.fromisoformat(e[key].replace('Z','+00:00')).year>1
  assert e['kind'] in ['tool_call','tool_result'] and e['outcome'] in ['unknown','success','error']
  if e['kind']=='tool_call':assert TOKEN.fullmatch(e['tool'])
  return True
 except (AssertionError,KeyError,ValueError,TypeError):return False
cases=json.loads(path.read_text())
for case in cases:assert valid(case['event'])==case['valid'],case['name']
print(f'{len(cases)} shared contract vectors passed')
