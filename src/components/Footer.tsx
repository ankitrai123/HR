import { candidate, support } from '../data/candidate';

export function Footer() {
  return (
    <footer className="app-footer">
      <span>© {new Date().getFullYear()} {candidate.organization}. All rights reserved.</span>
      <span>
        Need help? Contact us at <a href={`mailto:${support.email}`}>{support.email}</a> or{' '}
        <a href={`tel:${support.phone.replace(/\s/g, '')}`}>{support.phone}</a>
      </span>
    </footer>
  );
}
