# Property Valuation Coverage Plan

## Objective

Replace generic pending valuation cells with either:

- A defensible property-value estimate with its source, range, confidence, and effective date; or
- A specific, actionable review status explaining why a reliable estimate cannot yet be produced.

The system must not fabricate values merely to eliminate pending records.

## Valuation Source Hierarchy

Use the strongest available source for each property in this order:

1. A verified third-party AVM, such as RentCast.
2. A county- or state-specific XGBoost model with sufficient property features.
3. A comparable-sales estimate using nearby, recent, similar properties.
4. An assessment-based estimate adjusted using an official county equalization ratio.
5. Manual review when the property identity or characteristics remain ambiguous.

Every saved valuation should retain:

- Provider and methodology
- Estimated value
- Low and high range
- Confidence score
- Effective and retrieval dates
- Input-data quality indicators
- Provider response or model metadata
- Warnings appropriate to the estimation method

## Current Coverage Baseline

Among the 235 future scheduled properties measured during the audit:

- 5 have current Monmouth XGBoost estimates and complete ranges.
- 230 have no current valuation.

The pending population consists of:

- Camden: 166
- Cape May: 28
- Monmouth: 33
- New York: 3

Within the 38 future Monmouth properties:

- 5 are valued.
- 21 have parcel matches with confidence of at least 90%, but lack living-area data.
- 12 have no linked parcel/AVM feature record.
- None of the matched properties were excluded specifically because match confidence was below 90%.

## Phase 1: Complete the 21 Matched Monmouth Properties

These properties already have high-confidence parcel identities but cannot be scored because living area is missing.

### Data sources

Collect living area or square footage from:

- County assessment and property records
- Municipal tax records
- NJ property-history datasets
- RentCast subject-property attributes
- Recent deeds or verified listing history

### Implementation

1. Match each external characteristic record to the confirmed parcel.
2. Populate `properties.square_feet` or the appropriate AVM feature source.
3. Record the source, retrieval date, and match confidence.
4. Reject implausible values and conflicts for manual review.
5. Rerun the Monmouth model:

   ```bash
   python -m pipeline.predict_property_avm --save
   ```

### Expected result

Increase eligible Monmouth valuations from 5 to as many as 26 properties.

## Phase 2: Resolve the 12 Unmatched Monmouth Properties

Improve parcel matching using:

- Block, lot, and qualifier from the sheriff notice
- Municipality and borough normalization
- Street suffix and directional normalization
- Unit-number separation
- Alternate-address handling
- ZIP and municipality cross-checks
- Geocoding proximity
- Manual approval through Parcel Identity Review

### Implementation

1. Generate ranked parcel candidates.
2. Automatically accept only exact or sufficiently strong matches.
3. Send ambiguous candidates to Parcel Identity Review.
4. Preserve candidate scores and the final approval decision.
5. Create the property AVM feature record after approval.
6. Enrich living area and other required characteristics.
7. Run the local AVM.

Do not lower identity thresholds simply to produce a valuation.

## Phase 3: Expand Local AVM Coverage Beyond Monmouth

The current XGBoost model is Monmouth-specific and should not be applied blindly to other counties.

Priority counties:

1. Camden
2. Cape May
3. Remaining NJ counties as scraper coverage grows

### County onboarding process

For each county:

1. Load at least five years of usable arms-length sales.
2. Load assessment and property-characteristic records.
3. Normalize municipality, block, lot, and qualifier.
4. Join sales to parcels with auditable match confidence.
5. Exclude nominal, non-arms-length, and invalid transactions.
6. Engineer property and local-market features.
7. Train using time-based validation.
8. Measure error by municipality and property type.
9. Establish confidence and minimum-data thresholds.
10. Save predictions only when identity and feature quality pass those thresholds.

### Candidate features

- Living area
- Lot size
- Year built and property age
- Property class and use
- Bedrooms and bathrooms where available
- Municipality and ZIP
- Recent local sale-price median
- Recent local price per square foot
- Comparable count and distance
- Geographic coordinates
- Market trend and sale month

A unified NJ model may eventually outperform individual county models if county and municipality are included as features and validation confirms acceptable local performance.

## Phase 4: Add a Verified External AVM Fallback

Use RentCast when:

- The local model cannot score a property.
- Required local characteristics remain unavailable.
- The property is outside current local-model coverage.
- A complete, reliable postal address is available.

### Validation before saving

Verify the returned subject against:

- Street address
- City
- State
- ZIP code
- Unit number

Do not save a paid result when the returned subject does not match.

### Cost controls

