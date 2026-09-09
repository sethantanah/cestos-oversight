// One token rotation per browser session, including concurrent requests and tabs.
const ACCESS = 'cestos_access_token';
const REFRESH = 'cestos_refresh_token';
export function getAccessToken() { return typeof window === 'undefined' ? null : sessionStorage.getItem(ACCESS) || localStorage.getItem(ACCESS); }
export function getRefreshToken() { return typeof window === 'undefined' ? null : sessionStorage.getItem(REFRESH) || localStorage.getItem(REFRESH); }
export function clearTokens() {
  if (typeof window === 'undefined') return;
  for (const storage of [sessionStorage, localStorage]) { storage.removeItem(ACCESS); storage.removeItem(REFRESH); }
}
export function setTokens(access: string, refresh: string, remember?: boolean) {
  const persistent = remember ?? !!localStorage.getItem(REFRESH);
  clearTokens();
  const storage = persistent ? localStorage : sessionStorage;
  storage.setItem(ACCESS, access); storage.setItem(REFRESH, refresh);
}
let refreshing: Promise<boolean> | null = null;
export function refreshSession(base: string, failedAccess: string | null): Promise<boolean> {
  if (refreshing) return refreshing;
  const rotate = async () => {
    if (getAccessToken() && getAccessToken() !== failedAccess) return true;
    const token = getRefreshToken();
    if (!token) return false;
    const response = await fetch(`${base}/api/v1/auth/refresh`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({refresh_token:token}), cache:'no-store' });
    if (response.status === 401) { if (getRefreshToken() === token) clearTokens(); return false; }
    if (!response.ok) throw new Error('Session could not be renewed. Please retry.');
    const data = await response.json();
    if (getRefreshToken() !== token) return !!getAccessToken(); // Logout or a new login won the race.
    setTokens(data.access_token, data.refresh_token);
    return true;
  };
  const pending = Promise.resolve(typeof navigator !== 'undefined' && navigator.locks
    ? navigator.locks.request('cestos-session-refresh', rotate) : rotate()).then(value => value).finally(() => { refreshing = null; });
  refreshing = pending;
  return pending;
}
