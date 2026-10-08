import { authJson } from "@/lib/api";

/** Answer options; the API accepts the same values (backend/app/api/investor_profile.py). */
export const PROFILE_OPTIONS = {
  budget_range: [
    ["under_100k", "Under $100K"], ["100k_250k", "$100K – $250K"], ["250k_500k", "$250K – $500K"],
    ["500k_1m", "$500K – $1M"], ["over_1m", "Over $1M"],
  ],
  strategies: [
    ["fix_and_flip", "Fix & flip"], ["buy_and_hold", "Buy & hold rental"], ["wholesale", "Wholesale"],
    ["owner_occupant", "Home to live in"], ["land_development", "Land or development"],
  ],
  property_types: [
    ["single_family", "Single-family"], ["multi_2_4", "2–4 units"], ["condo_townhouse", "Condo or townhouse"],
    ["multi_5_plus", "5+ units"], ["commercial", "Commercial"], ["land", "Land"],
  ],
  timeframe: [
    ["now", "Ready now"], ["within_3_months", "Within 3 months"], ["3_6_months", "3–6 months"],
    ["6_12_months", "6–12 months"], ["exploring", "Just exploring"],
  ],
  financing: [["cash", "Cash"], ["hard_money", "Hard money or private"], ["conventional", "Conventional mortgage"], ["not_sure", "Not sure yet"]],
  experience: [["first_purchase", "This would be my first"], ["1_5", "1–5 properties"], ["6_20", "6–20 properties"], ["20_plus", "20+ properties"]],
  min_equity: [["any", "Any"], ["25k", "$25K+"], ["50k", "$50K+"], ["100k", "$100K+"]],
} as const satisfies Record<string, readonly (readonly [string, string])[]>;

export interface InvestorProfile {
  exists?: boolean;
  budget_range: string | null;
  states: string[];
  strategies: string[];
  property_types: string[];
  timeframe: string | null;
  financing: string | null;
  experience: string | null;
  min_equity: string | null;
  email_alerts: boolean;
  alert_frequency: "daily" | "weekly" | null;
  notes: string | null;
}

export const getProfile = () => authJson<InvestorProfile>("/api/v1/account/profile");

export const saveProfile = (profile: InvestorProfile) =>
  authJson<InvestorProfile>("/api/v1/account/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
  });
