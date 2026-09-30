/** Placeholder brand marks. Swap the SVG/text for your organization's logos. */
export function Brand({ organization, compact = false, subtitle = 'Talent Assessment' }: {
  organization: string;
  compact?: boolean;
  subtitle?: string;
}) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 32 32" width="32" height="32">
          <rect width="32" height="32" rx="8" fill="currentColor" />
          <path d="M9 21l5-10 4 7 2-3 3 6" fill="none" stroke="#fff" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span className="brand-name">
        {organization}
        {!compact && <small>{subtitle}</small>}
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
