"use client";

import type { Session } from "@supabase/supabase-js";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

import { type Account, getAccount } from "@/lib/account";
import { supabase } from "@/lib/supabase";

type AccountState = {
  session: Session | null;
  account: Account | null;
  loading: boolean;
  refresh: () => Promise<Account | null>;
  signOut: () => Promise<void>;
};

const AccountContext = createContext<AccountState | null>(null);

async function loadAccount(): Promise<{ session: Session | null; account: Account | null }> {
  try {
    const { data } = await supabase().auth.getSession();
    return { session: data.session, account: data.session ? await getAccount().catch(() => null) : null };
  } catch {
    // Sign-in is not configured (missing Supabase settings): everyone is signed out.
    return { session: null, account: null };
  }
}

/** The Supabase session and the API's view of the account (plan, coverage, role). */
export function AccountProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);

  const apply = useCallback((next: { session: Session | null; account: Account | null }) => {
    setSession(next.session);
    setAccount(next.account);
    setLoading(false);
    return next.account;
  }, []);

  const refresh = useCallback(() => loadAccount().then(apply), [apply]);

  useEffect(() => {
    let active = true;
    loadAccount().then((next) => { if (active) apply(next); });
    let unsubscribe = () => {};
    try {
      const { data } = supabase().auth.onAuthStateChange((event) => {
        if (event === "SIGNED_IN" || event === "SIGNED_OUT" || event === "USER_UPDATED") {
          loadAccount().then((next) => { if (active) apply(next); });
        }
      });
      unsubscribe = () => data.subscription.unsubscribe();
    } catch {
      // Sign-in is not configured; loadAccount() already reports a signed-out user.
    }
    return () => { active = false; unsubscribe(); };
  }, [apply]);

  const signOut = useCallback(async () => {
    await supabase().auth.signOut();
    setSession(null);
    setAccount(null);
  }, []);

  return <AccountContext.Provider value={{ session, account, loading, refresh, signOut }}>{children}</AccountContext.Provider>;
}

export function useAccount(): AccountState {
  const value = useContext(AccountContext);
  if (!value) throw new Error("useAccount must be used inside AccountProvider");
  return value;
}

/**
 * Shows its children only to a signed-in user with an active plan. Others are sent to
 * sign in or to choose a plan. The API enforces the same rules; this only spares the
 * user a page of failed requests.
 */
export function RequireAccess({ next, children }: { next: string; children: React.ReactNode }) {
  const { session, account, loading } = useAccount();
  const router = useRouter();
  const allowed = Boolean(session && account?.has_access);
  useEffect(() => {
    if (loading) return;
    if (!session) router.replace(`/get-started?mode=login&next=${encodeURIComponent(next)}`);
    else if (!account?.has_access) router.replace("/choose-plan");
  }, [account, loading, next, router, session]);
  if (!allowed) {
    return <div className="flex h-screen items-center justify-center bg-slate-100 text-sm text-slate-500">Checking your access…</div>;
  }
  return <>{children}</>;
}
