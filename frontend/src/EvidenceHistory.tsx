import type { Timeline } from './api';
import { label } from './labels';

const when = (date: string) => new Date(date).toLocaleString();
// Group adjacent equivalent findings. Preserve source failures, payment and
// reversal changes even when the policy outcome happens to remain unchanged.
function signature(row: Timeline) {
  return JSON.stringify([row.outcome, row.reasons, row.facts.payments,
    row.facts.orders, row.facts.refunds, row.facts.disputes, row.facts.access, row.facts.errors]);
}
export function EvidenceHistory({timeline, cursor, busy, onMore}: {
  timeline: Timeline[]; cursor: number | null; busy: boolean; onMore: () => void;
}) {
  const groups: {latest: Timeline; earliest: Timeline; count: number; signature: string}[] = [];
  for (const row of timeline) {
    const previous = groups.at(-1);
    const key = signature(row);
    if (previous && previous.signature === key) {previous.count++; previous.earliest = row;}
    else groups.push({latest: row, earliest: row, count: 1, signature: key});
  }
  return <section className="detail-section"><h3>Finding history</h3>
    {!timeline.length ? <p>No checks recorded yet.</p> : <>
      <p className="muted">Repeated checks with the same records are grouped together.</p>
      <ol className="finding-history">{groups.slice(0, 5).map(group => <li key={group.latest.observation_id}>
        <strong>{label(group.latest.outcome)}</strong><p>{group.latest.reasons.map(label).join('; ')}</p>
        <p className="muted">{when(group.latest.finished_at)}{group.count > 1 && ` · Same finding across ${group.count} checks`}</p>
      </li>)}</ol>
      <details><summary>All evidence checks ({timeline.length} loaded)</summary>
        <ol className="timeline">{timeline.map(row => <li key={row.observation_id}><strong>{label(row.outcome)}</strong>
          <span>{when(row.finished_at)}</span><span>{row.reasons.map(label).join('; ')}</span>
          <details className="reference-details"><summary>Technical check reference</summary><p className="mono">{row.observation_id}</p><p>Evidence version {row.generation}</p></details>
        </li>)}</ol>{cursor && <button className="secondary" disabled={busy} onClick={onMore}>Load earlier checks</button>}
      </details>
    </>}
  </section>;
}
