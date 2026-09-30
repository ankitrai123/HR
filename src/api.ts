/** Base URL of the backend. Empty = same origin (the backend serves this app). */
export const API_BASE: string = (import.meta.env.VITE_ASSESSMENT_API_URL ?? '').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(message);
  }
}

export async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown = null;
  try {
    detail = (await res.json()).detail;
  } catch {
    // non-JSON error body
  }
  const message =
    typeof detail === 'string'
      ? detail
      : detail && typeof detail === 'object' && 'message' in detail
        ? String((detail as { message: unknown }).message)
        : `Request failed (${res.status})`;
  return new ApiError(message, res.status, detail);
}
