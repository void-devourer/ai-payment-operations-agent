import { useCallback, useEffect, useState } from 'react';
import { ApiError, request } from './api';
import { Notice } from './Notice';
type Check = {job_id: string; requested_at: string; retry_after_seconds: number};
type Status = {state: string; started_at: string | null; observation_id: string | null};
export function CheckRecords({base, caseId, csrf, role, onChanged}: {
  base: string; caseId: string; csrf: string; role: string | undefined; onChanged: () => void;
}) {
  const [check, setCheck] = useState<Check | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [deadline, setDeadline] = useState(0);
  const [ready, setReady] = useState(false);
  const [now, setNow] = useState(Date.now());
  const close = useCallback(() => setMessage(''), []);
  const writable = !!csrf && (role === 'owner' || role === 'operator');
  const seconds = Math.max(0, Math.ceil((deadline - now) / 1000));
  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    async function availability() {
      if (running || controller.signal.aborted) return;
      running = true;
      try {
        const result = await request<{retry_after_seconds: number}>(`${base}/cases/${caseId}/check-availability`, {signal: controller.signal});
        if (!controller.signal.aborted) {setDeadline(Date.now() + result.retry_after_seconds * 1000); setReady(true);}
      } catch (e) {if (!controller.signal.aborted) {setReady(false); setMessage((e as Error).message);}}
      finally {running = false;}
    }
    void availability();
    const timer = setInterval(() => void availability(), 5000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    window.addEventListener('focus', availability);
    return () => {controller.abort(); clearInterval(timer); clearInterval(clock); window.removeEventListener('focus', availability);};
  }, [base, caseId]);
  useEffect(() => {
    if (!check) return;
    const controller = new AbortController();
    let running = false;
    const timeout = Date.now() + 180000;
    async function poll() {
      if (running || controller.signal.aborted) return;
      running = true;
      try {
        const status = await request<Status>(`${base}/cases/${caseId}/checks/${check!.job_id}`, {signal: controller.signal});
        if (controller.signal.aborted) return;
        if (status.observation_id && status.started_at && Date.parse(status.started_at) >= Date.parse(check!.requested_at)) {
          setCheck(null); setMessage('Latest records are ready.'); onChanged();
        } else if (status.state === 'dead') {setCheck(null); setMessage('The check failed. See Integration health for details.');}
        else if (Date.now() >= timeout) {setCheck(null); setMessage('The check is still processing. Results will appear automatically.');}
      } catch (e) {if (!controller.signal.aborted) {setCheck(null); setMessage((e as Error).message);}}
      finally {running = false;}
    }
    void poll();
    const timer = setInterval(() => void poll(), 3000);
    return () => {controller.abort(); clearInterval(timer);};
  }, [base, caseId, check, onChanged]);
  async function start() {
    setBusy(true); setMessage('');
    try {
      const result = await request<Check>(`${base}/cases/${caseId}/check`, {method:'POST', headers:{'X-CSRF-Token':csrf}});
      setCheck(result); setDeadline(Date.now() + result.retry_after_seconds * 1000);
    } catch (e) {
      if (e instanceof ApiError && e.status === 429) setDeadline(Date.now() + e.retryAfter * 1000);
      setMessage((e as Error).message);
    } finally {setBusy(false);}
  }
  return <div className="check-records"><button disabled={!writable || !ready || busy || !!check || seconds > 0} onClick={start}>
    {busy ? 'Requesting check…' : check ? 'Checking records…' : seconds > 0 ? `Check available in ${seconds}s` : !ready ? 'Checking availability…' : 'Check latest records'}
  </button>{check && seconds > 0 && <p className="muted">Another check is available in {seconds}s.</p>}
    {role === 'viewer' && <p className="muted">An owner or operator can request a new check.</p>}
    <Notice text={message} onClose={close}/>
  </div>;
}
