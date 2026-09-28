import { candidate } from '../data/candidate';
import { Brand } from './Brand';
import { User } from './Icons';

export function AppHeader() {
  return (
    <header className="app-header">
      <Brand />
      <div className="user-chip" title={candidate.email}>
        <span className="avatar">
          <User size={16} />
        </span>
        <span>{candidate.name}</span>
      </div>
    </header>
  );
}
