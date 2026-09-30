import { createContext, useContext } from 'react';

export interface Support {
  email: string;
  phone: string;
}

/** The employee's details, loaded from their personal link. */
export interface CandidateInfo {
  token: string;
  name: string;
  email: string | null;
  employeeCode: string;
  department: string | null;
  organization: string;
  support: Support;
  window: { opens: Date; closes: Date };
  durationMinutes: number;
  /** When the server recorded the start (ms), if the test was started on any device. */
  serverStartedAt: number | null;
}

export const CandidateContext = createContext<CandidateInfo | null>(null);

export function useCandidate(): CandidateInfo {
  const value = useContext(CandidateContext);
  if (!value) throw new Error('useCandidate must be used inside a CandidateContext provider');
  return value;
}
