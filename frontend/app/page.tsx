'use client';
import {useAuth} from '../lib/auth';
import Marketing from './marketing/page';
import DashboardView from './dashboard-view';
export default function Home(){const {user,loading}=useAuth();if(loading)return <main className="center"><div className="panel">Loading…</div></main>;return user?<DashboardView/>:<Marketing/>}
