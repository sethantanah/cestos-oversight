 'use client';
import {createContext, useContext, useEffect, useState, useCallback, ReactNode} from 'react';
import {apiFetch, getMe, getAccessToken, getRefreshToken, logout, UserRead, ApiError} from '@/lib/api';
type Access = {roles: string[]; permissions: string[]; is_superuser: boolean};
type Auth = {user: UserRead | null; access: Access | null; loading: boolean; error: string; reload: () => Promise<void>; signOut: () => Promise<void>; can: (code:string) => boolean};
const Context = createContext<Auth | null>(null);
export function AuthProvider({children}:{children:ReactNode}) {
 const [user,setUser]=useState<UserRead|null>(null); const [access,setAccess]=useState<Access|null>(null);
 const [loading,setLoading]=useState(true); const [error,setError]=useState('');
 const reload=useCallback(async()=>{setLoading(true);setError('');try {
  if (!getAccessToken() && !getRefreshToken()) {setUser(null);setAccess(null);return;}
  const profile=await getMe(); const permissions=await apiFetch<Access>('/api/v1/auth/access');
  setUser(profile);setAccess(permissions);
 }catch(e){if(e instanceof ApiError && e.status===401){setUser(null);setAccess(null);}else setError(e instanceof Error?e.message:'Could not restore session.');}finally{setLoading(false);}},[]);
 useEffect(()=>{if(window.location.hash.startsWith('#reset=')&&window.location.pathname!=='/sign-up-login'){window.location.replace('/sign-up-login'+window.location.hash);return;}void reload();const expired=()=>{setUser(null);setAccess(null);setLoading(false);};const changed=(e:StorageEvent)=>{if(e.key?.startsWith('cestos_'))void reload();};window.addEventListener('cestos:session-expired',expired);window.addEventListener('storage',changed);return()=>{window.removeEventListener('cestos:session-expired',expired);window.removeEventListener('storage',changed);};},[reload]);
 const signOut=async()=>{try {await logout();}finally{setUser(null);setAccess(null);window.location.assign('/sign-up-login');}};
 const can=(code:string)=>!!access&&(access.is_superuser||access.permissions.includes(code)||(code.startsWith('inventory.')&&access.permissions.includes('inventory.admin')));
 return <Context.Provider value={{user,access,loading,error,reload,signOut,can}}>{children}</Context.Provider>;
}
export function useAuth(){const value=useContext(Context);if(!value)throw new Error('AuthProvider missing');return value;}
