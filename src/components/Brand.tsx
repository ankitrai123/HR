import { candidate } from '../data/candidate';

/** Placeholder brand marks. Swap the SVGs/text for your organization's logos. */
export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="32" height="32">
          <rect width="32" height="32" rx="8" fill="currentColor" />
          <path d="M9 21l5-10 4 7 2-3 3 6" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="brand-name">
        {candidate.organization}
        {!compact && <small>Talent Assessment</small>}
      </span>
      {!compact && (
        <>
          <span className="brand-divider" aria-hidden="true" />
          <span className="brand-partner">
            <strong>Psych</strong>Assess
          </span>
        </>
      )}
    </div>
  );
}
