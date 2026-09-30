import { useCandidate } from '../candidate/CandidateContext';
import { Brand } from './Brand';
import { User } from './Icons';

export function AppHeader() {
  const { name, email, organization } = useCandidate();
  return (
    <header className="app-header">
      <Brand organization={organization} />
      <div className="user-chip" title={email ?? undefined}>
        <span className="avatar">
          <User size={16} />
        </span>
        <span>{name}</span>
      </div>
    </header>
  );
}
