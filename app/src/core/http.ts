import { API_BASE_URL } from "./config";

/** The API answered, but not with what was asked for. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly path: string,
  ) {
    super(`${path} responded ${status}`);
    this.name = "ApiError";
  }
}

/**
 * GET a JSON resource from the API.
 *
 * Returns null on 404 so callers can distinguish "no such thing" — a normal outcome
 * worth rendering a message for — from a failure, which throws.
 */
export async function getJson<T>(path: string): Promise<T | null> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: { accept: "application/json" },
    cache: "no-store",
  });

  if (response.status === 404) return null;
  if (!response.ok) throw new ApiError(response.status, path);

  return (await response.json()) as T;
}
