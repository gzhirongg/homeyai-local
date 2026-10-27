# Downloaded data

Source datasets and generated address/model reports are intentionally excluded
from Git. The standalone bootstrap creates them here and archives source copies
with content hashes in the local MinIO store.

From the repository root, after starting Docker services:

```bash
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_valuation.py
./scripts/local.sh exec -T backend python -u scripts/bootstrap_local_map.py
./scripts/local.sh exec -T backend python -u scripts/calibrate_local_valuation.py
./scripts/local.sh restart backend
```

The scripts download HDB resale records, HDB Property Information, HDB building
footprints, HDB RPI, URA Master Plan 2019 regions/planning areas and LTA MRT exits
from data.gov.sg. Address/station matching uses the pinned public archived OneMap
CSV identified in the bootstrap source. No OneMap account is required for this
archived local setup.

Exact source URLs, dataset IDs and SHA-256 hashes are recorded in
`local_provenance.json` and `local_map_provenance.json` after import. Public source
snapshots can change; imported counts, model scores and prices can therefore
differ from the documented verification run. The historical reported interval
coverage is not a promise about a newly trained model.

The repo does not include the POI source assets, MRT opening-date history,
authenticated routing data or a private-property training dataset. See the
[setup guide](../docs/guides/public-repository-setup.md) and
[feature audit](../docs/guides/local-feature-completion.md).
