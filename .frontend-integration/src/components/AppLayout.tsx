 'use client';
import React,{useState,useEffect} from 'react';
import {useRouter} from 'next/navigation';
import Sidebar from './Sidebar';import Topbar from './Topbar';import {useAuth} from './AuthProvider';
export default function AppLayout({children}:{children:React.ReactNode}) {
 const [collapsed,setCollapsed]=useState(false);const {user,loading,error,reload}=useAuth();const router=useRouter();
 useEffect(()=>{if(!loading&&!user&&!error)router.replace('/sign-up-login');},[user,loading,error,router]);
 if(error)return <main className="min-h-screen flex items-center justify-center p-6"><div className="card p-8 max-w-md"><h1 className="text-xl font-bold">Connection unavailable</h1><p role="alert" className="my-4 text-muted-foreground">{error}</p><button className="btn-primary" onClick={()=>void reload()}>Retry connection</button></div></main>;
 if(loading||!user)return <main className="min-h-screen flex items-center justify-center text-muted-foreground" role="status">Restoring your workspace…</main>;
 return <div className="flex h-screen overflow-hidden bg-background"><Sidebar collapsed={collapsed} onToggle={()=>setCollapsed(!collapsed)}/><div className="flex-1 flex flex-col overflow-hidden min-w-0"><Topbar/><main className="flex-1 overflow-y-auto scrollbar-thin"><div className="max-w-screen-2xl mx-auto px-4 py-6 md:px-6 xl:px-8">{children}</div></main></div></div>;
}
