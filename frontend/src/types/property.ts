export interface Property {
  property_id: string;
  sheriff_sale_id: string;
  sheriff_number: string;
  sale_type?: string;
  court_case_number?: string | null;
  bbl?: string | null;
  notice_details?: string | null;
  plaintiff?: string | null;
  defendant?: string | null;
  foreclosure_source_url?: string | null;
  apify_data?: Record<string, unknown> | null;

  normalized_address: string;
  street_address: string;
  city: string;
  county: string;
  state: string;
  zip_code: string | null;
  property_type?: string | null;
  bedrooms?: number | null;
  bathrooms?: number | null;
  square_feet?: number | null;
  acreage?: number | null;
  year_built?: number | null;
  pams_pin?: string | null;
  block?: string | null;
  lot?: string | null;
  qualifier?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  coordinate_source?: "canonical_parcel" | "nj_avm_parcel" | "nyc_planning_geosearch" | null;

  current_status: string;
  current_sale_date: string | null;
  status_history?: SheriffStatusHistoryItem[];

  market_value?: number | null;
  market_value_low?: number | null;
  market_value_high?: number | null;
  valuation_provider?: string | null;
  valuation_confidence?: number | null;
  valuation_retrieved_at?: string | null;
  valuation_status?:
    | "VALUED"
    | "COUNTY_MODEL_UNAVAILABLE"
    | "PARCEL_MATCH_UNDER_REVIEW"
    | "PARCEL_MATCH_REQUIRED"
    | "MANUAL_REVIEW_REQUIRED"
    | "PROPERTY_TYPE_MODEL_UNAVAILABLE"
    | "LIVING_AREA_MISSING"
    | "MODEL_SCORING_REQUIRED";
  valuation_pending_reason?: string | null;
  parcel_match_confidence?: number | null;
  judgment_amount?: number | null;
  judgment_amount_as_of_date?: string | null;
  judgment_source_url?: string | null;
  starting_bid?: number | null;
  distress_start_date?: string | null;
  distress_start_year?: number | null;
  distress_start_basis?: string | null;
  distress_duration_days?: number | null;
  distress_duration_min_days?: number | null;
  distress_duration_max_days?: number | null;
  notice_lien_amount?: number | null;
  avm_judgment_spread?: number | null;
  avm_judgment_spread_percent?: number | null;
  upset_price?: number | null;
  opening_bid?: number | null;
  zestimate?: number | null;
  minimum_asking_amount?: number | null;
  minimum_bid_basis?: "approx_upset" | "judgment" | "notice_estimate" | null;
  gross_equity?: number | null;
  gross_equity_percent?: number | null;
  expected_equity?: number | null;

  sale_probability?: number | null;
  sale_probability_features?: {
    state?: string;
    county?: string;
    prior_event_count?: number;
    prior_scheduled_count?: number;
    adjournment_count?: number;
    plaintiff_adjournment_count?: number;
    defendant_adjournment_count?: number;
    court_adjournment_count?: number;
    bankruptcy_count?: number;
    distinct_status_count?: number;
    days_in_process?: number;
    days_since_previous_event?: number;
    days_until_sale?: number;
    sale_month?: number;
    minimum_bid?: number;
    has_upset_price?: number;
    confidence?: number;
    plaintiff_adjournments?: number;
    defendant_adjournments?: number;
    generic_adjournments?: number;
    bankruptcy_events?: number;
    methodology?: string;
  } | null;
  sale_probability_explanations?: {
    methodology?: string;
    target?: string;
    model_version?: string;
    drivers?: Array<{ key: string; label: string; value: string; typical: string; impact: number }>;
    drivers_method?: string;
    /** No past results from this state; the estimate averages the trained states. */
    state_without_history?: boolean;
    trained_states?: string[];
    model_quality?: {
      holdout_rows?: number;
      holdout_roc_auc?: number;
      holdout_brier_score?: number;
      holdout_mean_prediction?: number;
      holdout_positive_rate?: number;
      holdout_cutoff?: string;
    };
  } | null;
  risk_score?: number | null;
  risk_level?: string | null;
  lien_risk_score?: number | null;
  lien_risk_level?: string | null;
  lien_risk_confidence?: number | null;
  known_lien_exposure?: number | null;
  total_lien_amount?: number | null;
  lien_risk_calculated_at?: string | null;
  lien_record_count?: number;
  open_lien_count?: number;
  potentially_surviving_lien_count?: number;
  lien_manual_review_count?: number;
  lien_items?: LienSummaryItem[];
}

