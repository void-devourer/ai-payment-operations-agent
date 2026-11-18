import {useEffect, useRef, useState} from 'react';
import type {Session, Workspace} from '../api';
import {ScopeError, scopeRequest, invalidateScopeRequests} from './api';

export function useScopeSession() {
  const [session, setSession] = useState<Session | null>(null);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspace, setWorkspace] = useState('');
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirming, setConfirming] = useState(false);
  const epoch = useRef(0);

  function clearSession() {setSession(null); setWorkspaces([]); setWorkspace(''); setConfirming(false);}
  useEffect(() => {
    const controller = new AbortController();
    const current = epoch.current;
    void (async () => {
      try {
        const found = await scopeRequest<Session>('/api/session', {signal: controller.signal});
        const rows = await scopeRequest<Workspace[]>('/api/workspaces', {signal: controller.signal});
        if (controller.signal.aborted || current !== epoch.current) return;
        setSession(found); setWorkspaces(rows); setWorkspace(rows[0]?.workspace_id ?? '');
      } catch (e) {
        if (!controller.signal.aborted && current === epoch.current && !(e instanceof ScopeError && e.status === 401)) setError((e as Error).message);
      } finally {if (!controller.signal.aborted && current === epoch.current) setChecking(false);}
    })();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const ended = () => {invalidateScopeRequests(); epoch.current++; clearSession(); setBusy(false); setChecking(false); setError(''); setNotice('Your session ended. Sign in to continue.');};
    const confirm = () => setConfirming(true);
    window.addEventListener('session-ended', ended);
    window.addEventListener('session-confirmation', confirm);
    return () => {window.removeEventListener('session-ended', ended); window.removeEventListener('session-confirmation', confirm);};
  }, []);

  useEffect(() => {
    if (!session) return;
    const controller = new AbortController();
    const current = epoch.current;
    let running = false;
    async function renew() {
      if (document.hidden || running) return;
      running = true;
      try {
        const renewed = await scopeRequest<Session>('/api/session', {signal: controller.signal});
        if (!controller.signal.aborted && current === epoch.current) setSession(renewed);
      } catch (e) {
        if (!controller.signal.aborted && current === epoch.current && e instanceof ScopeError && e.status === 401) window.dispatchEvent(new Event('session-ended'));
      } finally {running = false;}
    }
    const timer = setInterval(() => void renew(), 900000);
    window.addEventListener('focus', renew);
    return () => {controller.abort(); clearInterval(timer); window.removeEventListener('focus', renew);};
  }, [!!session]);

  async function signIn(subject: string, key: string) {
    invalidateScopeRequests();
    const current = ++epoch.current; setBusy(true); setError(''); setNotice('');
    try {
      const found = await scopeRequest<Session>(`/dev/sessions/${encodeURIComponent(subject)}`, {method: 'POST', headers: {'X-Demo-Login-Key': key}});
      const rows = await scopeRequest<Workspace[]>('/api/workspaces');
      if (current !== epoch.current) return;
      setSession(found); setWorkspaces(rows); setWorkspace(rows[0]?.workspace_id ?? '');
    } catch (e) {if (current === epoch.current) setError((e as Error).message);}
    finally {if (current === epoch.current) {setBusy(false); setChecking(false);}}
  }

  async function signOut() {
    invalidateScopeRequests();
    const current = ++epoch.current; setBusy(true); setError('');
    try {
      await scopeRequest(`/api/workspaces/${encodeURIComponent(workspace)}/sessions/revoke`, {method: 'POST', headers: {'X-CSRF-Token': session?.csrf_token ?? ''}});
      if (current !== epoch.current) return;
      clearSession(); setNotice('Signed out.');
    } catch (e) {if (current === epoch.current) setError((e as Error).message);}
    finally {if (current === epoch.current) setBusy(false);}
  }

  async function confirm(key: string) {
    setBusy(true); setError('');
    try {
      const result = await scopeRequest<{confirmation_until: string}>(`/api/workspaces/${encodeURIComponent(workspace)}/sessions/confirm`, {method: 'POST', headers: {'X-CSRF-Token': session?.csrf_token ?? '', 'X-Demo-Login-Key': key}});
      setSession(value => value ? {...value, confirmation_until: result.confirmation_until} : value);
      setConfirming(false); setNotice('Identity confirmed. You can repeat the action.');
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  return {session, workspaces, workspace, setWorkspace, checking, busy, error, setError, notice, setNotice, confirming, setConfirming, signIn, signOut, confirm};
}
