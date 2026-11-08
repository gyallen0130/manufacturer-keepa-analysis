"""Conservative, OFFLINE GitHub Actions allowance review for a private pilot.

No billing API access, workflow dispatch, account changes or paid tools.
Never assume GitHub Free private-environment secrets or protection rules:
private environment secrets are not a free-plan feature. A repository secret
may be available, but it can be referenced by other workflows in the repo.

This review uses only information an owner separately obtained from GitHub
Billing; it does not attest that information is correct or current.
"""
import re

_PERIOD = re.compile(r'^\d{4}-(?:0[1-9]|1[0-2])$')


def assess_private_actions_allowance(
        *, billing_period, usage_checked_period=None,
        account_included_minutes=None, already_used_minutes=None,
        planned_runs=30, max_minutes_per_run=5, reserve_minutes=120,
        private_repo=True, owner_verified_remaining=False,
        hard_stop_budget_reviewed=False, secret_controls_reviewed=False):
    """Return a non-authorizing plan from owner-supplied billing numbers.

    Unknown minute usage, missing stop-usage budget review or inadequate
    reserve BLOCKS deployment. This is not a replacement for checking
    actual GitHub Billing balances, usage multipliers or billing policies.
    """
    if (not isinstance(billing_period, str) or not _PERIOD.fullmatch(billing_period)
            or (usage_checked_period is not None
                and (not isinstance(usage_checked_period, str)
                     or not _PERIOD.fullmatch(usage_checked_period)))):
        raise ValueError('explicit valid billing periods required')
    for name, value in (
        ('private_repo', private_repo),
        ('owner_verified_remaining', owner_verified_remaining),
        ('hard_stop_budget_reviewed', hard_stop_budget_reviewed),
        ('secret_controls_reviewed', secret_controls_reviewed),
    ):
        if type(value) is not bool:
            raise ValueError('budget control flags must be booleans')
    if not private_repo:
        raise ValueError('private repo required for supplier workflow')
    for number, minimum, maximum in [
        (account_included_minutes, 0, 100000),
        (already_used_minutes, 0, 100000),
        (planned_runs, 0, 31),
        (max_minutes_per_run, 1, 15),
        (reserve_minutes, 100, 10000),
    ]:
        if number is not None and (
                type(number) is not int
                or not minimum <= number <= maximum):
            raise ValueError('invalid bounded Actions minute estimate')
    workload = planned_runs * max_minutes_per_run
    usage_available = (
        account_included_minutes is not None
        and already_used_minutes is not None
        and usage_checked_period == billing_period
        and owner_verified_remaining
    )
    remaining_after_plan = (
        account_included_minutes - already_used_minutes - workload
        if usage_available else None
    )
    if not usage_available:
        status = 'blocked_until_billing_usage_verified'
    elif remaining_after_plan < reserve_minutes:
        status = 'blocked_to_preserve_free_minute_reserve'
    elif not hard_stop_budget_reviewed:
        status = 'blocked_until_hard_spending_stop_reviewed'
    elif not secret_controls_reviewed:
        status = 'blocked_until_private_secret_controls_reviewed'
    else:
        status = 'eligible_for_separate_manual_security_review'
    return {
        'status': status,
        'planned_max_monthly_minutes': workload,
        'post_plan_remaining_minutes_estimate': remaining_after_plan,
        'minimum_remaining_reserve_minutes': reserve_minutes,
        'billing_figures_independently_verified_by_code': False,
        'private_environment_secrets_assumed_available_on_free_plan': False,
        'private_repo_secret_access_requires_workflow_review': True,
        'workflow_activated': False,
        'budget_changed': False,
        'additional_cost_guaranteed_zero': False,
    }