export interface SheriffStatusHistoryItem {
  status: string;
  raw_status?: string | null;
  event_date?: string | null;
  observed_at: string;
  sale_date?: string | null;
  upset_price?: number | null;
}

export interface LienSummaryItem {
  id: string;
  holder: string;
  amount: number | null;
  type: string;
  subtype: string | null;
  status: string;
  position:
    | "PRIMARY_FORECLOSING"
    | "POTENTIALLY_SENIOR"
    | "SECONDARY_JUNIOR"
    | "PRIORITY_UNKNOWN";
  position_confidence: number;
}

export interface LienCoverageItem {
  category: string;
  source_name: string;
  status:
    | "RECORDS_FOUND"
    | "CHECKED_NO_MATCH"
    | "POSSIBLE_MATCH"
    | "PARTIAL"
    | "MANUAL_REVIEW_REQUIRED"
    | "NOT_CHECKED"
    | "SOURCE_UNAVAILABLE";
  record_count: number;
  quantified_amount: number | null;
  source_url: string | null;
  message: string | null;
  checked_at: string | null;
  source_effective_at: string | null;
}

export interface LienItem {
  id: string;
  lien_type: string;
  lien_subtype: string | null;
  status: string;
  creditor_name: string | null;
  debtor_name: string | null;
  original_amount: number | null;
  current_amount: number | null;
  recording_date: string | null;
  instrument_number: string | null;
  match_confidence: number;
  match_reason: string;
  requires_manual_review: boolean;
  source_name: string;
  source_url: string | null;
  retrieved_at: string | null;
  ingestion_status?: string | null;
}

export interface LienEnrichment {
  property_id: string;
  status: string;
  primary_lender: string | null;
  municipal_violations_count: number | null;
  estimated_municipal_debt_usd: number | null;
  outstanding_taxes_usd: number | null;
  tax_delinquency_status: string | null;
  source_statuses: Record<string, string>;
  source_urls: string[];
  error_message: string | null;
  retrieved_at: string | null;
  updated_at: string | null;
}

export type PublicComplaint = Record<string, unknown>;

export interface LienSummaryCoverage {
  source_name: string;
  source_type: string;
  status: string;
  checked_at: string | null;
  source_url: string | null;
  records_found: number;
  message: string | null;
}

export interface LienSummaryResponse {
  property_id: string;
  summary: {
    risk_level: string;
    confidence: number;
    headline: string;
    summary_text: string;
    key_findings: Array<{ finding_id: string; type: string; severity: string; label: string; message: string; evidence_ids: string[]; confidence: number }>;
    coverage_summary: { checked_sources: number; unavailable_sources: number; manual_review_sources: number; total_sources: number };
    coverage: LienSummaryCoverage[];
    manual_review: Array<Record<string, unknown>>;
    data_freshness: string;
    calculated_at: string;
    disclaimer: string;
  };
  risk: { risk_score: number; risk_level: string; confidence_score: number; known_exposure: number; components: Record<string, number> };
  liens: LienItem[];
  enrichment: LienEnrichment | null;
  professional_title_search: ProfessionalTitleSearch;
}

export interface ProfessionalTitleSearch {
  provider_name: string;
  provider_url: string;
  relationship: "independent_third_party";
}

export interface SpotlightSummary {
  count: number;
  total_gross_equity: number | null;
  average_gross_equity: number | null;
  average_expected_equity: number | null;
  average_probability: number | null;
}

export interface PropertyResponse {
  items: Property[];
  page: number;
  page_size: number;
  total: number;
  /** Earliest sale date from today on across every match (YYYY-MM-DD), or null. */
  next_sale_date?: string | null;
  spotlight_summary?: SpotlightSummary;
}

export interface PropertyCoverageItem {
  state: string;
  county: string;
  property_count: number;
}
