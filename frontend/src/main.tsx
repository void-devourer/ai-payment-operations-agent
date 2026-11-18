import {lazy, Suspense} from 'react';
import {createRoot} from 'react-dom/client';
import ScopeApp from './scope/App';

const LegacyConsole = lazy(() => import('./LegacyConsole'));
const legacy = window.location.pathname === '/operations' || window.location.pathname.startsWith('/operations/');
if (!legacy) document.body.classList.add('scope-host');
document.title = legacy ? 'Payment Operations' : 'Scope & Pay';
createRoot(document.getElementById('root')!).render(legacy
  ? <Suspense fallback={<p>Loading payment operations…</p>}><LegacyConsole/></Suspense>
  : <ScopeApp/>);
