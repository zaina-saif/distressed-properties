export interface Property {
  property_id: string;
  sheriff_sale_id: string;
  sheriff_number: string;
  court_case_number?: string | null;
  plaintiff?: string | null;
  defendant?: string | null;
  foreclosure_source_url?: string | null;

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
  coordinate_source?: "canonical_parcel" | "nj_avm_parcel" | null;

  current_status: string;
  current_sale_date: string | null;

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
  upset_price?: number | null;
  gross_equity?: number | null;
  gross_equity_percent?: number | null;

  sale_probability?: number | null;
  sale_probability_features?: {
    confidence?: number;
    plaintiff_adjournments?: number;
    defendant_adjournments?: number;
    generic_adjournments?: number;
    bankruptcy_events?: number;
    methodology?: string;
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

export interface PropertyResponse {
  items: Property[];
  page: number;
  page_size: number;
  total: number;
}

export interface PropertyCoverageItem {
  state: string;
  county: string;
  property_count: number;
}
