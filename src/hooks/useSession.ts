import { useEffect, useReducer, useState } from 'react';
import { test } from '../data/test';
import type { Stage } from '../types';

export interface SessionState {
  stage: Stage;
  docsConfirmed: string[];
  systemCheckPassed: boolean;
  inputCheckPassed: boolean;
  /** questionId -> selected option index */
  answers: Record<number, number>;
  revisit: number[];
  currentIndex: number;
  startedAt: number | null;
  submittedAt: number | null;
  submitReason: 'manual' | 'timeout' | null;
}

export type SessionAction =
  | { type: 'toggleDoc'; id: string }
  | { type: 'goTo'; stage: Stage }
  | { type: 'systemCheckPassed' }
  | { type: 'inputCheckPassed' }
  | { type: 'startTest' }
  | { type: 'answer'; questionId: number; option: number }
  | { type: 'clearAnswer'; questionId: number }
  | { type: 'toggleRevisit'; questionId: number }
  | { type: 'setIndex'; index: number }
  | { type: 'submit'; reason: 'manual' | 'timeout' }
  | { type: 'reset' };

const STORAGE_KEY = `psychometric:${test.testId}:session`;

const initialState: SessionState = {
  stage: 'registration',
  docsConfirmed: [],
  systemCheckPassed: false,
  inputCheckPassed: false,
  answers: {},
  revisit: [],
  currentIndex: 0,
  startedAt: null,
  submittedAt: null,
  submitReason: null,
};

function reducer(state: SessionState, action: SessionAction): SessionState {
  switch (action.type) {
    case 'toggleDoc': {
      const has = state.docsConfirmed.includes(action.id);
      return {
        ...state,
        docsConfirmed: has
          ? state.docsConfirmed.filter((d) => d !== action.id)
          : [...state.docsConfirmed, action.id],
      };
    }
    case 'goTo':
      return { ...state, stage: action.stage };
    case 'systemCheckPassed':
      return { ...state, systemCheckPassed: true };
    case 'inputCheckPassed':
      return { ...state, inputCheckPassed: true };
    case 'startTest':
      return { ...state, stage: 'test', startedAt: state.startedAt ?? Date.now() };
    case 'answer':
      return { ...state, answers: { ...state.answers, [action.questionId]: action.option } };
    case 'clearAnswer': {
      const answers = { ...state.answers };
      delete answers[action.questionId];
      return { ...state, answers };
    }
    case 'toggleRevisit': {
      const has = state.revisit.includes(action.questionId);
      return {
        ...state,
        revisit: has
          ? state.revisit.filter((id) => id !== action.questionId)
          : [...state.revisit, action.questionId],
      };
    }
    case 'setIndex':
      return { ...state, currentIndex: action.index };
    case 'submit':
      if (state.stage !== 'test') return state;
      return { ...state, stage: 'completed', submittedAt: Date.now(), submitReason: action.reason };
    case 'reset':
      return initialState;
  }
}

function load(): SessionState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...initialState, ...JSON.parse(raw) };
  } catch {
    // Storage unavailable or corrupt: start fresh.
  }
  return initialState;
}

/**
 * Candidate session state, auto-saved to localStorage on every change so a
 * refresh resumes where the candidate left off (timer included).
 */
export function useSession() {
  const [state, dispatch] = useReducer(reducer, undefined, load);
  const [lastSavedAt, setLastSavedAt] = useState(() => Date.now());

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      setLastSavedAt(Date.now());
    } catch {
      // Quota exceeded or storage blocked; state still lives in memory.
    }
  }, [state]);

  return { state, dispatch, lastSavedAt };
}

/** Re-renders every `intervalMs` and returns the current time. */
export function useNow(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
