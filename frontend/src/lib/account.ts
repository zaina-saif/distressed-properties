import { authJson } from "@/lib/api";

export type Plan = "none" | "trial" | "free" | "starter" | "pro";
export type BillingInterval = "month" | "year";
export type Role = "user" | "developer" | "file_uploader";

export interface Account {
  email: string;
  role: Role;
  plan: Plan;
  plan_status: "inactive" | "active" | "trialing" | "past_due" | "canceled";
  billing_interval: BillingInterval | null;
  coverage_state: string | null;
  coverage_county: string | null;
  current_period_end: string | null;
  has_access: boolean;
  is_developer: boolean;
  can_upload_files: boolean;
  has_billing: boolean;
  coverage_change_available_at: string | null;
  paid_plans_available: Plan[];
  trial_ends_at: string | null;
  trial_available: boolean;
}

export const TRIAL_DAYS = 7;

/** Whole days left in an active trial, counting a part day as a day. */
export function trialDaysLeft(account: Account | null): number | null {
  if (!account || account.plan !== "trial" || !account.trial_ends_at) return null;
  return Math.max(0, Math.ceil((new Date(account.trial_ends_at).getTime() - Date.now()) / 86_400_000));
}

export const getAccount = () => authJson<Account>("/api/v1/account/me");

const post = <T,>(path: string, body?: unknown) =>
  authJson<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const startTrial = () => post<{ plan: "trial"; trial_ends_at: string }>("/api/v1/account/trial");
export const startFreePlan = (state: string, county: string) => post("/api/v1/account/free-plan", { state, county });
export const changeCoverage = (state: string, county?: string) => post("/api/v1/account/coverage", { state, county });
export const startCheckout = (plan: "starter" | "pro", interval: BillingInterval, state?: string) =>
  post<{ url: string }>("/api/v1/billing/checkout", { plan, interval, state });
export const openBillingPortal = () => post<{ url: string }>("/api/v1/billing/portal");

/** An account as the developer's user management panel lists it (/api/v1/admin/users). */
export interface ManagedUser {
  user_id: string;
  email: string;
  name: string | null;
  role: Role;
  plan: Plan;
  plan_status: Account["plan_status"];
  coverage_state: string | null;
  coverage_county: string | null;
  trial_ends_at: string | null;
  has_subscription: boolean;
  access_level: string;
  created_at: string | null;
  last_sign_in_at: string | null;
}

export type AccessChange = { role?: Role; plan?: "none" | "free" | "starter" | "pro"; coverage_state?: string; coverage_county?: string };

export const listUsers = () => authJson<ManagedUser[]>("/api/v1/admin/users");
export const changeUserAccess = (userId: string, change: AccessChange) =>
  authJson<ManagedUser>(`/api/v1/admin/users/${userId}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change) });
