import { supabase } from "@/lib/supabase";

// A trailing slash in the setting would turn every path into "//api/...", which the API rejects.
export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

/** fetch() for API routes that need the signed-in user's access token. */
export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const { data } = await supabase().auth.getSession();
  const headers = new Headers(init.headers);
  if (data.session) headers.set("Authorization", `Bearer ${data.session.access_token}`);
  return fetch(input, { cache: "no-store", ...init, headers });
}

/** JSON from an authenticated API route; throws with the API's message on failure. */
export async function authJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await authFetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    const detail = await response.json().then((body) => body?.detail).catch(() => null);
    throw new ApiError(response.status, typeof detail === "string" ? detail : `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}
