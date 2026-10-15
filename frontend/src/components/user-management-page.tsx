"use client";

import { Pencil, Search, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAccount } from "@/components/account-provider";
import { SiteFooter, SiteHeader } from "@/components/marketing-chrome";
import { type AccessChange, type AccessChangeEntry, changeUserAccess, deleteUser, listAccessChanges, listUsers, type ManagedUser, type Role } from "@/lib/account";
import { STATES } from "@/lib/states";
import { getPropertyCoverage } from "@/services/properties";
import type { PropertyCoverageItem } from "@/types/property";

import styles from "./marketing-home.module.css";

type GrantedPlan = NonNullable<AccessChange["plan"]>;

const ROLES: { value: Role; label: string; hint: string }[] = [
  { value: "user", label: "User", hint: "Sale data as their plan allows" },
  { value: "developer", label: "Developer (admin)", hint: "Everything, including this panel and file storage" },
  { value: "file_uploader", label: "File uploader", hint: "File storage only; no sale data" },
];
const PLANS: { value: GrantedPlan; label: string }[] = [
  { value: "none", label: "No access" },
  { value: "free", label: "Free: one county" },
  { value: "starter", label: "Starter: one state" },
  { value: "pro", label: "Pro: full access" },
];
const day = (value: string | null) => value ? new Date(value).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—";
const FIELD_LABELS: Record<AccessChangeEntry["field"], string> = {
  role: "Role", plan: "Plan", plan_status: "Plan status", coverage_state: "State", coverage_county: "County", deleted: "Account",
};
const VALUE_LABELS: Record<string, string> = {
  user: "User", developer: "Developer (admin)", file_uploader: "File uploader",
  none: "No access", trial: "Trial", free: "Free", starter: "Starter", pro: "Pro",
  active: "active", inactive: "inactive", trialing: "trialing", past_due: "past due", canceled: "canceled",
};
const shownValue = (entry: AccessChangeEntry, value: string | null) =>
  value === null ? "none" : entry.field === "role" || entry.field === "plan" || entry.field === "plan_status" ? VALUE_LABELS[value] ?? value : value;
const moment = (value: string) => new Date(value).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });

/** One save from the panel writes a row per changed field at the same moment: shown as one entry.
 *  Plan status follows the plan, so it is left out when the plan changed too. */
function groupChanges(entries: AccessChangeEntry[]) {
  const groups: { key: string; first: AccessChangeEntry; fields: AccessChangeEntry[] }[] = [];
  for (const entry of entries) {
    const key = `${entry.user_id}|${entry.changed_at}`;
    const group = groups.find((item) => item.key === key);
    if (group) group.fields.push(entry);
    else groups.push({ key, first: entry, fields: [entry] });
  }
  for (const group of groups) {
    if (group.fields.some((entry) => entry.field === "plan")) group.fields = group.fields.filter((entry) => entry.field !== "plan_status");
  }
  return groups;
}

const levelClass = (user: ManagedUser) => user.role === "developer" ? "is-admin" : user.role === "file_uploader" ? "is-files"
  : user.access_level.startsWith("No access") ? "is-none" : "is-data";

