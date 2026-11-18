import {useCallback, useEffect, useState} from 'react';
import type {FormEvent} from 'react';
import {publicToken} from './api';
import {Notice, Loading} from './Components';
import {ClientReview} from './ClientReview';
import {Workspace} from './Workspace';
import {useScopeSession} from './session';
import './style.css';

function OperatorApp() {
  const auth = useScopeSession();
  const [subject, setSubject] = useState('owner_a');
  const [key, setKey] = useState('');
  const [confirmKey, setConfirmKey] = useState('');
  const clearError = useCallback(() => auth.setError(''), []);
  const clearNotice = useCallback(() => auth.setNotice(''), []);
  const roleName = auth.session?.subject === 'owner_a' ? 'Studio owner' : auth.session?.subject === 'operator_a' ? 'Team member' : auth.session?.subject === 'viewer_a' ? 'Viewer' : 'Workspace owner';
  const avatar = roleName.split(' ').map(word => word[0]).join('');
  async function login(event: FormEvent) {event.preventDefault(); await auth.signIn(subject, key); setKey('');}
  return <div className={`scope-app ${auth.session && auth.workspace ? 'is-signed-in' : ''}`}><a className="scope-skip" href="#scope-main">Skip to content</a><header className="scope-header"><a href="/" className="scope-brand">Scope &amp; Pay</a>{auth.session && auth.workspace && <span className="header-workspace-name">{auth.workspace === 'ws_a' ? 'My studio' : auth.workspace === 'ws_b' ? 'Second studio' : auth.workspace}</span>}<div className="header-right"><span className="header-environment">Demo workspace</span>{auth.session && <><span className="signed-in-as">{roleName}</span><span className="profile-avatar" aria-hidden="true">{avatar}</span><button className="header-button" disabled={auth.busy} onClick={() => void auth.signOut()}>Sign out</button></>}</div></header>
    <div className="scope-global-notices"><Notice text={auth.error} error onClose={clearError}/><Notice text={auth.notice} onClose={clearNotice}/></div>
    {auth.checking ? <main id="scope-main" className="scope-login-main"><Loading text="Restoring your session…"/></main> : !auth.session || !auth.workspace ? <main id="scope-main" className="scope-login-main"><section className="scope-login"><h1>Clear scope. Agreed changes.</h1><p className="scope-lead">Turn client requests into reviewed proposals and invoices, with the original agreement always in view.</p><div className="scope-login-form"><h2>Sign in to your workspace</h2><form onSubmit={login}><label htmlFor="scope-identity">Demo identity</label><select id="scope-identity" value={subject} onChange={e => setSubject(e.target.value)} disabled={auth.busy}><option value="owner_a">Studio owner</option><option value="operator_a">Team member</option><option value="viewer_a">Viewer</option><option value="owner_b">Second workspace owner</option></select><label htmlFor="scope-login-key">Login key</label><input id="scope-login-key" type="password" autoComplete="current-password" value={key} onChange={e => setKey(e.target.value)} disabled={auth.busy} required/><button className="primary" disabled={auth.busy}>{auth.busy ? 'Signing in…' : 'Sign in'}</button></form><p className="scope-muted">Use your local demo login key. Client review links open without a workspace account.</p></div></section></main> : <>
      {auth.confirming && <section className="scope-confirm" aria-labelledby="scope-confirm-title"><h2 id="scope-confirm-title">Confirm your identity</h2><p>Enter your login key before sharing an agreement or creating an invoice. Your project stays open.</p><form onSubmit={event => {event.preventDefault(); void auth.confirm(confirmKey).then(() => setConfirmKey(''));}}><label htmlFor="scope-confirm-key">Login key</label><div className="inline-form"><input id="scope-confirm-key" type="password" autoComplete="current-password" required value={confirmKey} onChange={e => setConfirmKey(e.target.value)}/><button className="primary" disabled={auth.busy}>Confirm identity</button><button type="button" onClick={() => {auth.setConfirming(false); setConfirmKey('');}}>Cancel</button></div></form></section>}
      <Workspace key={auth.workspace} workspace={auth.workspace} workspaces={auth.workspaces} onWorkspace={auth.setWorkspace} csrf={auth.session.csrf_token} role={auth.workspaces.find(row => row.workspace_id === auth.workspace)?.role ?? 'viewer'}/>
    </>}
    <footer className="scope-footer"><span>Scope &amp; Pay</span><a href="/operations">Payment operations console</a></footer>
  </div>;
}

export default function App() {
  const [token, setToken] = useState(publicToken);
  useEffect(() => {const changed = () => setToken(publicToken()); window.addEventListener('hashchange', changed); return () => window.removeEventListener('hashchange', changed);}, []);
  return token ? <ClientReview key={token} token={token}/> : <OperatorApp/>;
}
