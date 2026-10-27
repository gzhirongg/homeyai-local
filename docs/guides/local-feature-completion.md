# Local feature completion audit

Reviewed and verified on 27 October 2026. This audit covers `data/`, `backend/`,
`modelling/`, and the isolated local database/MinIO store. No team VM or production
database was accessed. No new external datasets were downloaded for this work.

## Assets actually present

- Public HDB resale CSV, catalogue, footprints, RPI, validated address parquet.
- URA region/planning polygons and LTA exit geometry; archived OneMap station codes.
- One registered local LightGBM baseline, its manifest/metrics/configuration, and
  the shared modelling pipeline. The small legacy pickle is not the active model.
- SHAP code and runtime dependency, report HTML/CSS/WeasyPrint, analytics/query code.
- Local tables: 175 MRT line entries; **zero POI rows and zero MRT route rows**.
- No POI source assets, dated MRT registry, private-property training data, or
  news/social sentiment corpus. Notebook references to files are not those files.
- OpenAI, MAS, URA and OneMap credentials are not configured (values were not logged).

## Completed or verified

| Feature | Evidence / change |
| --- | --- |
| SHAP explanations | Real premium valuation returns 11 feature contributions. Their sum plus the baseline reproduces the prediction in log-price space within 1e-5. Existing implementation works. |
| Report configuration | Repaired missing `get_default_report_config`; all six supported section flags now return successfully. |
| JSON report preview | Repaired obsolete `property_type`, `floor_area`, `lease_year`, `floor_level` references to match `ValuationInput`. |
| HTML/PDF reports | Verified live HTML, PDF download and custom sections. Preview gates now match the PDF premium gate. Removed external font fetching. |
| Report accuracy | Uses actual recorded comparable sales from the valuation response, rather than town street aggregates labelled as comparable transactions. Removed unsupported 95%/model-calibration claims and explained SHAP units. Missing rate data is explicitly unavailable. |
| Print layout | Replaced overlapping logical-page labels with physical PDF page counters. Combined short methodology/disclaimer sections. All four final PDF pages were rendered and inspected. |
| Price ranges | Added held-out calibration to the existing baseline pipeline and serving path. Target and observed coverage are shown in the UI and report. Details below. |
| Standalone assistant | Replaced keyword canned answers at `/api/ai/chat` with the existing analytics chat service. Fixed broken service imports and PSF conversion in the prompt. Without a key it provides rule-based statistics from the actual database, not full conversational AI. Removed fabricated numeric confidence. |
| Analytics summaries | Removed an unsupported national-median comparison from the rule-based summary. Local chat recognizes towns from the actual data catalogue. |
| Market signals | Reuses the populated Postgres RPI table before remote/cache fallbacks. Missing rates are not labelled stable. Missing RPI fails explicitly. The UI no longer substitutes sample market values on failures, and labels the synthesis as rule-based. |
| Calculators | Browser checked S$500,000 / 25 years / 3.5% -> S$2,503 rounded monthly; S$650,000 sale minus S$500,000 purchase minus S$20,000 costs -> S$130,000 / 26%; changing costs to S$30,000 -> S$120,000 / 24%. No calculator source change needed. |
| Flat-type encoding | Fixed pandas nullable missing values becoming `pd.NA` in numeric model inputs; unknown labels now yield IEEE NaN for the existing imputer. |
| Address MRT explorer | Unknown/undated physical stations have a separate group instead of being presented as operational. This improves labelling but does not supply opening history. |

## Calibrated local model

The prior local model was refitted on every available row, so its training residuals
cannot be used as independent calibration evidence. The new version uses the same
LightGBM configuration and cached data, with strictly separated chronological periods:

- Train: 118,340 transactions, November 2021-April 2026.
- Calibrate: 6,898 transactions, May-July 2026.
- Test: 6,560 transactions, August-October 2026.
- No refit on calibration or test rows.
- Nominal-SGD test MAE S$31,600; RMSE S$47,052; MAPE 4.55%; R2 0.9574.
- Relative-error quantile 0.0873179, using the finite-sample split-conformal rank.
- **Target coverage: 90%. Observed later test coverage: 86.65%.** This demonstrates
  temporal undercoverage; it is not a guaranteed 90% future coverage statement.
  The UI/report show the observed result and the market-shift limitation.

Method reference: [Angelopoulos & Bates, introduction to conformal prediction](https://arxiv.org/abs/2107.07511).
Exchangeability assumptions do not automatically hold for changing property markets.
These ranges remain a development estimate, not a production-certified uncertainty model.

New immutable model folder:
`models/dev/valuation/experiments/local_lightgbm_calibrated__20261027T055742Z/`.
Calibration metadata lives with that exact model's manifest. The existing registry
activates it on backend startup. The old baseline and its metrics are retained for
rollback; the two test scores use different holdout periods and are not a direct
model-performance comparison.

Reproduce from already bootstrapped local data:

```bash
./scripts/local.sh exec -T backend python -u scripts/calibrate_local_valuation.py
./scripts/local.sh restart backend
./scripts/local.sh exec -T backend python -u scripts/verify_local_features.py
python3 scripts/check_local.py --valuation --map
```

Reports: `data/local_calibration_report.json`, `data/local_feature_verification.json`.
Reviewed PDF: `output/pdf/verified-local-valuation.pdf`.

## Final verification

- Backend: **146 passed**, 7 deprecation warnings.
- Modelling: **121 passed, 1 skipped**; skipped POI smoke test requires seven absent source assets.
- Frontend: TypeScript and production build passed. Changed frontend files have
  zero lint errors (26 warnings); the three previously documented Map.tsx errors
  remain outside these edits.
- Live checks: active calibrated model; 11 SHAP contributions and log additivity;
  JSON/HTML/PDF previews; custom report flags; real HDB assistant statistics;
  database RPI/volume; absent rates; address/area MRT unknown-status groups;
  authentication, storage/DB/Prefect health; 10 actual nearby resale comparables.
- Browser: calculator inputs/results, premium valuation, prediction range,
  calibrated sample count and observed coverage were checked.
- Four physical PDF pages rendered and inspected after the footer fix.
- Screenshot: `docs/guides/local-calibrated-valuation-verified.png`.

## Remaining gaps

| Gap | Why these folders cannot finish it |
| --- | --- |
| POI displays and advanced POI model | Ingestion/feature code exists, but source assets and populated tables are absent. |
| MRT opening/planned classification and point-in-time model | No trustworthy dated registry is included. Location geometry does not establish opening dates. |
| MRT walk/transit routes | No stored routes or configured OneMap credentials. Straight-line distance is not a substitute for routed travel time. |
| Condo/landed valuation | No private-property training dataset or compatible validated model is supplied. |
| Full conversational AI | Integration exists, but no provider key. Local statistics are useful but do not implement arbitrary language reasoning. |
| MAS interest-rate signal | Missing API credentials/cached rate series. |
| News/social sentiment | Current service measures HDB/RPI/volume/rates; no news/social pipeline or corpus is supplied. |
| Google login / password recovery / billing | Requires provider/SMTP/payment setup and additional application flows; not solvable by loading modelling data. |
| Free quota enforcement | Field exists, but reset/usage logic is absent; requirements conflict between daily and monthly limits. Requires an agreed policy plus migration/implementation. |
| Scheduled ingestion/retraining | Prefect flow code/server exist; no local worker/deployment scheduling was configured. |

This work does not certify every admin screen, PDF input edge case, production
security requirement or financial-policy rule. Existing map lint errors and
dependency deprecation warnings remain documented in the standalone setup guide.
