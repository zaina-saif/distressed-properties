import { authJson } from "@/lib/api";

export type Plan = "none" | "trial" | "free" | "starter" | "pro";
export type BillingInterval = "month" | "year";

export interface Account {
  email: string;
  role: "user" | "developer";
  plan: Plan;
  plan_status: "inactive" | "active" | "trialing" | "past_due" | "canceled";
  billing_interval: BillingInterval | null;
  coverage_state: string | null;
  coverage_county: string | null;
  current_period_end: string | null;
  has_access: boolean;
  is_developer: boolean;
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
