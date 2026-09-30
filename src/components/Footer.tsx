import type { Support } from '../candidate/CandidateContext';

export function Footer({ organization, support }: { organization: string; support?: Support }) {
  return (
    <footer className="app-footer">
      <span>© {new Date().getFullYear()} {organization}. All rights reserved.</span>
      {support && (support.email || support.phone) && (
        <span>
          Need help? Contact us at <a href={`mailto:${support.email}`}>{support.email}</a>
          {support.phone && (
            <>
              {' '}or <a href={`tel:${support.phone.replace(/\s/g, '')}`}>{support.phone}</a>
            </>
          )}
        </span>
      )}
    </footer>
  );
}
