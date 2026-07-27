/**
 * Where the API lives.
 *
 * Server components call it directly; the browser needs the same URL, so it is a
 * NEXT_PUBLIC_ variable rather than a server-only one.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
