'use strict';
// Local diagnostic only. Import sanitization helpers; use actual caller defaults.
const {performance}=require('node:perf_hooks');
const path=require('node:path');
const {safeEvent,category,digest}=require('./benchmarkCollectorCaller.cjs');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const copy=v=>JSON.parse(JSON.stringify(v));
function normalized(v){
  if(Array.isArray(v))return v.map(normalized);
  if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).filter(([k])=>!['catalog_revision','expected_revision'].includes(k)).map(([k,x])=>[k,normalized(x)]));
  return v;
}
async function run(input,emit){
  const {createCollectorClient}=require(path.resolve(input.clientPath));
  const sessions=input.workload.sessions,plan=input.scenarios.plan;
  if(!Array.isArray(sessions)||sessions.length!==16||new Set(sessions.map(s=>digest(s.payload))).size!==16
    ||sessions.some((s,i)=>s.index!==i||!s.payload||!Array.isArray(s.payload.turns)||s.payload.turns.length!==20
      ||s.payload.turns[0]?.type!=='ask'||s.payload_sha256!==digest(s.payload)
      ||!/^[a-f0-9]{64}$/.test(s.expected_result_semantic_sha256||''))
    ||!/^[a-f0-9]{64}$/.test(input.workload.catalog_revision||''))throw Error('distinct_sessions_required');
  validatePlan(plan,sessions.length);
  let requestNumber=0,currentCase;let native=true;
  emit({event:'run_started',planned_requests:plan.reduce((n,c)=>n+c.indices.length,0),client_mode:'current_required',node_version:process.version});
  async function call(index,cancel=false){
    const item=sessions[index],payload=copy(item.payload);
    const session={schema:'pokemon.pivota-collector-session.v1',turns:payload.turns.slice(0,-1),limit:payload.limit,expected_revision:input.workload.catalog_revision};
    const action=payload.turns.at(-1),original=digest({session,action}),requestId=++requestNumber;
    const attempts=[],fetchAttempts=[];
    emit({event:'request_started',request_id:requestId,case_id:currentCase,workload_sha256:digest(payload),cancellation_requested:cancel});
    const client=createCollectorClient({baseUrl:input.baseUrl,allowLoopback:true,
      fetchImpl:async(url,options)=>{
        const row={attempt:fetchAttempts.length+1,http_status:null,runtime_error:null};fetchAttempts.push(row);
        emit({event:'fetch_attempt',request_id:requestId,attempt:{...row}});
        const response=await globalThis.fetch(url,options);row.http_status=response.status;
        const runtime=response.headers.get('x-collector-error');
        if(['catalog_busy','catalog_snapshot_changed','catalog_work_budget_exceeded'].includes(runtime))row.runtime_error=runtime;
        emit({event:'fetch_attempt',request_id:requestId,attempt:{...row}});
        return response;
      },onAttempt:event=>{const safe=safeEvent(event);if(safe){attempts.push(safe);emit({event:'attempt_completed',request_id:requestId,attempt:safe});}}});
    const controller=cancel?new AbortController():null;
    const timer=cancel?setTimeout(()=>controller.abort(),10):null;const start=performance.now();
    const row={request_id:requestId,cancellation_requested:cancel,workload_sha256:digest(payload),category:null,elapsed_ms:null,error_code:null,attempts,fetch_attempts:fetchAttempts};
    try{
      const output=await client.advance({session,action,signal:controller?.signal});
      row.status=output.status;row.category=category(null,output.status);
      if(output.status==='accepted'){
        const result=output.result;row.semantic_sha256=digest(normalized(result));
        row.deterministic_match=row.semantic_sha256===item.expected_result_semantic_sha256;
        row.catalog_revision=result.catalog_revision;row.turn_count=result.turn_count;
        const coverage=result.discovery?.coverage||{};
        row.exercised_pool_records=coverage.scoped_catalog_records??coverage.matched_catalog_records??0;
        row.session_integrity=digest(output.session.turns)===digest(payload.turns)&&output.session.expected_revision===input.workload.catalog_revision;
        row.gates_closed=['conversation_persisted','inventory_persisted','ownership_assertions_verified','physical_copy_verified','ready_for_offer_tracking','purchase_ready','complete_collection_established','public_display_allowed','preferences_applied_to_market'].every(k=>result[k]===false)&&result.prices.length===0&&result.live_offers.length===0;
      }
    }catch(error){
      const safe=safeEvent({schema:'pokemon.collector-attempt.v1',error_class:error.code});
      row.error_code=safe?.error_class||'unclassified_caller_error';row.category=category(row.error_code,null);
    }finally{if(timer)clearTimeout(timer);row.elapsed_ms=Math.round((performance.now()-start)*1000)/1000;row.input_unchanged=digest({session,action})===original;}
    native=native&&attempts.length>0;emit({event:'request_completed',row});return row;
  }
  for(let i=0;i<plan.length;i++){
    const c=plan[i];if(c.delay_ms)await sleep(c.delay_ms);
    currentCase=i+1;emit({event:'case_started',case:{case_id:currentCase,phase:c.phase,clients:c.clients,scheduled_requests:c.indices.length,...(c.label?{label:c.label}:{}),...(c.after?{after:c.after}:{}),...(c.delay_ms?{idle_delay_ms:c.delay_ms}:{})}});
    const start=performance.now();
    if(c.sustained){
      // Lane ownership guarantees no concurrent duplicate payloads even when
      // rejected lanes run ahead of the expensive admitted lane.
      await Promise.all(Array.from({length:c.clients},(_,lane)=>(async()=>{
        for(let j=lane;j<c.indices.length;j+=c.clients)await call(c.indices[j]);
      })()));
    }else await Promise.all(c.indices.map(index=>call(index,c.cancel)));
    emit({event:'case_completed',case_id:currentCase,wall_ms:Math.round((performance.now()-start)*1000)/1000});
  }
  emit({event:'run_completed',node_version:process.version,client_mode:'current_required',native_attempt_diagnostics:native,cancellation_support:'required_and_exercised'});
}
if(require.main===module)(async()=>{
  let raw='';for await(const chunk of process.stdin){raw+=chunk;if(raw.length>1024*1024)throw Error('input_too_large');}
  await run(JSON.parse(raw),e=>process.stdout.write(JSON.stringify({schema:'pokemon.collector-journal.v1',...e})+'\n'));
})().catch(()=>{process.stderr.write('mixed_caller_benchmark_failed\n');process.exitCode=1;});
function validatePlan(plan,count=16){
  const phases=new Set(['serial_first_use','serial_warm','serial_control_b','simultaneous_burst',
    'immediate_recovery','post_burst_recovery','sustained','cross_session_integrity',
    'cross_session_recovery','external_cancellation','post_cancel_deadline_recovery']);
  const fields=new Set(['phase','clients','indices','label','after','delay_ms','sustained','cancel']);
  const label=v=>typeof v==='string'&&(['sustained','external_cancellation'].includes(v)||/^burst_([1-9]|1[0-6])$/.test(v));
  if(!Number.isInteger(count)||count<1||count>16||!Array.isArray(plan)||plan.length<1||plan.length>64)throw Error('invalid_mixed_plan');
  let total=0;
  for(const c of plan){
    const delay=c&&typeof c==='object'&&Object.prototype.hasOwnProperty.call(c,'delay_ms')?c.delay_ms:0;
    if(!c||typeof c!=='object'||Array.isArray(c)||Object.keys(c).some(k=>!fields.has(k))
      ||!phases.has(c.phase)||!Number.isInteger(c.clients)||c.clients<1||c.clients>16
      ||!Array.isArray(c.indices)||!c.indices.length||c.indices.some(i=>!Number.isInteger(i)||i<0||i>=count)
      ||['sustained','cancel'].some(k=>k in c&&typeof c[k]!=='boolean')
      ||['label','after'].some(k=>k in c&&!label(c[k]))
      ||!Number.isInteger(delay)||delay<0||delay>8500)throw Error('invalid_mixed_case');
    total+=c.indices.length;if(total>128)throw Error('mixed_request_bound');
    if(c.sustained){
      if(c.clients>c.indices.length||c.cancel)throw Error('invalid_mixed_sustained');
      const owners=new Map();
      for(let j=0;j<c.indices.length;j++){
        const id=c.indices[j],lane=j%c.clients;
        if(owners.has(id)&&owners.get(id)!==lane)throw Error('mixed_concurrent_duplicate');
        owners.set(id,lane);
      }
    }else if(c.indices.length!==c.clients||new Set(c.indices).size!==c.indices.length)throw Error('mixed_concurrent_duplicate');
    if(c.cancel&&(c.clients!==1||c.phase!=='external_cancellation'))throw Error('invalid_mixed_cancel');
  }
  return plan;
}
module.exports={normalized,validatePlan,run};
