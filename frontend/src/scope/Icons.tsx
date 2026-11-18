import type {ReactNode} from 'react';

export type IconName = 'home' | 'projects' | 'plus' | 'review' | 'sample' | 'arrow' | 'check';

export function Icon({name, className = ''}: {name: IconName; className?: string}) {
  const paths: Record<IconName, ReactNode> = {
    home: <><path d="m3 10 9-7 9 7"/><path d="M5 9v12h14V9M9 21v-8h6v8"/></>,
    projects: <><path d="M3 7h7l2 2h9v11H3Z"/><path d="M3 7V4h7l2 3h8v2"/></>,
    plus: <path d="M12 4v16M4 12h16"/>,
    review: <><path d="M14 3H5v18h14V8Z"/><path d="M14 3v5h5M8 12h8M8 16h5"/></>,
    sample: <><path d="m12 3 10 6-10 6L2 9Z"/><path d="m3 13 9 5 9-5M3 17l9 5 9-5"/></>,
    arrow: <path d="M5 12h14m-6-6 6 6-6 6"/>,
    check: <path d="m5 12 4 4L19 6"/>,
  };
  return <svg className={`scope-icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
