'use client';
import {createContext,useContext,useEffect,useState} from 'react';
import {api,clearToken,setToken,tryRestoreSession} from './api';
import type {User} from '../types';

type LoginResult={mfaRequired?:boolean;mfaChallenge?:string;mfaSetupRequired?:boolean;mfaSetupToken?:string};
type AuthContext={user:User|null;loading:boolean;login:(email:string,password:string)=>Promise<LoginResult>;logout:()=>Promise<void>};
const Auth=createContext<AuthContext>({user:null,loading:true,login:async()=>({}),logout:async()=>{}});

export function AuthProvider({children}:{children:React.ReactNode}){
 const [user,setUser]=useState<User|null>(null); const [loading,setLoading]=useState(true);
 useEffect(()=>{let active=true;
  function expired(){clearToken();if(active){setUser(null);setLoading(false)}if(typeof window!=='undefined'&&!['/login','/register'].includes(window.location.pathname))window.location.replace('/login')}
  window.addEventListener('rcaa:auth-expired',expired);
  async function restore(){try{if(await tryRestoreSession()){const current=await api<User>('/auth/me');if(active)setUser(current)}}catch{clearToken();if(active)setUser(null)}finally{if(active)setLoading(false)}}
  void restore(); return()=>{active=false;window.removeEventListener('rcaa:auth-expired',expired)};
 },[]);
 async function login(email:string,password:string):Promise<LoginResult>{setLoading(true);try{const r=await api<{access_token?:string;mfa_required?:boolean;mfa_challenge?:string;mfa_setup_required?:boolean;mfa_setup_token?:string}>('/auth/login',{method:'POST',body:JSON.stringify({email:email.trim().toLowerCase(),password})});
   if(r.mfa_required||r.mfa_setup_required)return {mfaRequired:r.mfa_required,mfaChallenge:r.mfa_challenge,mfaSetupRequired:r.mfa_setup_required,mfaSetupToken:r.mfa_setup_token};
   if(!r.access_token)throw new Error('Login succeeded but no access token was returned.');setToken(r.access_token);setUser(await api<User>('/auth/me'));return {};
  }catch(error){clearToken();setUser(null);throw error}finally{setLoading(false)}}
 async function logout(){try{await api('/auth/logout',{method:'POST'})}catch{}finally{clearToken();setUser(null);if(typeof window!=='undefined')window.location.replace('/login')}}
 return <Auth.Provider value={{user,loading,login,logout}}>{children}</Auth.Provider>;
}
export function useAuth(){return useContext(Auth)}
