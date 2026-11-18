import {useCallback, useState} from 'react';
import type {FormEvent} from 'react';
import type {Workspace as WorkspaceRecord} from '../api';
import {amountMinor} from './api';
import {Loading, Notice} from './Components';
import {ProjectView} from './ProjectView';
import {Home, ProjectTable} from './Home';
import {Icon} from './Icons';
import {useScopeData} from './useScopeData';

export function Workspace({workspace, workspaces, onWorkspace, csrf, role}: {workspace: string; workspaces: WorkspaceRecord[]; onWorkspace: (id: string) => void; csrf: string; role: string}) {
  const data = useScopeData(workspace, csrf);
  const [view, setView] = useState<'home' | 'projects'>('home');
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState('');
  const [form, setForm] = useState({name:'', client_name:'', client_email:'', brief:'', amount:''});
  const canEdit = role !== 'viewer';
  const busy = !!data.busy;
  const aiMode = data.config?.analysis.mode;
  const aiReady = aiMode === 'openai' || aiMode === 'gemini';
  const aiName = aiMode === 'gemini' ? 'Gemini' : aiMode === 'openai' ? 'OpenAI' : 'AI';
  const clearError = useCallback(() => data.setError(''), []);
  const clearNotice = useCallback(() => data.setNotice(''), []);
  const shown = data.projects.filter(project => `${project.name} ${project.client_name}`.toLowerCase().includes(search.toLowerCase()));
  const isHome = !creating && !data.selected && view === 'home';
  function navigate(next: 'home' | 'projects') {setCreating(false); data.setSelected(''); setView(next);}
  function openProject(id: string) {setView('projects'); setCreating(false); data.setSelected(id);}
  function newProject() {setView('projects'); data.setSelected(''); setCreating(true);}
  function sample() {setView('projects'); setCreating(false); void data.mutate('Loading sample project', '/demo', {});}
  async function create(event: FormEvent) {
    event.preventDefault();
    try {
      const result = await data.mutate('Creating project', '/projects', {name:form.name,client_name:form.client_name,client_email:form.client_email,brief:form.brief,base_amount_minor:amountMinor(form.amount),currency:'usd'});
      if (result) {setCreating(false); setForm({name:'',client_name:'',client_email:'',brief:'',amount:''});}
    } catch (e) {data.setError((e as Error).message);}
  }
  return <div className="scope-layout">
    <aside className="scope-sidebar" aria-label="Workspace navigation">
      {canEdit && <button className="sidebar-create primary" onClick={newProject} disabled={busy}><Icon name="plus"/>Create project</button>}
      <nav className="sidebar-nav" aria-label="Main navigation">
        <button className={`sidebar-item ${isHome ? 'is-selected' : ''}`} aria-current={isHome ? 'page' : undefined} onClick={() => navigate('home')} disabled={busy}><Icon name="home"/>Home</button>
        <button className={`sidebar-item ${!creating && !data.selected && view === 'projects' ? 'is-selected' : ''}`} aria-current={!creating && !data.selected && view === 'projects' ? 'page' : undefined} onClick={() => navigate('projects')} disabled={busy}><Icon name="projects"/>Projects</button>
      </nav>
      <div className="sidebar-workspace"><label htmlFor="scope-workspace">Your workspace</label><select id="scope-workspace" value={workspace} onChange={e => onWorkspace(e.target.value)} disabled={busy}>{workspaces.map(row => <option key={row.workspace_id} value={row.workspace_id}>{row.workspace_id === 'ws_a' ? 'My studio' : row.workspace_id === 'ws_b' ? 'Second studio' : row.workspace_id}</option>)}</select></div>
      {data.projects.length > 0 && <div className="sidebar-projects"><p>Recent projects</p>{data.projects.slice(0,5).map(project => <button className={`sidebar-item sidebar-project ${data.selected === project.project_id ? 'is-selected' : ''}`} aria-current={data.selected === project.project_id ? 'page' : undefined} key={project.project_id} onClick={() => openProject(project.project_id)} disabled={busy}><span>{project.name}</span></button>)}</div>}
      <div className="sidebar-connection"><p><span className={`connection-dot ${aiReady ? 'connected' : ''}`}/>{aiName} {aiReady ? 'configured' : 'not configured'}</p><p><span className={`connection-dot ${data.config?.invoice.mode === 'paypal_sandbox' ? 'connected' : ''}`}/>{data.config?.invoice.mode === 'paypal_sandbox' ? 'PayPal sandbox' : 'Local invoice demo'}</p></div>
    </aside>
    <main id="scope-main" className="scope-main">
      <Notice text={data.error} error onClose={clearError}/><Notice text={data.notice} onClose={clearNotice}/>
      {data.loading ? <Loading text="Loading your workspace…"/> : creating ? <section className="new-project">
        <button className="text-button" onClick={() => navigate('projects')}>Back to projects</button><h1>Start with the agreement</h1><p className="scope-lead">Save the original scope and price. Later requests will be reviewed against this brief.</p>
        <form onSubmit={create} className="scope-form">
          <label htmlFor="new-project-name">Project name</label><input id="new-project-name" value={form.name} onChange={e => setForm({...form,name:e.target.value})} maxLength={160} required placeholder="e.g. Northstar website"/>
          <div className="form-columns"><div><label htmlFor="new-client-name">Client name</label><input id="new-client-name" value={form.client_name} onChange={e => setForm({...form,client_name:e.target.value})} maxLength={160} required/></div><div><label htmlFor="new-client-email">Client email</label><input id="new-client-email" type="email" value={form.client_email} onChange={e => setForm({...form,client_email:e.target.value})} maxLength={254} required/></div></div>
          <label htmlFor="new-brief">Agreed project brief</label><textarea id="new-brief" rows={8} maxLength={6000} value={form.brief} onChange={e => setForm({...form,brief:e.target.value})} required placeholder="Describe the deliverables, included revisions and any exclusions."/>
          <label htmlFor="new-base-price">Original agreed price (USD)</label><div className="price-input"><span>$</span><input id="new-base-price" inputMode="decimal" value={form.amount} onChange={e => setForm({...form,amount:e.target.value})} required placeholder="500.00"/></div>
          <div className="form-actions"><button className="primary" disabled={busy}>{data.busy || 'Create project'}</button><button type="button" onClick={() => navigate('projects')} disabled={busy}>Cancel</button></div>
        </form>
      </section> : data.selected ? data.loadingProject ? <Loading/> : data.project ? <ProjectView key={data.project.project_id} data={data} project={data.project} canEdit={canEdit}/> : <div className="scope-empty"><h1>Project unavailable</h1><p>Choose another project or return to the project list.</p><button onClick={() => navigate('projects')}>All projects</button></div> : view === 'home' ?
        <Home projects={data.projects} canEdit={canEdit} busy={busy} onCreate={newProject} onProjects={() => navigate('projects')} onOpen={openProject} onSample={sample}/>
      : <section className="project-index">
        <div className="scope-page-heading"><div><h1>Your projects</h1><p className="scope-lead">Agreed work, client requests and invoices. All in one place.</p></div>{canEdit && <button className="primary" onClick={newProject}><Icon name="plus"/>New project</button>}</div>
        {!data.projects.length ? <div className="scope-empty first-project"><h2>One clear agreement for every change.</h2><p>Start a project with its agreed brief, or explore a sample website project with three different client requests.</p>{canEdit && <div className="form-actions"><button className="primary" onClick={newProject}>Create your first project</button><button disabled={busy} onClick={sample}>Load sample project</button></div>}<ol className="scope-walkthrough"><li><strong>Save the original brief</strong><span>Keep the agreed scope and price as your reference.</span></li><li><strong>Review client requests</strong><span>Separate included work, additions and open questions.</span></li><li><strong>Agree, then invoice</strong><span>The client accepts the exact change and amount.</span></li></ol></div> : <>
          <div className="project-toolbar"><div><label htmlFor="project-search">Find a project</label><input id="project-search" type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder="Project or client name"/></div>{canEdit && <button disabled={busy} onClick={sample}>Open sample project</button>}</div>
          <ProjectTable projects={shown} onOpen={openProject}/>
          {!shown.length && <p className="scope-empty">No projects match “{search}”. Try a client or project name.</p>}
        </>}
      </section>}
    </main>
  </div>;
}
