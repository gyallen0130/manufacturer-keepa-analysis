# Owner-run WIF/IAM read-only preflight (not a deployment approval)

**Status: dev-only.** This helper cannot activate a workflow, create a WIF provider, modify IAM, fetch Sheets values or check actual GitHub billing. It does not replace independent security review.

## Purpose

Private GitHub → Google Reader is blocked on verifying the real Workload Identity Federation provider and dedicated Reader service-account IAM policy. The entrypoint calls only the two existing read-only gcloud requests and prints anonymous yes/no checks.

## Prerequisites

1. A trusted local PC or Google Cloud Shell with an already authenticated gcloud CLI and sufficient read-only IAM permissions. No login or token creation is performed by the helper.
2. Locally prepared PRIVATE JSON files for settings and a separately authenticated GitHub repository snapshot. Required repository fields: full_name, numeric id, owner.id, visibility, archived, default_branch, default_branch_protected. For that last field, read the branch endpoint rather than inferring protection.
3. Absolute paths to both JSON files, no symlinks, maximum 16 KiB each. On Linux or Cloud Shell set chmod 600. Never commit the real files or paste them into public logs, issues or chat.
4. Independently reviewed 40-character workflow_sha and source commit sha. Unreviewed code changes invalidate the trust assumption.
5. The settings object accepted by supplier_docs.github_wif_review.plan_private_github_wif, whose REQUIRED keys and fake-only test fixture are in the code. Do not claim that billing or security reviews are complete unless independently verified.

## Run command

From the reviewed branch, inside the manufacturer_checker directory:

    python -m supplier_docs.manual_wif_preflight_cli \
      --settings-file /absolute/private/owner-wif-settings.json \
      --github-snapshot-file /absolute/private/github-repo-snapshot.json \
      --workflow-sha REVIEWED_40_HEX_WORKFLOW_SHA \
      --source-sha REVIEWED_40_HEX_SOURCE_SHA \
      --confirm-readonly

Without --confirm-readonly no API is called. The only remote commands permitted are the Google WIF provider DESCRIBE and Reader service-account GET-IAM-POLICY. No IAM writes, Google OAuth login, GitHub workflow dispatch, Drive or Sheets read, Artifact upload or additional service provisioning.

Output contains status/check booleans only. Actual resource names, project numbers, SA emails, raw IAM JSON and error details are never output by the helper. A missing provider, permission, or exact condition is a fail-closed condition.

## Interpret results

- blocked_on_observed_trust_mismatch: observed repo, provider or Reader identity trust does not match the reviewed expectation. NO-GO.
- blocked_on_external_configuration_review: some independent checklist confirmations are incomplete. NO-GO.
- eligible_for_separate_manual_connection_review: observed provider and IAM satisfy these limited checks. STILL NO-GO for production: real token exchange, actual Sheets read, private workflow and owner decryption are not yet tested.

Important: service account get-iam-policy does not enumerate inherited project or organization roles. Review effective Reader permissions separately.

GitHub Free includes a monthly USD-based pool of compute credit, but the helper does NOT know the account's actual remaining credit, billable storage or spending-stop setting. Verify these in GitHub Billing before any private workflow starts.

## Next milestone

After GitHub billing stop, private repo code controls, WIF conditions, Reader identity, owner Windows key safety and code/Action/dependency review are complete, separately authorize ONE FILE, ONE TAB, ONE MANUAL RUN via Private GitHub Actions → WIF → Reader → Sheets → owner-encrypted Artifact → Windows decrypt. No recurring job, Drive-wide crawler, Keepa or SP-API integration.

Official references:
- https://docs.cloud.google.com/iam/docs/manage-workload-identity-pools-providers
- https://docs.cloud.google.com/sdk/gcloud/reference/iam/service-accounts/get-iam-policy
- https://docs.github.com/en/billing/reference/product-usage-included
- https://docs.github.com/en/billing/how-tos/set-up-budgets
