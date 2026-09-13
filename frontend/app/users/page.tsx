'use client';
import {FormEvent,useEffect,useState} from 'react';
import {api} from '../../lib/api';
import {canManageUsers} from '../../lib/permissions';
import {useAuth} from '../../lib/auth';
import type {Role,User} from '../../types';
import {Badge,Button,ErrorState,Loading,PageTitle,Table} from '../../components/ui';

const roles:Role[]=['ADMIN','OPS','ANALYST','VIEWER'];
export default function Users(){
  const {user}=useAuth(); const isAdmin=canManageUsers(user?.role);
  const [items,setItems]=useState<User[]>([]); const [loading,setLoading]=useState(true); const [e,setE]=useState('');
  const [email,setEmail]=useState(''); const [password,setPassword]=useState(''); const [role,setRole]=useState<Role>('VIEWER'); const [busy,setBusy]=useState(false); const [message,setMessage]=useState('');
  const load=()=>{setLoading(true);setE('');api<{items:User[]}>('/users').then(r=>setItems(r.items)).catch(x=>setE(x.message)).finally(()=>setLoading(false))}; useEffect(load,[]);
  async function create(e:FormEvent){e.preventDefault();setBusy(true);setE('');setMessage('');try{await api('/users',{method:'POST',body:JSON.stringify({email,password,role})});setEmail('');setPassword('');setRole('VIEWER');setMessage('User created.');load()}catch(x:any){setE(x.message)}finally{setBusy(false)}}
  async function update(id:string,body:Partial<Pick<User,'role'|'is_active'>>){setE('');try{await api(`/users/${id}`,{method:'PATCH',body:JSON.stringify(body)});load()}catch(x:any){setE(x.message)}}
  if(loading)return <Loading/>; if(e&&!items.length)return <ErrorState message={e} onRetry={load}/>;
  return <><PageTitle title="Users" description="Same-merchant user administration. Backend RBAC remains authoritative."/>
    {isAdmin&&<section className="panel" style={{marginBottom:16}}><h3>Create user</h3><form className="filters" onSubmit={create}><label>Email<input required type="email" value={email} onChange={x=>setEmail(x.target.value)}/></label><label>Password<input required minLength={10} maxLength={128} type="password" value={password} onChange={x=>setPassword(x.target.value)}/></label><label>Role<select value={role} onChange={x=>setRole(x.target.value as Role)}>{roles.map(r=><option key={r}>{r}</option>)}</select></label><Button disabled={busy}>{busy?'Creating…':'Create user'}</Button></form>{message&&<p className="muted">{message}</p>}</section>}
    {e&&<p className="error">{e}</p>}<Table><thead><tr><th>User</th><th>Email</th><th>Role</th><th>Active</th><th>Created</th>{isAdmin&&<th>Actions</th>}</tr></thead><tbody>{items.map(u=><tr key={u.id}><td>{u.id}</td><td>{u.email}</td><td><select aria-label={`Role for ${u.email}`} value={u.role} onChange={x=>update(u.id,{role:x.target.value as Role})}>{roles.map(r=><option key={r}>{r}</option>)}</select></td><td>{u.is_active?'Yes':'No'}</td><td>{u.created_at||'—'}</td>{isAdmin&&<td><button className="btn secondary" onClick={()=>update(u.id,{is_active:!u.is_active})}>{u.is_active?'Deactivate':'Activate'}</button></td>}</tr>)}</tbody></Table></>
}
