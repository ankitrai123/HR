export interface Question {
  id: number;
  questionText: string;
  options: string[];
  /** Optional scoring dimension, used later by analysis scripts. */
  trait?: string;
}

export interface Section {
  sectionId: string;
  sectionTitle: string;
  questions: Question[];
}

export interface TestDefinition {
  testId: string;
  title: string;
  durationMinutes: number;
  sections: Section[];
}

/** A question flattened out of its section, with its 1-based display number. */
export interface FlatQuestion extends Question {
  number: number;
  sectionIndex: number;
}

export type Stage = 'registration' | 'verification' | 'test' | 'completed';

export interface RequiredDocument {
  id: string;
  label: string;
  detail: string;
  optional?: boolean;
}

export interface CandidateProfile {
  name: string;
  email: string;
  candidateId: string;
  role: string;
  organization: string;
}
