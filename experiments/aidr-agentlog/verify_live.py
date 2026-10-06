"""Read-only acceptance; evidence contains summaries and digests, never tool content."""
import collections,hashlib,json,pathlib,subprocess,time
ROOT=pathlib.Path(__file__).resolve().parents[2]
BASE=pathlib.Path(__file__).parent/'evidence'
BINARY=BASE/'agent-manager-client'
results=[]
for agent in ['claude','codex']:
 path=pathlib.Path((BASE/(agent+'-source-path.txt')).read_text())
 args=[str(BINARY),'agent-log-read','--agent',agent,'--root',str(path.parent),'--file',str(path),'--since','1970-01-01T00:00:00Z','--max-bytes',str(64<<20),'--max-events','4096','--timeout','30s']
 started=time.monotonic();run=subprocess.run(args,capture_output=True,check=True);batch=json.loads(run.stdout)
 offset=int(batch['cursor']['offset'])
 with path.open('rb') as f: prefix=f.read(offset)
 expected=collections.Counter()
 for line in prefix.splitlines():
  row=json.loads(line)
  if agent=='claude':
   msg=row.get('message') or {};content=msg.get('content') if isinstance(msg,dict) else None
   for block in content if isinstance(content,list) else []:
    if not isinstance(block,dict):continue
    if block.get('type')=='tool_use':expected[(block['id'],'tool_call')]+=1
    elif block.get('type')=='tool_result':expected[(block['tool_use_id'],'tool_result')]+=1
  elif row.get('type')=='response_item':
   item=row.get('payload') or {};typ=item.get('type')
   if typ in ['function_call','custom_tool_call']:expected[(item['call_id'],'tool_call')]+=1
   elif typ in ['function_call_output','custom_tool_call_output']:expected[(item['call_id'],'tool_result')]+=1
 actual=collections.Counter((e['native_call_id'],e['kind']) for e in batch['events'])
 # Output JSON deliberately excludes source bodies and private log paths.
 summary={'agent':agent,'version':batch['cursor']['agent_version'],'duration_ms':round((time.monotonic()-started)*1000,2),'source_digest':hashlib.sha256(str(path).encode()).hexdigest(),'offset':offset,'events':len(batch['events']),'kinds':dict(collections.Counter(e['kind'] for e in batch['events'])),'coverage':batch['coverage'],'independent_prefix_match':expected==actual,'process_relations':sorted(set(e['process_relation'] for e in batch['events'])),'event_ids_unique':len({e['event_id'] for e in batch['events']})==len(batch['events'])}
 assert summary['independent_prefix_match'],summary
 assert batch['events'],summary
 checkpoint=BASE/(agent+'-cursor.json');checkpoint.write_text(json.dumps(batch['cursor']));checkpoint.chmod(0o600)
 resumed=json.loads(subprocess.check_output(args+['--cursor',str(checkpoint)]))
 summary['resume_old_event_ids_repeated']=len({e['event_id'] for e in batch['events']} & {e['event_id'] for e in resumed['events']})
 assert summary['resume_old_event_ids_repeated']==0
 results.append(summary)
(BASE/'live-results.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
