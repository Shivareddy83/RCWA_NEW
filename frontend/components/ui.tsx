'use client';
import Link from 'next/link';
import {usePathname, useRouter} from 'next/navigation';
import {useAuth} from '../lib/auth';
import {useEffect, useState} from 'react';

export function Badge({value}:{value:unknown}){const v=String(value??'—'); return <span className="badge">{v.replaceAll('_',' ')}</span>}
export function Loading(){return <div className="panel skeleton">Loading data…</div>}
export function ErrorState({message,onRetry}:{message:string;onRetry?:()=>void}){return <div className="panel error"><b>Unable to load this view</b><p>{message}</p>{onRetry&&<button className="btn secondary" onClick={onRetry}>Try again</button>}</div>}
export function Empty({label='No records found.'}){return <div className="panel empty"><div className="empty-icon">—</div><strong>{label}</strong><p>There is nothing to review here yet.</p></div>}

const nav=[
  {title:'Workspace',items:[['/','Dashboard'],['/health','Health'],['/activation','Activation']]},
  {title:'Reconciliation',items:[['/reconciliation','Reconciliation'],['/ingestion','Data ingestion'],['/connectors','Data connectors'],['/payments','Payments'],['/refunds','Refunds'],['/settlements','Settlements']]},
  {title:'Investigations',items:[['/exceptions','Exceptions'],['/cases','Cases'],['/reports','Reports']]},
  {title:'Operations',items:[['/notifications','Notifications'],['/jobs','Jobs'],['/audit','Audit'],['/billing','Billing']]},
];
const adminNav=[['/users','Users'],['/sso','Enterprise SSO'],['/leads','Demo leads'],['/customers','Customers']];
const allPaths=[...nav.flatMap(g=>g.items),...adminNav];

export function Shell({children}:{children:React.ReactNode}){
  const path=usePathname();
  const router=useRouter();
  const {user,loading,logout}=useAuth();
  const [mobileOpen,setMobileOpen]=useState(false);
  const isPublicRoute=path==='/'||path==='/signup'||path==='/demo'||path==='/marketing'||path==='/login'||path==='/register'||path==='/forgot-password'||path==='/reset-password';
  useEffect(()=>{if(!loading && !user && !isPublicRoute) router.replace('/login')},[loading,user,isPublicRoute,router]);
  useEffect(()=>{setMobileOpen(false)},[path]);
  if(loading)return <main className="center"><Loading/></main>;
  if(!user)return isPublicRoute?<>{children}</>:<main className="center"><Loading/></main>;
  const pageTitle=allPaths.find(([href])=>path===href)?.[1]||'Investigation workspace';
  return <div className="app">
    <button className="mobile-menu-btn" aria-label="Open navigation" onClick={()=>setMobileOpen(v=>!v)}>☰</button>
    {mobileOpen&&<div className="mobile-overlay" onClick={()=>setMobileOpen(false)}/>} 
    <aside className={mobileOpen?'sidebar open':'sidebar'}>
      <div className="brand"><div className="brandmark">R</div><div><b>RCAA</b><small>Finance operations</small></div></div>
      <div className="workspace-chip"><span className="status-dot"/> Live workspace <span>⌄</span></div>
      <nav>
        {nav.map(group=><div className="nav-group" key={group.title}><div className="nav-label">{group.title}</div>{group.items.map(([href,label])=><Link className={path===href||path.startsWith(href+'/')?'active':''} key={href} href={href}>{label}</Link>)}</div>)}
        {user.role==='ADMIN'&&<div className="nav-group"><div className="nav-label">Administration</div>{adminNav.map(([href,label])=><Link className={path===href||path.startsWith(href+'/')?'active':''} key={href} href={href}>{label}</Link>)}</div>}
      </nav>
      <div className="side-note"><div className="trust-mark">✓</div><div><b>Financial truth is deterministic</b><span>AI is advisory only</span></div></div>
    </aside>
    <div className="content">
      <header>
        <div className="header-title"><span className="eyebrow">RCAA / {user.merchant_id}</span><h1>{pageTitle}</h1></div>
        <div className="user"><div className="avatar">{user.email.slice(0,1).toUpperCase()}</div><span>{user.email}<small>{user.role} · secure session</small></span><button className="btn ghost" onClick={logout}>Log out</button></div>
      </header>
      <main>{children}</main>
    </div>
  </div>
}
export function PageTitle({title,description,actions}:{title:string;description?:string;actions?:React.ReactNode}){return <div className="page-title"><div><span className="section-kicker">Operations</span><h2>{title}</h2>{description&&<p>{description}</p>}</div>{actions}</div>}
export function Stat({label,value,detail}:{label:string;value:React.ReactNode;detail?:string}){return <div className="stat"><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</div>}
export function Table({children}:{children:React.ReactNode}){return <div className="table-wrap"><table>{children}</table></div>}
export function Button({children,...props}:React.ButtonHTMLAttributes<HTMLButtonElement>){return <button className="btn primary" {...props}>{children}</button>}
