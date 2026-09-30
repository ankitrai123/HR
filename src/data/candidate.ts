import type { RequiredDocument } from '../types';

// Platform-wide content shown to every employee. Per-person details come
// from their personal link (see candidate/CandidateContext.tsx).

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

