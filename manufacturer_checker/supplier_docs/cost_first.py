"""Zero-new-subscription-first decision gate; purely offline.

This module does NOT assert that using GitHub Actions, Apps Script, or existing
Google Cloud necessarily costs $0. It checks estimates and prerequisites,
returns only non-sensitive conclusions, and never provisions any services.

Supplier source values, tokens, signing keys, encrypted state, file IDs and
private workflow logs MUST NOT be committed to a public repository.
"""
SUPPORTED_RUNNERS = frozenset({
    'manual_local', 'existing_github_actions', 'existing_apps_script',
    'new_gcp_resources',
})


def evaluate_cost_first_plan(plan):
    """Review a proposal without executing it, before additional billing.

    Keys:
      runner: one of SUPPORTED_RUNNERS
      new_paid_service: bool
      recurring_charge_estimate_jpy: nonnegative integer or None (unknown)
      secret_business_data_in_public_repo: bool
      confidential_logs_or_artifacts: bool
      persistent_state_ready: bool
      execution_enabled: bool
      owner_approved_extra_cost: bool
      shared_free_quota_verified: bool

    A new recurring expense is blocked by default and needs explicit consent.
    An apparently free option without verified quotas/state is a design candidate,
    not production approval. All output is redacted.
    """
    fields = frozenset({
        'runner', 'new_paid_service', 'recurring_charge_estimate_jpy',
        'secret_business_data_in_public_repo', 'confidential_logs_or_artifacts',
        'persistent_state_ready', 'execution_enabled',
        'owner_approved_extra_cost', 'shared_free_quota_verified',
    })
    if not isinstance(plan, dict) or set(plan) != fields:
        raise ValueError('invalid cost-first design proposal')
    runner = plan['runner']
    if runner not in SUPPORTED_RUNNERS:
        raise ValueError('unknown processing option')
    for key in fields - {'runner', 'recurring_charge_estimate_jpy'}:
        if type(plan[key]) is not bool:
            raise ValueError('decision flags must be explicit booleans')
    estimate = plan['recurring_charge_estimate_jpy']
    if estimate is not None and (type(estimate) is not int or estimate < 0):
        raise ValueError('recurring cost must be nonnegative or unknown')
    if plan['secret_business_data_in_public_repo'] or plan['confidential_logs_or_artifacts']:
        raise ValueError('supplier data must not be exposed through public storage or logs')
    if plan['execution_enabled']:
        raise ValueError('this offline preflight cannot activate a workflow')
    if runner == 'new_gcp_resources' and not plan['new_paid_service']:
        # Free trial credits and account-shared free allowances are not proof
        # that newly provisioned resources have zero recurring cost.
        raise ValueError('new Google Cloud resources require billing risk review')
    extra_cost = plan['new_paid_service'] or estimate is None or estimate > 0
    if extra_cost and not plan['owner_approved_extra_cost']:
        status = 'blocked_pending_explicit_cost_approval'
    elif not plan['persistent_state_ready']:
        status = 'design_only_state_storage_unresolved'
    elif not plan['shared_free_quota_verified']:
        status = 'design_only_free_quota_unverified'
    else:
        status = 'eligible_for_separate_security_and_access_review'
    return {
        'policy': 'no_new_recurring_cost_by_default',
        'runner_class': runner,
        'status': status,
        'zero_extra_cost_guaranteed': False,
        'cloud_resources_created': 0,
        'automations_activated': 0,
        'public_business_data_allowed': False,
        'explicit_owner_cost_approval_required': extra_cost,
        'additional_security_review_required': True,
    }
