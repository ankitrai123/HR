import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';
import { AdminApp } from './admin/AdminApp';
import { CandidateApp, StatusScreen } from './candidate/CandidateApp';
import { usePathname } from './router';

function Root() {
  const path = usePathname();
  if (path === '/admin' || path.startsWith('/admin/')) return <AdminApp />;
  const link = path.match(/^\/t\/([^/]+)\/?$/);
  if (link) return <CandidateApp token={decodeURIComponent(link[1])} />;
  return (
    <StatusScreen
      title="Personality assessment"
      body="Employees: please open the personal link you received from HR to start your assessment."
      icon="check"
      organization=""
      action={<a className="btn btn-outline" href="/admin">Admin sign-in</a>}
    />
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);
