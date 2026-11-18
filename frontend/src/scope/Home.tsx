import {money, date} from './api';
import type {ProjectSummary} from './api';
import {Badge} from './Components';
import {Icon} from './Icons';

export function ProjectTable({projects, onOpen}: {projects: ProjectSummary[]; onOpen: (id: string) => void}) {
  return <div className="project-table-wrap"><table className="project-table">
    <thead><tr><th>Project</th><th>Client</th><th>Original price</th><th>Created</th><th><span className="visually-hidden">Open project</span></th></tr></thead>
    <tbody>{projects.map(project => <tr key={project.project_id}>
      <td><button className="project-name" onClick={() => onOpen(project.project_id)}>{project.name}</button>{project.demo && <Badge>Sample project</Badge>}</td>
      <td>{project.client_name}<small>{project.client_email}</small></td>
      <td data-label="Original price">{money(project.base_amount_minor, project.currency)}</td>
      <td data-label="Created" className="project-created">{date(project.created_at)}</td>
      <td><button className="project-open" onClick={() => onOpen(project.project_id)} aria-label={`Open ${project.name}`}><Icon name="arrow"/></button></td>
    </tr>)}</tbody>
  </table></div>;
}

export function Home({projects, canEdit, busy, onCreate, onProjects, onOpen, onSample}: {
  projects: ProjectSummary[]; canEdit: boolean; busy: boolean;
  onCreate: () => void; onProjects: () => void; onOpen: (id: string) => void; onSample: () => void;
}) {
  const clientProjects = projects.filter(project => !project.demo);
  const originalValue = clientProjects.reduce((total, project) => total + project.base_amount_minor, 0);
  const clients = new Set(clientProjects.map(project => project.client_email.trim().toLowerCase())).size;
  const latest = clientProjects[0] ?? projects[0];
  return <section className="workspace-home">
    <section className="workspace-hero" aria-labelledby="workspace-value-title">
      <p className="workspace-value"><span>{money(originalValue, 'usd')}</span><span className="value-currency">USD</span></p>
      <h1 id="workspace-value-title">Original project value</h1>
      <p className="value-context">Across {clientProjects.length} client {clientProjects.length === 1 ? 'project' : 'projects'}. Sample projects excluded.</p>
      <button className="hero-action" onClick={onProjects}>View your projects</button>
    </section>
    <section className="home-section" aria-labelledby="quick-access-title">
      <h2 id="quick-access-title">Quick access</h2>
      <div className="quick-access">
        {canEdit && <button disabled={busy} onClick={onCreate}><span className="quick-icon"><Icon name="plus"/></span><span>New project</span></button>}
        <button disabled={busy} onClick={onProjects}><span className="quick-icon"><Icon name="projects"/></span><span>All projects</span></button>
        <button disabled={busy || !latest} onClick={() => latest && onOpen(latest.project_id)}><span className="quick-icon"><Icon name="review"/></span><span>Review latest project</span></button>
        {canEdit && <button disabled={busy} onClick={onSample}><span className="quick-icon"><Icon name="sample"/></span><span>Explore sample project</span></button>}
      </div>
    </section>
    <section className="home-section" aria-labelledby="workspace-overview-title">
      <div className="home-section-heading"><h2 id="workspace-overview-title">Workspace overview</h2><span>Current workspace</span></div>
      <dl className="workspace-overview">
        <div><dt>Client projects</dt><dd>{clientProjects.length}<span>Original briefs and agreed prices</span></dd></div>
        <div><dt>Clients</dt><dd>{clients}<span>Across your client projects</span></dd></div>
        <div><dt>Sample projects</dt><dd>{projects.length - clientProjects.length}<span>Try the workflow with example data</span></dd></div>
      </dl>
    </section>
    <section className="home-section recent-projects" aria-labelledby="recent-projects-title">
      <div className="home-section-heading"><h2 id="recent-projects-title">Recent projects</h2><button className="text-button" onClick={onProjects}>View all projects</button></div>
      {projects.length ? <ProjectTable projects={projects.slice(0, 5)} onOpen={onOpen}/> : <div className="scope-empty home-empty"><h3>Your first agreement starts here.</h3><p>Save a project's original scope and price, or explore a sample before adding your own.</p>{canEdit && <button className="primary" onClick={onCreate}>Create a project</button>}</div>}
    </section>
  </section>;
}
