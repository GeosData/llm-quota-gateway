# Deploy

Cloud Run service `llm-quota-gateway` (project `geosdata`, region `us-east1`), built from source. No CI deploy.

```bash
gcloud run deploy llm-quota-gateway --source . --region us-east1 --project geosdata --max-instances 1 --memory 512Mi --cpu 1
```

Do not pass `--env-vars-file`, `--set-env-vars` or `--set-secrets`: the service already holds its variables and Secret Manager references (see gcloud run services describe), and redeploying without env flags keeps them. Add or change one with `--update-env-vars NAME=value` or `--update-secrets NAME=secret:latest`.

Verify: revision Ready, `/health` returns 200, no ERROR in logs. Then record the commit in `Core/projects/geosdata/infra/deploy/apps.json` (`lastDeploy`).
