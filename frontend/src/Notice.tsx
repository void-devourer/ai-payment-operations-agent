import { useEffect } from 'react';

export function Notice({text, onClose, error = false}: {text: string; onClose: () => void; error?: boolean}) {
  useEffect(() => {
    if (!text) return;
    const timer = setTimeout(onClose, 8000);
    return () => clearTimeout(timer);
  }, [text, onClose]);
  if (!text) return null;
  return <div className={`notification ${error ? 'alert' : 'notice'}`} role={error ? 'alert' : 'status'}>
    <span>{text}</span><button className="dismiss-notice" aria-label="Dismiss message" onClick={onClose}>×</button>
  </div>;
}
