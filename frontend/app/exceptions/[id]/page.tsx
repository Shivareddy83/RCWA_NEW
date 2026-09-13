'use client';
import {useEffect,useState} from 'react';
import {useParams,useRouter} from 'next/navigation';
import {api} from '../../../lib/api';
import {money,dateTime} from '../../../lib/format';
import {Badge,Button,ErrorState,Loading,PageTitle,Table} from '../../../components/ui';

export default function ExceptionDetail(){
  const {id}=useParams<{id:string}>(); const router=useRouter();
  const [x,setX]=useState<any>(); const [rca,setRca]=useState<any>(); const [ev,setEv]=useState<any>();
  const [caseInfo,setCaseInfo]=useState<any>(); const [error,setError]=useState(''); const [busy,setBusy]=useState(false);
  const load=()=>Promise.all([
    api<any>(`/exceptions/${id}`),api<any>(`/exceptions/${id}/rca`).catch(()=>null),api<any>(`/exceptions/${id}/evidence`).catch(()=>({items:[]}))
  ]).then(([a,b,c])=>{setX(a);setRca(b);setEv(c);if(a.reconciliation_case_id)return api<any>(`/cases/${a.reconciliation_case_id}`).then(setCaseInfo).catch(()=>null)}).catch(v=>setError(v.message));
  useEffect(()=>{void load()},[id]);
  async function act(path:string,body?:any){setBusy(true);setError('');try{const result=await api<any>(path,{method:'POST',body:body?JSON.stringify(body):undefined});if(result?.id&&path.includes('/cases'))setCaseInfo(result);await load()}catch(e:any){setError(e.message)}finally{setBusy(false)}}
  if(error&&!x)return <ErrorState message={error} onRetry={load}/>; if(!x)return <Loading/>;
  return <>
    <PageTitle title="Exception detail" description="A deterministic discrepancy that can be acknowledged, investigated and resolved." actions={<div style={{display:'flex',gap:7,flexWrap:'wrap'}}>
      {x.status==='OPEN'&&<Button disabled={busy} onClick={()=>act(`/exceptions/${id}/acknowledge`)}>Acknowledge</Button>}
      {!caseInfo&&<Button disabled={busy} onClick={()=>act('/cases',{exception_id:id})}>Open investigation</Button>}
      {caseInfo&&<Button disabled={busy} onClick={()=>router.push(`/cases/${caseInfo.id}`)}>Open case</Button>}
      {x.status!=='RESOLVED'&&<Button disabled={busy||!caseInfo} onClick={()=>caseInfo&&router.push(`/cases/${caseInfo.id}`)}>Resolve from case</Button>}
    </div>}/>
    {error&&<div className="error panel" style={{marginBottom:14}}>{error}</div>}
    <div className="cards"><section className="panel"><h3>Problem</h3><p>{x.description||x.message||x.exception_code}</p><Table><tbody>{[['Exception ID',x.id],['Code',x.exception_code],['Severity',<Badge value={x.severity}/>],['Status',<Badge value={x.status}/>],['Expected',money(x.expected_amount,x.currency)],['Actual',money(x.actual_amount,x.currency)],['Difference',money(x.difference,x.currency)],['Detected',dateTime(x.created_at)]].map(([k,v])=><tr key={String(k)}><th>{k}</th><td>{v as any}</td></tr>)}</tbody></Table></section><section className="panel"><h3>Investigation status</h3>{caseInfo?<><p><b>{caseInfo.case_number}</b></p><p className="muted">{caseInfo.status} · {caseInfo.priority} · {caseInfo.assigned_to||'Unassigned'}</p><p>{caseInfo.summary||caseInfo.description}</p></>:<p className="muted">No investigation case is attached yet.</p>}<h3 style={{marginTop:24}}>Deterministic RCA</h3>{rca?<><p><b>{rca.root_cause_code}</b></p><p className="muted">Confidence: {rca.confidence}</p><p>{rca.explanation}</p><div className="notice">Recommended action: {rca.recommended_action||'—'}</div></>:<p className="muted">RCA is not available for this exception.</p>}</section></div>
    <section className="panel" style={{marginTop:14}}><h3>Evidence</h3>{ev?.items?.length?ev.items.map((a:any)=><details key={a.id} style={{marginTop:10}}><summary>{a.evidence_type||a.type||'Evidence'} · {dateTime(a.captured_at)}</summary><p className="muted">{a.relevance||a.description||'Stored evidence snapshot.'}</p><pre style={{whiteSpace:'pre-wrap',fontSize:11}}>{JSON.stringify(a.snapshot_json||a.snapshot||a,null,2)}</pre></details>):<p className="muted">No evidence returned by the backend.</p>}</section>
  </>;
}
