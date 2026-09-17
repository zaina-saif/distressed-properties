export interface WarehouseCoverageYear {
  year: number;
  sales: number;
  sale_counties: number;
  snapshots: number;
  snapshot_counties: number;
  first_sale: string | null;
  last_sale: string | null;
}

export interface WarehouseModelRun {
  status: string;
  model_version: string;
  data_as_of: string | null;
  trained_at: string | null;
  row_counts: Record<string, number>;
  metrics: {
    feature_weightages?: Record<string, number>;
    test?: {
      xgboost?: { mae?: number; within_20_percent?: number; r2?: number };
      prior_county_median?: { mae?: number };
    };
  };
}

export interface WarehouseCoverage {
  state: string;
  as_of: string;
  refreshed_at: string | null;
  years: WarehouseCoverageYear[];
  total_sales: number;
  total_snapshots: number;
  latest_sale: string | null;
  future_dated_sales: number;
  model: WarehouseModelRun | null;
  coverage_note: string;
}

export interface WarehouseProperty {
  source_id: string;
  state: string;
  county: string;
  source_parcel_id: string;
  snapshot_year: number;
  street_address: string | null;
  house_number_unavailable: boolean;
  address_source_id?: string;
  address_snapshot_year?: number;
  longitude: number | null;
  latitude: number | null;
  city: string | null;
  zip_code: string | null;
  property_type: string | null;
  year_built: number | null;
  living_area: number | null;
  land_area: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  feature_source_id?: string;
  feature_snapshot_year?: number;
  rooms: number | null;
  total_assessed_value: number | null;
  school_district_name: string | null;
  last_sale_date: string | null;
  last_sale_price: number | null;
  estimated_price: number | null;
  estimate_status: string;
  model_version: string | null;
}

export interface WarehouseCursor {
  parcel: string;
  source: string;
}

export interface WarehousePropertyPage {
  items: WarehouseProperty[];
  next_cursor: WarehouseCursor | null;
  state: string;
  county: string;
  year: number;
  note: string;
}

export interface WarehouseMonthlyCoverage {
  state: string;
  county: string;
  year: number;
  months: { month: number; sales: number; first_sale: string | null; last_sale: string | null }[];
  note: string;
}
