import { useCallback, useEffect, useState } from 'react';
import { Brand } from '../components/Brand';
import { Footer } from '../components/Footer';
import { Check, Clock, X } from '../components/Icons';
import { fetchInvite, type InviteResponse } from './api';
import { AssessmentFlow } from './AssessmentFlow';
import { CandidateContext, type CandidateInfo } from './CandidateContext';

const MESSAGES: Record<string, { title: string; body: string; icon: 'check' | 'clock' | 'x' }> = {
  completed: {
    title: 'Assessment already submitted',
    body: 'Thank you — we have received your responses. The HR team will contact you about next steps.',
    icon: 'check',
  },
  expired: {
    title: 'This link has expired',
    body: 'Please contact HR if you still need to take the assessment; they can extend your link.',
    icon: 'clock',
  },
  revoked: {
    title: 'This link is no longer active',
    body: 'It was withdrawn by the organisation. Please contact HR if you think this is a mistake.',
    icon: 'x',
  },
  invalid: {
    title: 'Link not recognised',
    body: 'Check that you opened the full link from your invitation. If it still doesn’t work, contact HR.',
    icon: 'x',
  },
};

export function StatusScreen({ title, body, icon, organization, support, action }: {
  title: string;
  body: string;
  icon: 'check' | 'clock' | 'x' | 'spinner';
  organization: string;
  support?: InviteResponse['support'];
  action?: React.ReactNode;
}) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Brand organization={organization || 'Talent Assessment'} />
      </header>
      <main className="page page-complete">
        <section className="card complete-card">
          <span className={`complete-badge${icon === 'x' || icon === 'clock' ? ' is-warning' : ''}`}>
            {icon === 'spinner' ? <span className="spinner spinner-lg" /> : icon === 'check' ? <Check size={32} />
              : icon === 'clock' ? <Clock size={32} /> : <X size={32} />}
          </span>
          <h1>{title}</h1>
          <p className="muted">{body}</p>
          {action}
        </section>
      </main>
      <Footer organization={organization || 'Talent Assessment'} support={support} />
    </div>
  );
}

/** Entry point for /t/:token — loads the employee's invitation, then runs the test. */
export function CandidateApp({ token }: { token: string }) {
  const [invite, setInvite] = useState<InviteResponse | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      setInvite(await fetchInvite(token));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the assessment.');
    }
  }, [token]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <StatusScreen title="Can’t reach the server" body={`${error} Check your connection and try again.`} icon="x"
        organization="" action={<button className="btn btn-primary" onClick={() => void load()}>Try again</button>} />
    );
  }
  if (!invite) {
    return <StatusScreen title="Loading your assessment…" body="" icon="spinner" organization="" />;
  }
  const message = MESSAGES[invite.status];
  if (message || !invite.candidate || !invite.window) {
    const m = message ?? MESSAGES.invalid;
    return <StatusScreen {...m} organization={invite.organization} support={invite.support} />;
  }

  const info: CandidateInfo = {
    token,
    name: invite.candidate.name,
    email: invite.candidate.email,
    employeeCode: invite.candidate.employee_code,
    department: invite.candidate.department,
    organization: invite.organization,
    support: invite.support,
    window: { opens: new Date(invite.window.opens), closes: new Date(invite.window.closes) },
    durationMinutes: invite.duration_minutes ?? 45,
    serverStartedAt: invite.started_at ? Date.parse(invite.started_at) : null,
  };
  return (
    <CandidateContext.Provider value={info}>
      <AssessmentFlow />
    </CandidateContext.Provider>
  );
}