- Cache successful results.
- Respect valuation expiration dates.
- Do not request the same property repeatedly.
- Prioritize future scheduled properties.
- Skip low-quality or ambiguous addresses.
- Track usage, failures, and cost per successful match.

RentCast is a paid service depending on plan and request volume.

## Phase 5: Add an Assessment-Based Fallback

Where no stronger estimate exists, calculate:

```text
estimated market value = total assessed value / official assessment ratio
```

Use official county or state equalization/common-level ratios where available.

### Required labeling

- Provider: `assessment_ratio`
- Confidence: low
- Wider low/high range than AVM estimates
- Warning: `Assessment-derived estimate—not an appraisal`
- Ratio source and effective year

An assessment-based estimate should never appear equivalent to a verified external AVM or a validated local model.

## Phase 6: Add Comparable-Sales Estimates

For properties with verified location and basic characteristics:

1. Find sales within approximately 1–5 miles.
2. Prefer sales from the previous 12–24 months.
3. Match property type and municipality.
4. Prefer similar living area, age, lot size, and construction type.
5. Remove nominal transfers and extreme outliers.
6. Calculate adjusted value and price-per-square-foot estimates.
7. Derive the value range from comparable dispersion.

Store:

- Comparable count
- Median and maximum comparable distance
- Comparable sale dates
- Adjustment methodology
- Median price per square foot
- Confidence score

Do not return a comparable-sales estimate when the comparable set is too small or dissimilar.

## Phase 7: Replace Generic Pending Labels with Actionable Statuses

Expose a valuation status and reason such as:

- Parcel match required
- Parcel match under review
- Living area missing
- Property characteristics incomplete
- County model unavailable
- Insufficient comparable sales
- External AVM lookup not attempted
- External AVM address mismatch
- External AVM unavailable
- Assessment ratio unavailable
- Manual review required
- Valuation expired

The frontend should display the reason and, where useful, a remediation action.

## Phase 8: Automate the Valuation Queue

After each sheriff-sale scraper run:

```text
New or updated sheriff sale
→ normalize address
→ resolve parcel identity
→ enrich property characteristics
→ run an eligible local AVM
→ use the verified external AVM fallback
→ calculate comparable-sales fallback
→ calculate assessment-based fallback
→ assign confidence and value range
→ calculate equity
→ queue unresolved properties for review
```

The automated job should:

- Prioritize future scheduled properties.
- Preserve historical valuations.
- Mark only one valuation as current according to source precedence.
- Refresh expired valuations.
- Avoid replacing stronger valuations with weaker estimates.
- Record all skipped and failed attempts.
- Recalculate equity after valuation changes.

## Data-Quality and Safety Rules

1. Never use an unverified parcel match for a high-confidence valuation.
2. Never overwrite a stronger current valuation with a weaker fallback.
3. Never describe a statistical estimate as an appraisal.
4. Store confidence and methodology with every valuation.
5. Preserve prior valuations for auditing.
6. Require low and high ranges for automated estimates where practical.
7. Flag conflicting square footage or identity information.
8. Keep valuation confidence separate from lien-risk confidence.
9. Do not calculate meaningful equity when the valuation or upset price is absent.
10. Monitor model error by county, municipality, and property type.

## Monitoring and Coverage Reporting

Add a valuation coverage report showing:

- Total future scheduled properties
- Valued and unresolved counts
- Coverage percentage
- Counts by state, county, and provider
- Counts by pending reason
- Median valuation confidence
- Expired valuations
- External API success and mismatch rates
- Local-model error metrics
- Properties requiring manual review

## Immediate Execution Sequence

1. Enrich living area for the 21 matched Monmouth properties.
2. Resolve the 12 unmatched Monmouth properties.
3. Rerun and validate the Monmouth XGBoost model.
4. Add valuation-status and pending-reason fields to the API and frontend.
5. Use RentCast for remaining future properties with reliable addresses.
6. Prepare Camden training and assessment datasets.
7. Prepare Cape May training and assessment datasets.
8. Add assessment-ratio fallback estimates.
9. Add comparable-sales fallback estimates.
10. Automate the valuation queue and coverage report.

## Definition of Done

The valuation workflow is complete when:

- Every future scheduled property has a defensible current estimate or an explicit review status.
- Every estimate shows provider, range, confidence, and date.
- Stronger sources take precedence over weaker fallbacks.
- Address and parcel mismatches cannot silently produce valuations.
- Equity is recalculated when market value or upset price changes.
- Coverage and failure reasons are measurable by county.
- Local models meet documented out-of-time accuracy thresholds.
- The frontend clearly distinguishes AVMs, comparable estimates, assessment-derived estimates, and manual values.
