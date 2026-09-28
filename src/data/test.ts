import type { FlatQuestion, TestDefinition } from '../types';
import raw from './test.json';

export const test: TestDefinition = raw;

export const questions: FlatQuestion[] = test.sections.flatMap((section, sectionIndex) =>
  section.questions.map((q) => ({ ...q, sectionIndex, number: 0 })),
).map((q, i) => ({ ...q, number: i + 1 }));

/** Index of the first question in each section. */
export const sectionStarts: number[] = test.sections.map((_, s) =>
  questions.findIndex((q) => q.sectionIndex === s),
);
