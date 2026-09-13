'use client';
import {useEffect,useState} from 'react';
import {useParams} from 'next/navigation';
import {api} from '../../../lib/api';
import {money,dateTime} from '../../../lib/format';
import {Badge,Button,ErrorState,Loading,PageTitle,Table} from '../../../components/ui';
import {useAuth} from '../../../lib/auth';

const RESOLUTION_CODES=[
  ['SETTLEMENT_POSTED','Settlement posted'],
  ['REFUND_PROCESSED','Refund processed'],
  ['DUPLICATE_CONFIRMED','Duplicate confirmed'],
  ['BANK_CORRECTION_REQUIRED','Bank correction required'],
  ['PROVIDER_INVESTIGATION_REQUIRED','Provider investigation required'],
  ['FALSE_POSITIVE','False positive'],
  ['OTHER','Other'],
];

export default function CaseWorkspace(){
  const {id}=useParams<{id:string}>(); const {user}=useAuth();
  const [c,setC]=useState<any>(); const [ai,setAi]=useState<any>();
  const [q,setQ]=useState('Why does this case require investigation?');
  const [note,setNote]=useState(''); const [assignee,setAssignee]=useState('');
  const [resolutionCode,setResolutionCode]=useState(''); const [resolutionNote,setResolutionNote]=useState('');
  const [busy,setBusy]=useState(false); const [error,setError]=useState(''); const [message,setMessage]=useState('');
  const [recoveryAction,setRecoveryAction]=useState('PROVIDER_TICKET'); const [recoveryRef,setRecoveryRef]=useState(''); const [recoveryNote,setRecoveryNote]=useState(''); const [verifyBankId,setVerifyBankId]=useState(''); const [verifyNote,setVerifyNote]=useState('');
  const load=()=>api<any>(`/cases/${id}`).then(v=>{setC(v);setAssignee(v.assigned_to||'');setResolutionCode(v.resolution_code||'')}).catch(e=>setError(e.message));
  useEffect(()=>{void load()},[id]);
  if(error)return <ErrorState message={error} onRetry={load}/>; if(!c)return <Loading/>;
  async function act(path:string,body?:any){setBusy(true);setError('');setMessage('');try{await api(path,{method:'POST',body:body?JSON.stringify(body):undefined});setMessage('Saved.');await load()}catch(e:any){setError(e.message)}finally{setBusy(false)}}
  async function investigate(){setBusy(true);setError('');setMessage('');try{setAi(await api(`/cases/${id}/ai/investigate`,{method:'POST',body:JSON.stringify({question:q})}))}catch(e:any){setError(e.message)}finally{setBusy(false)}}
  const rca=c.rca; const status=c.status; const canOperate=!!user?.role&&['ADMIN','OPS'].includes(user.role); const canStart=canOperate&&(status==='OPEN'||status==='REOPENED'); const canResolve=canOperate&&status!=='RESOLVED';
  return <>
    <PageTitle title={c.case_number||'Case investigation'} description="Evidence-backed workflow for investigating and resolving a reconciliation exception." actions={<div style={{display:'flex',gap:7,flexWrap:'wrap'}}>
      {canStart&&<Button disabled={busy} onClick={()=>act(`/cases/${id}/start`)}>Start investigation</Button>}
      {canResolve&&<Button disabled={busy||!resolutionCode} onClick={()=>act(`/cases/${id}/resolve`,{resolution_code:resolutionCode,resolution_note:resolutionNote||undefined})}>Resolve case</Button>}
      {status==='RESOLVED'&&<Button disabled={busy} onClick={()=>act(`/cases/${id}/reopen`)}>Reopen</Button>}
    </div>}/>
    {message&&<div className="notice" style={{marginBottom:14}}>{message}</div>}
    <section className="panel" style={{marginBottom:14}}><div style={{display:'flex',gap:9,alignItems:'center',flexWrap:'wrap'}}><Badge value={c.priority}/><Badge value={c.status}/><span className="muted">Assignee: {c.assigned_to||'Unassigned'}</span>{c.resolution_code&&<span className="muted">Resolution: {c.resolution_code}</span>}</div><h3 style={{marginTop:14}}>{c.title||c.case_type}</h3><p className="muted">{c.description||c.summary||'No case description.'}</p></section>
    <div className="grid two">
      <section className="panel"><h3>Financial summary</h3><div className="financial">{[['Payment',c.payment_amount],['Refund',c.refund_amount],['Settlement',c.actual_amount],['Expected',c.expected_amount],['Actual',c.actual_amount],['Difference',c.difference]].map(([k,v])=><div className="metric" key={String(k)}><span>{k}</span><b>{v==null?'—':money(v,c.currency||'INR')}</b></div>)}</div><h3 style={{marginTop:24}}>Problem / exception</h3><p>{c.description||c.summary||'Backend did not provide additional description.'}</p></section>
      <section className="panel"><h3>Deterministic RCA</h3>{rca?<><p><b>{rca.root_cause_code||rca.root_cause}</b></p><p className="muted">Confidence: {rca.confidence||rca.confidence_label}</p><p>{rca.explanation}</p><div className="notice">Recommended action: {rca.recommended_action||'—'}</div></>:<p className="muted">RCA not available.</p>}
      <h3 style={{marginTop:24}}>Resolution</h3><label className="field">Resolution code<select value={resolutionCode} onChange={e=>setResolutionCode(e.target.value)}><option value="">Select a reason</option>{RESOLUTION_CODES.map(([v,l])=><option value={v} key={v}>{l}</option>)}</select></label><label className="field">Resolution note<textarea rows={3} maxLength={5000} value={resolutionNote} onChange={e=>setResolutionNote(e.target.value)} placeholder="Record what was verified or corrected."/></label></section>
    </div>
    <section className="panel" style={{marginTop:14}}><h3>Closed-loop financial recovery</h3>
      <div className="notice"><b>An exception is not resolved until RCWA can establish what happened to the money and verify the financial outcome.</b> Recovery actions are operational records only; RCWA never mutates provider, payment, settlement or bank financial truth.</div>
      <div className="financial">{[['Status',c.recovery?.status||'IDENTIFIED'],['Exposure',c.recovery?.exposure_amount!=null?money(c.recovery.exposure_amount,c.recovery.currency||c.currency||'INR'):'—'],['Recoverable',c.recovery?.recoverable_amount!=null?money(c.recovery.recoverable_amount,c.recovery.currency||c.currency||'INR'):'—'],['Recovered',c.recovery?.recovered_amount!=null?money(c.recovery.recovered_amount,c.recovery.currency||c.currency||'INR'):'—']].map(([k,v])=><div className="metric" key={String(k)}><span>{k}</span><b>{String(v)}</b></div>)}</div>
      {c.recovery?.status!=='VERIFIED'&&c.recovery?.status!=='NOT_REQUIRED'&&<div className="grid two" style={{marginTop:18}}>
        <div><h4>Initiate recovery</h4><label className="field">Action<select value={recoveryAction} onChange={e=>setRecoveryAction(e.target.value)}><option value="PROVIDER_TICKET">Provider ticket / investigation</option><option value="BANK_CORRECTION">Bank correction</option><option value="REFUND_CORRECTION">Refund correction</option><option value="INTERNAL_CORRECTION">Internal correction</option><option value="OTHER">Other</option></select></label><label className="field">External reference<input value={recoveryRef} onChange={e=>setRecoveryRef(e.target.value)} placeholder="Provider ticket / claim reference"/></label><label className="field">Action note<textarea rows={3} value={recoveryNote} onChange={e=>setRecoveryNote(e.target.value)} placeholder="What recovery action was initiated?"/></label><Button disabled={!canOperate||busy} onClick={()=>act(`/cases/${id}/recovery/initiate`,{action_type:recoveryAction,external_reference:recoveryRef||undefined,action_note:recoveryNote||undefined})}>Record recovery action</Button></div>
        <div><h4>Verify money received</h4><p className="muted">Select the bank transaction that proves the recoverable amount was actually received. Verification requires an exact amount match and, when supplied, the recovery reference.</p><label className="field">Bank transaction ID<input value={verifyBankId} onChange={e=>setVerifyBankId(e.target.value)} placeholder="Bank transaction ID"/></label><label className="field">Verification note<textarea rows={3} value={verifyNote} onChange={e=>setVerifyNote(e.target.value)} placeholder="Why this bank credit proves recovery."/></label><Button disabled={!canOperate||busy||!verifyBankId.trim()} onClick={()=>act(`/cases/${id}/recovery/verify`,{bank_transaction_id:verifyBankId.trim(),verification_note:verifyNote||undefined})}>Verify recovery</Button></div>
      </div>}
      {c.recovery?.status==='VERIFIED'&&<div className="notice" style={{marginTop:14}}>Recovery verified against bank transaction <b>{c.recovery.verified_bank_transaction_id}</b> for <b>{money(c.recovery.recovered_amount,c.recovery.currency||c.currency||'INR')}</b>. The financial outcome is now evidenced.</div>}
    </section>
    <section className="panel" style={{marginTop:14}}><h3>Case ownership</h3><div className="grid two"><label className="field">Assignee<input value={assignee} onChange={e=>setAssignee(e.target.value)} placeholder="analyst@example.com"/></label><div style={{display:'flex',alignItems:'end',paddingBottom:16}}><Button disabled={!canOperate||busy||!assignee.trim()} onClick={()=>act(`/cases/${id}/assign`,{assigned_to:assignee.trim()})}>Assign case</Button></div></div><label className="field">Investigation note<textarea rows={3} maxLength={10000} value={note} onChange={e=>setNote(e.target.value)} placeholder="Add a factual investigation note."/></label><Button disabled={!canOperate||busy||!note.trim()} onClick={async()=>{await act(`/cases/${id}/notes`,{note:note.trim()});setNote('')}}>Add note</Button></section>
    <section className="panel" style={{marginTop:14}}><h3>Evidence</h3>{c.evidence?.length?c.evidence.map((e:any)=><details key={e.id} style={{marginTop:10}}><summary>{e.evidence_type||e.type||'Evidence'} · {e.source_entity_type||'source'} · {dateTime(e.captured_at)}</summary><p className="muted">{e.relevance||e.description||'Stored evidence snapshot.'}</p><pre style={{whiteSpace:'pre-wrap',fontSize:11}}>{JSON.stringify(e.snapshot_json||e.snapshot||e,null,2)}</pre></details>):<p className="muted">No evidence returned.</p>}</section>
    <section className="panel" style={{marginTop:14}}><h3>AI-assisted investigation</h3><div className="notice">AI is assistive and read-only. Financial truth comes from deterministic reconciliation and stored evidence.</div><label className="field">Investigation question<textarea rows={3} maxLength={2000} value={q} onChange={e=>setQ(e.target.value)}/></label><Button disabled={busy||!q.trim()} onClick={investigate}>{busy?'Working…':'Ask investigation'}</Button>{ai&&<div style={{marginTop:18}}><h4>Facts</h4><p>{ai.ai_investigation?.summary||ai.answer}</p><h4>Deterministic findings</h4><ul>{(ai.ai_investigation?.deterministic_findings||[]).map((x:string)=><li key={x}>{x}</li>)}</ul><h4>Hypotheses</h4><ul>{(ai.ai_investigation?.hypotheses||[]).map((x:any,i:number)=><li key={i}>{typeof x==='string'?x:JSON.stringify(x)}</li>)}</ul><h4>Recommendations</h4><ul>{(ai.ai_investigation?.recommended_actions||[]).map((x:string)=><li key={x}>{x}</li>)}</ul><h4>Evidence references</h4><p className="muted">{JSON.stringify(ai.ai_investigation?.evidence_references||[])}</p><h4>Uncertainty</h4><p className="muted">{JSON.stringify(ai.ai_investigation?.uncertainty||"Not provided")}</p><p className="muted">{ai.disclaimer}</p></div>}</section>
    <section className="panel" style={{marginTop:14}}><h3>Case timeline</h3><div className="timeline">{(c.timeline||[]).map((e:any)=><div key={e.id}><b>{e.event_type||e.type||'Event'}</b><div className="muted">{dateTime(e.created_at)}</div>{e.metadata_json&&<div className="muted">{JSON.stringify(e.metadata_json)}</div>}</div>)}{!(c.timeline||[]).length&&<p className="muted">No timeline events returned.</p>}</div></section>
  </>;
}
