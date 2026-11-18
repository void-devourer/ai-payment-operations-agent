import {useEffect, useRef, useState} from 'react';
import {ScopeError, scopeRequest} from './api';
import type {Project, ProjectSummary, ScopeConfig, Share} from './api';

export function useScopeData(workspace: string, csrf: string) {
  const base = `/api/workspaces/${encodeURIComponent(workspace)}/scope`;
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [selected, setSelected] = useState('');
  const [config, setConfig] = useState<ScopeConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingProject, setLoadingProject] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [retryUntil, setRetryUntil] = useState(0);
  const alive = useRef(true);

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    void Promise.all([
      scopeRequest<{data: ProjectSummary[]}>(base + '/projects', {signal: controller.signal}),
      scopeRequest<ScopeConfig>(base + '/config', {signal: controller.signal}),
    ]).then(([rows, settings]) => {
      if (!controller.signal.aborted) {setProjects(rows.data); setConfig(settings);}
    }).catch(e => {if (!controller.signal.aborted) setError(e.message);})
      .finally(() => {if (!controller.signal.aborted) setLoading(false);});
    return () => {alive.current = false; controller.abort();};
  }, [base]);

  useEffect(() => {
    if (!selected) {setProject(null); return;}
    const controller = new AbortController();
    setLoadingProject(true); setError('');
    void scopeRequest<Project>(base + '/projects/' + encodeURIComponent(selected), {signal: controller.signal})
      .then(value => {if (!controller.signal.aborted) setProject(value);})
      .catch(e => {if (!controller.signal.aborted) setError(e.message);})
      .finally(() => {if (!controller.signal.aborted) setLoadingProject(false);});
    return () => controller.abort();
  }, [base, selected]);

  useEffect(() => {
    if (!project?.invoices.some(invoice => invoice.status === 'creating' || invoice.status === 'draft' && !invoice.provider_invoice_id)) return;
    const controller = new AbortController();
    const timer = setInterval(() => {
      if (document.hidden) return;
      void scopeRequest<Project>(base + '/projects/' + encodeURIComponent(project.project_id), {signal: controller.signal})
        .then(value => {if (!controller.signal.aborted) setProject(value);})
        .catch(() => {});
    }, 3000);
    return () => {controller.abort(); clearInterval(timer);};
  }, [base, project?.project_id, project?.invoices.map(invoice => invoice.status).join(',')]);

  function keep(value: Project) {
    if (!alive.current) return;
    setProject(value); setSelected(value.project_id);
    setProjects(rows => rows.some(row => row.project_id === value.project_id)
      ? rows.map(row => row.project_id === value.project_id ? value : row) : [value, ...rows]);
  }

  async function perform<T>(label: string, action: () => Promise<T>): Promise<T | null> {
    if (busy) return null;
    setBusy(label); setError(''); setNotice('');
    try {return await action();}
    catch (e) {if (alive.current) {setError((e as Error).message); if (e instanceof ScopeError && e.status === 429) setRetryUntil(Date.now() + Math.max(e.retryAfter, 1) * 1000);} return null;}
    finally {if (alive.current) setBusy('');}
  }

  const headers = {'Content-Type': 'application/json', 'X-CSRF-Token': csrf};
  async function mutate(label: string, path: string, body: unknown, method = 'POST') {
    const value = await perform(label, () => scopeRequest<Project>(base + path, {method, headers, body: JSON.stringify(body)}));
    if (value) keep(value);
    return value;
  }

  async function share(proposalId: string, version: number) {
    if (!project) return null;
    const value = await perform('Creating review link', () => scopeRequest<Share>(`${base}/projects/${project.project_id}/proposals/${proposalId}/share`, {method: 'POST', headers, body: JSON.stringify({expected_version: version})}));
    if (value) {
      try {keep(await scopeRequest<Project>(base + '/projects/' + project.project_id));}
      catch {setNotice('Your review link is ready. Refresh the project if its status has not updated.');}
    }
    return value;
  }

  async function reload() {
    if (!project) return;
    const value = await perform('Refreshing project', () => scopeRequest<Project>(base + '/projects/' + project.project_id));
    if (value) keep(value);
  }

  return {base, projects, project, config, selected, setSelected, loading, loadingProject, busy, error, setError, notice, setNotice, retryUntil, mutate, share, reload};
}

export type ScopeData = ReturnType<typeof useScopeData>;
