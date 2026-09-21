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
const params = new URLSearchParams(location.search);
localStorage.setItem('agent-manager-client-locale', params.get('locale') || 'zh-CN');
const externalGatewayEnabled = params.get('gateway') === 'external';
const gatewayName = params.get('locale') === 'en-US' ? 'Enterprise AI Gateway' : '客户 AI 网关';
const specs = ${JSON.stringify(contract.agents)};
const agents = Object.entries(specs).map(([kind, spec]) => ({ agent_type: kind, local_agent_id: kind, display_name: spec.label, version: 'UI fixture', skills: [], capabilities: {installed: true, model_config_auto_apply: true, model_config_verification: spec.verification === 'isolated_cli', model_config_contract: spec, model_config_state: { supported:true, model:'model-a', config_path:'~/'+spec.files[0], gateway_url:'http://127.0.0.1:8001/v1', parameters: {}, revision:'a'.repeat(64), change_id:'fixture-change', status:'pending_restart', can_restore:true }}}));
const inventory = {client_id:'ui-fixture',hostname:'UI fixture',os:'darwin',arch:'arm64',agents};
const savedConnections = [
 {server:'https://manager-primary.example.com',name:'Primary Governance Platform',active:true},
 {server:'https://manager-disaster-recovery.example.com:8443',name:'Disaster Recovery Environment With a Long Name',active:false},
];
for (const agent of agents) {
 const spec=agent.capabilities.model_config_contract;
 agent.version=spec.parameter_versions?.[0] || 'UI fixture';
 if(params.get('version')==='unverified' && spec.parameter_versions?.length){
  agent.version='unverified'; agent.capabilities.model_config_contract={...spec,parameters:{},parameter_status:'version_unverified'};
 }
}
const modelConfiguration = {can_configure_models:true,models:[{name:'model-a',display_name:'Model A',provider_name:'Test provider',max_output_tokens:8192},{name:'model-b',display_name:'Model B',provider_name:'Test provider',max_output_tokens:8192}],model_routing:{external_gateway_enabled:externalGatewayEnabled,external_gateway_id:7,client_select_model:true},external_gateway:externalGatewayEnabled?{id:7,name:gatewayName,model_base_url:'http://gateway.example.test:8080'}:null,external_catalogs:[]};
const connection = {configured:true, connected:true, server:savedConnections[0].server, service_running:true, service_installed:true, name:savedConnections[0].name, inventory, local:{notifications:[],tasks:[],sync:{inventory:{last_success_at:new Date().toISOString()}}}, platform:{client_id:'ui-fixture',name:'UI fixture — simulated responses',agents:[],policy_mode:'audit',classification:{version:'7:0'},model_configuration:modelConfiguration}};
if(externalGatewayEnabled && params.get('prepared')==='all'){
 connection.platform.agents=agents.map(agent=>({local_agent_id:agent.local_agent_id,agent_type:agent.agent_type,managed_agent_id:'managed-'+agent.local_agent_id}));
 modelConfiguration.external_catalogs=connection.platform.agents.map(agent=>({gateway_id:7,gateway_name:gatewayName,managed_agent_id:agent.managed_agent_id,external_agent_id:'agent-'+agent.local_agent_id,key_id:'key-'+agent.local_agent_id,status:'active',models:[{id:'external-model-a',name:'external-model-a',display_name:'External Model A'},{id:'external-model-b',name:'external-model-b',display_name:'External Model B'}],models_refreshed_at:new Date().toISOString()}));
 localStorage.setItem('agent-manager-client-settings-v1',JSON.stringify({defaultPanel:'models'}));
 localStorage.setItem('agent-manager-external-gateway-policy-prompt-v1',JSON.stringify(['ui-fixture:7:0:7:http://gateway.example.test:8080']));
}
window.__TAURI__={core:{invoke:async (name, input={}) => {
 if(name==='get_build_version') return 'UI fixture';
 if(name==='get_connection_status') return structuredClone(connection);
 if(name==='get_local_snapshot') return structuredClone({local:connection.local,inventory});
 if(name==='refresh_model_catalog') {
  await new Promise(resolve=>setTimeout(resolve,500));
  const localAgent=agents.find(agent=>agent.local_agent_id===input.localAgentId) || agents[0];
  const managedAgentId='managed-'+localAgent.local_agent_id;
  const response={gateway:{id:7,name:gatewayName,model_base_url:'http://gateway.example.test:8080'},binding:{external_agent_id:'agent-'+localAgent.local_agent_id,key_id:'key-'+localAgent.local_agent_id,status:'active',models_refreshed_at:new Date().toISOString()},agent:{local_agent_id:localAgent.local_agent_id,agent_type:localAgent.agent_type,managed_agent_id:managedAgentId},models:[{id:'external-model-a',name:'external-model-a',display_name:'External Model A'},{id:'external-model-b',name:'external-model-b',display_name:'External Model B'}]};
  connection.platform.agents=[...connection.platform.agents.filter(agent=>agent.local_agent_id!==localAgent.local_agent_id),response.agent];
  connection.platform.model_configuration.external_catalogs=[...connection.platform.model_configuration.external_catalogs.filter(catalog=>catalog.managed_agent_id!==managedAgentId),{gateway_id:7,gateway_name:response.gateway.name,managed_agent_id:managedAgentId,external_agent_id:response.binding.external_agent_id,key_id:response.binding.key_id,status:'active',models:response.models,models_refreshed_at:response.binding.models_refreshed_at}];
  return response;
 }
 if(name==='get_client_history') return {items:[],total:0};
 if(name==='execute_client') {
  const args=input.args||[]; const selected=agents.find(agent=>agent.agent_type===args[args.indexOf('--agent-type')+1]) || agents[0];
  if(input.command==='connections') return JSON.stringify(savedConnections);
  if(input.command==='switch-connection') {
   const server=args[args.indexOf('--server')+1];
   const target=savedConnections.find(item=>item.server===server);
   savedConnections.forEach(item=>{item.active=item===target});
   if(target){connection.server=target.server;connection.name=target.name}
   return 'configuration saved';
  }
  if(['switch-model','verify-model','restore-model'].includes(input.command)) {
   await new Promise(resolve=>setTimeout(resolve,1200));
   if(params.get('outcome')==='failed') throw new Error('model_config.conflict');
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
