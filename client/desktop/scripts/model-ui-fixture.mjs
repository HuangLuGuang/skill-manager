// Isolated UI fixture: no Tauri commands, credentials, Agent calls or API writes.
// Run with Node, then open http://127.0.0.1:18420/?locale=en-US&outcome=failed.
import http from 'node:http'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
const source = fileURLToPath(new URL('../src/', import.meta.url))
const contract = JSON.parse(await readFile(new URL('../../../agent_manager/core/model_switch_contract.json', import.meta.url), 'utf8'))
const bootstrap = `
(() => {
localStorage.setItem('agent-manager-client-locale', new URLSearchParams(location.search).get('locale') || 'zh-CN');
const specs = ${JSON.stringify(contract.agents)};
const agents = Object.entries(specs).map(([kind, spec]) => ({ agent_type: kind, local_agent_id: kind, display_name: spec.label, version: 'UI fixture', skills: [], capabilities: {installed: true, model_config_auto_apply: true, model_config_verification: spec.verification === 'isolated_cli', model_config_contract: spec, model_config_state: { supported:true, model:'model-a', config_path:'~/'+spec.files[0], gateway_url:'http://127.0.0.1:8001/v1', parameters: {}, revision:'a'.repeat(64), change_id:'fixture-change', status:'pending_restart', can_restore:true }}}));
const inventory = {client_id:'ui-fixture',hostname:'UI fixture',os:'darwin',arch:'arm64',agents};
for (const agent of agents) {
 const spec=agent.capabilities.model_config_contract;
 agent.version=spec.parameter_versions?.[0] || 'UI fixture';
 if(new URLSearchParams(location.search).get('version')==='unverified' && spec.parameter_versions?.length){
  agent.version='unverified'; agent.capabilities.model_config_contract={...spec,parameters:{},parameter_status:'version_unverified'};
 }
}
const connection = {configured:true, connected:true, service_running:true, service_installed:true, name:'UI fixture — simulated responses', inventory, local:{notifications:[],tasks:[],sync:{inventory:{last_success_at:new Date().toISOString()}}}, platform:{name:'UI fixture — simulated responses',agents:[],policy_mode:'audit',model_configuration:{can_configure_models:true,models:[{name:'model-a',display_name:'Model A',provider_name:'Test provider',max_output_tokens:8192},{name:'model-b',display_name:'Model B',provider_name:'Test provider',max_output_tokens:8192}]}}};
window.__TAURI__={core:{invoke:async (name, input={}) => {
 if(name==='get_build_version') return 'UI fixture';
 if(name==='get_connection_status') return structuredClone(connection);
 if(name==='get_client_history') return {items:[],total:0};
 if(name==='execute_client') {
  const args=input.args||[]; const selected=agents.find(agent=>agent.agent_type===args[args.indexOf('--agent-type')+1]) || agents[0];
  if(['switch-model','verify-model','restore-model'].includes(input.command)) {
   await new Promise(resolve=>setTimeout(resolve,1200));
   if(new URLSearchParams(location.search).get('outcome')==='failed') throw new Error('model_config.conflict');
   const state=selected.capabilities.model_config_state;
   if(input.command==='switch-model'){state.model=args[args.indexOf('--model')+1];state.parameters=JSON.parse(args[args.indexOf('--model-parameters')+1]||'{}');state.status='pending_restart'}
   else {state.status=input.command==='verify-model'?'verified':'restored';state.verification=input.command==='verify-model'?[{request_id:'fixture_request_simulated',model:state.model,status:'success',parameters:{stream:true}}]:[];}
   return JSON.stringify(state);
  }
  if(['agent-settings','pending','backups','scan-history','refresh-scan-history'].includes(input.command)) return '[]';
  if(input.command==='inventory'||input.command==='cached-inventory') return JSON.stringify(inventory);
  if(input.command==='local-status') return JSON.stringify(connection.local);
  return '{}';
 }
 return {};
}}};
})();
`
const types = {'.js':'text/javascript','.css':'text/css','.html':'text/html','.svg':'image/svg+xml','.png':'image/png'}
http.createServer(async (req,res)=>{
 try {
  const url=new URL(req.url,'http://localhost');
  if(url.pathname==='/__fixture.js'){res.setHeader('Content-Type','text/javascript');res.end(bootstrap);return}
  const relative=url.pathname==='/'?'index.html':decodeURIComponent(url.pathname.slice(1));
  const target=path.resolve(source,relative);
  if(!target.startsWith(source)){res.writeHead(403);res.end();return}
  let body=await readFile(target);
  if(relative==='index.html')body=body.toString().replace('<head>','<head><script src="/__fixture.js"></script>');
  res.setHeader('Content-Type',types[path.extname(target)]||'application/octet-stream');res.end(body);
 }catch{res.writeHead(404);res.end()}
}).listen(18420,'127.0.0.1',()=>console.log('UI fixture: http://127.0.0.1:18420 (simulated; no Agent calls)'))
