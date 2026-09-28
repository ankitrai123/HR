import type { CandidateProfile, RequiredDocument } from '../types';

// Placeholder data. Replace with values from your candidate/ATS backend.

export const candidate: CandidateProfile = {
  name: 'Prateek Kumar',
  email: 'candidate@example.com',
  candidateId: 'CND-2026-00457',
  role: 'Senior Software Engineer',
  organization: 'Acme Corporation',
};

const DAY = 24 * 60 * 60 * 1000;
const today = new Date();
today.setHours(9, 0, 0, 0);

/** Registration window. Demo default: opened today 09:00, closes in 7 days. */
export const registrationWindow = {
  opens: new Date(today.getTime() - DAY),
  closes: new Date(today.getTime() + 7 * DAY),
};

export const offerOverview = [
  { label: 'Position', value: 'Senior Software Engineer' },
  { label: 'Location', value: 'Bengaluru (Hybrid)' },
  { label: 'Employment type', value: 'Full-time, permanent' },
  { label: 'Compensation', value: 'Shared after assessment review' },
];

export const guidelines = [
  'The assessment is a personality inventory. There are no right or wrong answers — respond honestly.',
  'Use a desktop or laptop with a stable internet connection and an up-to-date browser.',
  'Once started, the timer cannot be paused. Responses are saved automatically.',
  'Do not refresh repeatedly or switch devices during the test.',
  'Keep the documents below ready; they are verified before the offer stage.',
];

export const requiredDocuments: RequiredDocument[] = [
  { id: 'pan', label: 'PAN Card', detail: 'Self-attested copy' },
  { id: 'certificates', label: 'Educational Certificates', detail: '10th, 12th, graduation and post-graduation' },
  { id: 'experience', label: 'Work Experience Letters', detail: 'From all previous employers' },
  { id: 'payslips', label: 'Pay Slips', detail: 'Last 3 months from current employer' },
  { id: 'relieving', label: 'Relieving Letter', detail: 'From your most recent employer' },
  { id: 'passport', label: 'Passport', detail: 'If available', optional: true },
];

export const support = {
  email: 'support@example.com',
  phone: '+91 80 0000 0000',
};
