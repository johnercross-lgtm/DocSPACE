# DocSPACE

## Feed scheduler

`.github/workflows/feed-scheduler.yml` runs at 03:17, 09:43, 15:28 and
21:52 UTC. Each run checks every configured source and executes at most two
due sources. Source intervals, jitter and per-run item budgets are defined in
`config/feed_sources.json`.

Scheduler state is stored in Firestore collection `feed_scheduler_state`.
Each source document contains the effective configuration plus
`last_success_at`, `next_run_at`, last result and error fields. GitHub cache is
not used as scheduler state.

Required GitHub Actions secret:

- `FIREBASE_SERVICE_ACCOUNT_JSON`: minified service-account key JSON with
  Firestore read/write access. Prefer a dedicated account and least-privilege
  IAM permissions.

Optional repository variables:

- `FIREBASE_PROJECT_ID`: overrides the project ID embedded in credentials.
- `FIRESTORE_DATABASE`: Firestore database ID; defaults to `(default)`.

The workflow also uses the existing `OPENAI_API_KEY`, `OPENAI_MODEL`, Telegram
and feed-push settings. Firestore server libraries authenticate through IAM;
client Firestore Security Rules are not used for these scheduler writes.

Validate the scheduler without contacting Firestore:

```bash
python3 scripts/feed_scheduler.py --validate-config
python3 -m unittest discover -s tests -v
```