function EditAccess({ user, self, counties, onSaved, onDeleted, onCancel }: {
  user: ManagedUser; self: boolean; counties: PropertyCoverageItem[];
  onSaved: (user: ManagedUser) => void; onDeleted: (user: ManagedUser) => void; onCancel: () => void;
}) {
  const [role, setRole] = useState<Role>(user.role);
  const [plan, setPlan] = useState<GrantedPlan>(user.plan === "trial" ? "none" : user.plan);
  const [state, setState] = useState(user.coverage_state ?? "");
  const [county, setCounty] = useState(user.coverage_county ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // A trial shows as "No access" in the picker; leaving it there keeps the trial.
  const keepsTrial = user.plan === "trial" && plan === "none";
  const planChanged = !keepsTrial && (plan !== user.plan || (plan !== "none" && plan !== "pro"
    && (state !== (user.coverage_state ?? "") || (plan === "free" && county !== (user.coverage_county ?? "")))));
  const stateCounties = counties.filter((item) => item.state === state && item.property_count > 0)
    .sort((a, b) => a.county.localeCompare(b.county));
  const missing = planChanged && ((plan === "starter" && !state) || (plan === "free" && (!state || !county)));

  // Your own account and other developers cannot be deleted (change the role first);
  // a paying Stripe subscriber is refused by the API until the subscription is canceled.
  const deletable = !self && user.role !== "developer";

  async function remove() {
    const who = user.name ? `${user.name} (${user.email})` : user.email;
    if (!window.confirm(`Delete ${who}? Their login, plan, investor profile, saved searches and watchlists are removed and cannot be restored. Files they uploaded are kept.`)) return;
    setBusy(true);
    setError(null);
    try {
      await deleteUser(user.user_id);
      onDeleted(user);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not delete the user.");
      setBusy(false);
    }
  }

  async function save() {
    const change: AccessChange = {};
    if (role !== user.role) change.role = role;
    if (planChanged) {
      change.plan = plan;
      if (plan === "starter" || plan === "free") change.coverage_state = state;
      if (plan === "free") change.coverage_county = county;
    }
    if (!Object.keys(change).length) return onCancel();
    setBusy(true);
    setError(null);
    try {
      onSaved(await changeUserAccess(user.user_id, change));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Could not save the change.");
    } finally {
      setBusy(false);
    }
  }

  return <div className="user-edit">
    <label>Role<select value={role} disabled={self} onChange={(event) => setRole(event.target.value as Role)}>
      {ROLES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
    </select><span className="account-muted">{self ? "You cannot change your own role." : ROLES.find((item) => item.value === role)?.hint}</span></label>
    {role === "user" && <>
      <label>Plan<select value={plan} onChange={(event) => { setPlan(event.target.value as GrantedPlan); setCounty(""); }}>
        {PLANS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>{keepsTrial && <span className="account-muted">On a trial until {day(user.trial_ends_at)}; leave as is to keep it.</span>}</label>
      {(plan === "starter" || plan === "free") && <label>State<select value={state} onChange={(event) => { setState(event.target.value); setCounty(""); }}>
        <option value="">Choose a state</option>{STATES.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
      </select></label>}
      {plan === "free" && <label>County<select value={county} disabled={!state} onChange={(event) => setCounty(event.target.value)}>
        <option value="">{state ? "Choose a county" : "Choose a state first"}</option>
        {stateCounties.map((item) => <option key={item.county} value={item.county}>{item.county}</option>)}
      </select></label>}
    </>}
    {user.has_subscription && role === "user" && planChanged && <p className="account-muted user-edit-note">
      This user pays through Stripe. Stripe sets their plan again the next time their subscription changes or renews.</p>}
    {error && <p className="form-error user-edit-note" role="alert">{error}</p>}
    <div className="user-edit-actions">
      <button type="button" className="site-button" disabled={busy || missing} onClick={save}>{busy ? "Saving…" : "Save"}</button>
      <button type="button" className="site-button button-ghost" disabled={busy} onClick={onCancel}>Cancel</button>
      {deletable && <button type="button" className="site-button button-ghost user-delete" disabled={busy} onClick={remove}><Trash2/>Delete user</button>}
    </div>
    {!deletable && !self && <p className="account-muted user-edit-note">To delete a developer, change their role first.</p>}
  </div>;
}

export function UserManagementPage() {
  const router = useRouter();
  const { session, account, loading } = useAccount();
  const [users, setUsers] = useState<ManagedUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<PropertyCoverageItem[]>([]);
  const [changes, setChanges] = useState<AccessChangeEntry[] | null>(null);
  const [changesError, setChangesError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !session) router.replace(`/get-started?mode=login&next=${encodeURIComponent("/admin/users")}`);
  }, [loading, router, session]);

  const load = useCallback(() => listUsers().then(setUsers)
    .catch((failure) => setError(failure instanceof Error ? failure.message : "Could not load users.")), []);
  const loadChanges = useCallback(() => listAccessChanges().then((rows) => { setChanges(rows); setChangesError(null); })
    .catch((failure) => setChangesError(failure instanceof Error ? failure.message : "Could not load the change log.")), []);
  useEffect(() => {
    if (!account?.is_developer) return;
    load();
    loadChanges();
    getPropertyCoverage("scheduled").then(setCoverage).catch(() => setCoverage([]));
  }, [account, load, loadChanges]);
  const changeGroups = useMemo(() => groupChanges(changes ?? []), [changes]);

  const shown = useMemo(() => {
    const term = query.trim().toLowerCase();
    return (users ?? []).filter((user) => !term || [user.email, user.name ?? "", user.access_level].some((value) => value.toLowerCase().includes(term)));
  }, [query, users]);
  const counts = useMemo(() => {
    const all = users ?? [];
    return [
      { label: "Users", value: all.length },
      { label: "With sale data", value: all.filter((user) => levelClass(user) === "is-data").length },
      { label: "No access", value: all.filter((user) => levelClass(user) === "is-none").length },
      { label: "Developers / uploaders", value: all.filter((user) => user.role !== "user").length },
    ];
  }, [users]);

  function deleted(user: ManagedUser) {
    setUsers((current) => current?.filter((item) => item.user_id !== user.user_id) ?? null);
    setEditing(null);
    setNotice(`${user.name ?? user.email} was deleted.`);
    loadChanges();
  }

  function saved(user: ManagedUser) {
    setUsers((current) => current?.map((item) => item.user_id === user.user_id ? user : item) ?? null);
    setEditing(null);
    setNotice(`${user.name ?? user.email}: ${user.access_level}.`);
    loadChanges();
  }

  return <div className={styles.root}>
    <SiteHeader active="none"/>
    <main className="account-page user-admin container">
      <span className="eyebrow">DEVELOPER</span>
      <h1>Users</h1>
      {!account ? <p className="account-muted">{loading ? "Loading…" : "We could not load your account. Try again shortly."}</p>
        : !account.is_developer ? <p className="account-muted">User management is only available to developers.</p> : <>
          <dl className="account-facts user-counts">{counts.map((item) => <div key={item.label}><dt>{item.label}</dt><dd>{users ? item.value : "…"}</dd></div>)}</dl>
          <label className="user-search"><Search aria-hidden/>
            <input type="search" placeholder="Search by name, email or access" value={query} onChange={(event) => setQuery(event.target.value)}/>
          </label>
          {notice && <p className="form-notice" role="status">{notice}</p>}
          {error && <p className="form-error" role="alert">{error}</p>}
          {!users ? <p className="account-muted">Loading…</p> : !shown.length ? <p className="account-muted">No users match.</p>
            : <ul className="user-list">{shown.map((user) => <li key={user.user_id}>
              <div className="user-main">
                <div className="user-who">
                  <span className="user-name">{user.name ?? user.email}{user.email === account.email ? " (you)" : ""}</span>
                  {user.name && <span className="account-muted">{user.email}</span>}
                </div>
                <span className={`user-level ${levelClass(user)}`}>{user.access_level}</span>
                <span className="account-muted user-dates">Joined {day(user.created_at)} · Last sign-in {day(user.last_sign_in_at)}</span>
                {editing === user.user_id
                  ? <button type="button" className="site-button button-ghost user-edit-toggle" aria-label="Close" onClick={() => setEditing(null)}><X/></button>
                  : <button type="button" className="site-button button-outline user-edit-toggle" onClick={() => { setNotice(null); setEditing(user.user_id); }}><Pencil/>Edit</button>}
              </div>
              {editing === user.user_id && <EditAccess user={user} self={user.email === account.email} counties={coverage}
                onSaved={saved} onDeleted={deleted} onCancel={() => setEditing(null)}/>}
            </li>)}</ul>}
          <div className="file-list-head">
            <h2>Change log</h2>
            {changes && changeGroups.length > 0 && <span className="account-muted">{changeGroups.length} change{changeGroups.length === 1 ? "" : "s"}</span>}
          </div>
          {changesError ? <p className="form-error" role="alert">{changesError}</p>
            : !changes ? <p className="account-muted">Loading…</p>
            : !changeGroups.length ? <p className="account-muted">No changes yet. Role and plan changes made here are listed with who made them and when.</p>
            : <ul className="change-log">{changeGroups.map((group) => {
              const target = users?.find((item) => item.user_id === group.first.user_id);
              const editor = group.first.changed_by_email === account.email ? "You" : group.first.changed_by_email ?? "A developer";
              return <li key={group.key}>
                <div className="change-log-head">
                  <span className="user-name">{target?.name ?? group.first.user_email
                    ?? group.fields.find((entry) => entry.field === "deleted")?.old_value ?? "Deleted user"}</span>
                  <span className="account-muted">{moment(group.first.changed_at)} · by {editor}</span>
                </div>
                <ul className="change-log-fields">{group.fields.map((entry) => entry.field === "deleted" ? <li key={entry.id}>
                  <span className="change-field">Account</span><span className="change-new change-deleted">Deleted</span>
                </li> : <li key={entry.id}>
                  <span className="change-field">{FIELD_LABELS[entry.field] ?? entry.field}</span>
                  <span className="change-old">{shownValue(entry, entry.old_value)}</span>
                  <span aria-hidden>→</span><span className="sr-only">changed to</span>
                  <span className="change-new">{shownValue(entry, entry.new_value)}</span>
                </li>)}</ul>
              </li>;
            })}</ul>}
        </>}
    </main>
    <SiteFooter/>
  </div>;
}
