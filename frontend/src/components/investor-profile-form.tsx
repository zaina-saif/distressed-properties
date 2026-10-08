"use client";

import { ArrowRight, Check } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { getProfile, type InvestorProfile, PROFILE_OPTIONS, saveProfile } from "@/lib/profile";
import { STATES } from "@/lib/states";

import styles from "./marketing-home.module.css";

const EMPTY: InvestorProfile = {
  budget_range: null, states: [], strategies: [], property_types: [], timeframe: null, financing: null,
  experience: null, min_equity: null, email_alerts: false, alert_frequency: null, notes: null,
};

type ListField = "states" | "strategies" | "property_types";
type ChoiceField = "budget_range" | "timeframe" | "financing" | "experience" | "min_equity";

/** Optional investor profile; every question can be skipped. */
export function InvestorProfileForm() {
  const router = useRouter();
  const { session, loading } = useAccount();
  const [profile, setProfile] = useState<InvestorProfile>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !session) router.replace(`/get-started?mode=login&next=${encodeURIComponent("/profile")}`);
  }, [loading, router, session]);
  useEffect(() => {
    if (!session) return;
    getProfile()
      .then((value) => setProfile({ ...EMPTY, ...value }))
      .catch(() => setError("We could not load your profile. You can still fill it in and save."))
      .finally(() => setLoaded(true));
  }, [session]);

  const update = (patch: Partial<InvestorProfile>) => { setProfile((current) => ({ ...current, ...patch })); setSaved(false); };
  const toggle = (field: ListField, value: string) =>
    update({ [field]: profile[field].includes(value) ? profile[field].filter((item) => item !== value) : [...profile[field], value] });
  const choose = (field: ChoiceField, value: string) => update({ [field]: profile[field] === value ? null : value });

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      setProfile({ ...EMPTY, ...(await saveProfile(profile)) });
      setSaved(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Your profile could not be saved. Try again.");
    } finally {
      setBusy(false);
    }
  }

  const chips = (field: ListField, options: readonly (readonly [string, string])[]) => (
    <div className="chip-group">{options.map(([value, label]) =>
      <button key={value} type="button" aria-pressed={profile[field].includes(value)}
        className={profile[field].includes(value) ? "chip is-selected" : "chip"} onClick={() => toggle(field, value)}>
        {profile[field].includes(value) && <Check size={13} aria-hidden="true"/>}{label}
      </button>)}</div>
  );
  const single = (field: ChoiceField, options: readonly (readonly [string, string])[]) => (
    <div className="chip-group" role="radiogroup">{options.map(([value, label]) =>
      <button key={value} type="button" role="radio" aria-checked={profile[field] === value}
        className={profile[field] === value ? "chip is-selected" : "chip"} onClick={() => choose(field, value)}>
        {profile[field] === value && <Check size={13} aria-hidden="true"/>}{label}
      </button>)}</div>
  );

  return <div className={styles.root}>
    <SiteHeader active="pricing"/>
    <main className="profile-page container">
      <span className="eyebrow">YOUR INVESTOR PROFILE</span>
      <h1>What are you looking for?</h1>
      <p className="profile-intro">Your profile helps us send you targeted investment opportunities that match your budget, markets and strategy. Every question is optional, and you can change your answers any time.</p>
      {!loaded && session ? <p className="account-muted">Loading your profile…</p> :
      <form className="profile-form" onSubmit={submit}>
        <fieldset><legend>Investment budget</legend><p className="field-help">The purchase price range you would consider.</p>{single("budget_range", PROFILE_OPTIONS.budget_range)}</fieldset>
        <fieldset><legend>States you are interested in</legend>
          {chips("states", STATES.map((state) => [state.code, state.name] as const))}</fieldset>
        <fieldset><legend>Investment strategy</legend><p className="field-help">Choose all that apply.</p>{chips("strategies", PROFILE_OPTIONS.strategies)}</fieldset>
        <fieldset><legend>Property types</legend><p className="field-help">Choose all that apply.</p>{chips("property_types", PROFILE_OPTIONS.property_types)}</fieldset>
        <fieldset><legend>When do you plan to buy?</legend>{single("timeframe", PROFILE_OPTIONS.timeframe)}</fieldset>
        <fieldset><legend>How would you pay?</legend>{single("financing", PROFILE_OPTIONS.financing)}</fieldset>
        <fieldset><legend>How many properties have you bought before?</legend>{single("experience", PROFILE_OPTIONS.experience)}</fieldset>
        <fieldset><legend>Minimum estimated equity</legend><p className="field-help">The smallest gap between estimated value and minimum bid that interests you.</p>{single("min_equity", PROFILE_OPTIONS.min_equity)}</fieldset>
        <fieldset><legend>Anything else?</legend>
          <textarea value={profile.notes ?? ""} maxLength={1000} rows={3} placeholder="For example: brick ranch homes near good schools, no condos"
            onChange={(event) => update({ notes: event.target.value })}/></fieldset>
        <fieldset className="alerts-box"><legend>Opportunity emails</legend>
          <label className="check-row"><input type="checkbox" checked={profile.email_alerts}
            onChange={(event) => update({ email_alerts: event.target.checked, alert_frequency: event.target.checked ? profile.alert_frequency ?? "weekly" : null })}/>
            <span>Email me investment opportunities that match my profile.</span></label>
          {profile.email_alerts && <div className="chip-group" role="radiogroup" aria-label="How often">
            {(["weekly", "daily"] as const).map((frequency) =>
              <button key={frequency} type="button" role="radio" aria-checked={profile.alert_frequency === frequency}
                className={profile.alert_frequency === frequency ? "chip is-selected" : "chip"} onClick={() => update({ alert_frequency: frequency })}>
                {frequency === "weekly" ? "Weekly summary" : "Daily"}</button>)}
          </div>}
          <p className="field-help">You can unsubscribe at any time from any email or from this page. We never sell your information.</p>
        </fieldset>
        {error && <p className="form-error" role="alert">{error}</p>}
        {saved && <p className="form-notice" role="status">Your profile is saved.</p>}
        <div className="choose-plan-actions">
          <button type="submit" className="site-button" disabled={busy}>{busy ? "Saving…" : "Save profile"}<ArrowRight/></button>
          <Link href="/dashboard" className="site-button button-outline">{saved ? "Go to the dashboard" : "Skip for now"}</Link>
        </div>
      </form>}
    </main>
    <SiteFooter/>
  </div>;
}
