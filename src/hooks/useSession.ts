import { useEffect, useReducer, useRef, useState } from 'react';
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
  /** True once the backend has confirmed it received the submission. */
  serverReceived: boolean;
}

export type SessionAction =
  | { type: 'toggleDoc'; id: string }
  | { type: 'goTo'; stage: Stage }
  | { type: 'systemCheckPassed' }
  | { type: 'inputCheckPassed' }
  | { type: 'startTest'; startedAt: number }
  | { type: 'syncStartedAt'; startedAt: number }
  | { type: 'answer'; questionId: number; option: number }
  | { type: 'clearAnswer'; questionId: number }
  | { type: 'toggleRevisit'; questionId: number }
  | { type: 'setIndex'; index: number }
  | { type: 'submit'; reason: 'manual' | 'timeout' }
  | { type: 'serverAccepted' }
  | { type: 'reset' };

const storageKey = (token: string) => `psychometric:${test.testId}:${token}`;

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
  serverReceived: false,
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
      return { ...state, stage: 'test', startedAt: action.startedAt };
    case 'syncStartedAt':
      return { ...state, startedAt: action.startedAt };
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
    case 'serverAccepted':
      return { ...state, serverReceived: true };
    case 'reset':
      return initialState;
  }
}

function load(token: string): SessionState {
  try {
    const raw = localStorage.getItem(storageKey(token));
    if (raw) return { ...initialState, ...JSON.parse(raw) };
  } catch {
    // Storage unavailable or corrupt: start fresh.
  }
  return initialState;
}

/**
 * Candidate session state for one personal link, auto-saved to localStorage
 * on every change so a refresh resumes where the candidate left off.
 */
export function useSession(token: string) {
  const [state, dispatch] = useReducer(reducer, token, load);
  // A ref, not state: a setState here would force an extra synchronous render
  // on every key press, which trips React's nested-update limit when
  // answering quickly. The test page re-renders each second for its timer,
  // so "Saved: N seconds ago" stays current.
  const lastSavedAt = useRef(Date.now());

  useEffect(() => {
    try {
      localStorage.setItem(storageKey(token), JSON.stringify(state));
      lastSavedAt.current = Date.now();
    } catch {
      // Quota exceeded or storage blocked; state still lives in memory.
    }
  }, [state, token]);

  return { state, dispatch, lastSavedAt: lastSavedAt.current };
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
