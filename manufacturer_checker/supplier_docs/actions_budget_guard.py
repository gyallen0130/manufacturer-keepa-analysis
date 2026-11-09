"""No-network, fail-closed CURRENT-STYLE GitHub compute-credit review.

GitHub now describes included standard-runner compute as a dollar credit
(e.g. GitHub Free $12/month), shared with other eligible compute. Historical
"2,000 minutes/month" must NOT be used as a deployment budget. This module
uses owner-supplied CURRENT billing figures; it does not read GitHub Billing,
prove quotas, configure spending limits, launch workflows or incur charges.
"""
from decimal import Decimal
import re

_PERIOD = re.compile(r'^\d{4}-(?:0[1-9]|1[0-2])$')
_AMOUNT = re.compile(r'^(?:0|[1-9]\d{0,4})(?:\.\d{1,5})?$')


def _money(value, *, positive=False):
    if not isinstance(value, str) or not _AMOUNT.fullmatch(value):
        raise ValueError('USD budget figures must be explicit decimal strings')
    amount = Decimal(value)
    if (positive and amount <= 0) or amount > Decimal('100000'):
        raise ValueError('invalid USD budget value')
    return amount


def assess_private_actions_allowance(
        *, billing_period, usage_checked_period=None,
        included_compute_usd=None, consumed_compute_usd=None,
        runner_rate_usd_per_minute=None, planned_runs=30,
        max_minutes_per_run=5, reserve_usd='1.00',
        private_repo=True, owner_verified_remaining=False,
        hard_stop_budget_reviewed=False, secret_controls_reviewed=False,
        storage_billing_reviewed=False):
    """Assess proposed cost as USD; unknown existing usage ALWAYS blocks.

    The owner must independently check the runner rate, CURRENT included
    compute credits, usage across repos and other eligible compute, storage,
    and GitHub spending stop configuration. No approval or secrets implied.
    """
    if (not isinstance(billing_period, str) or not _PERIOD.fullmatch(billing_period)
            or (usage_checked_period is not None and (
                not isinstance(usage_checked_period, str)
                or not _PERIOD.fullmatch(usage_checked_period)))):
        raise ValueError('billing periods must be explicit YYYY-MM')
    for flag in (private_repo, owner_verified_remaining,
                 hard_stop_budget_reviewed, secret_controls_reviewed,
                 storage_billing_reviewed):
        if type(flag) is not bool:
            raise ValueError('billing and safety flags must be booleans')
    if not private_repo:
        raise ValueError('supplier workflow must use a private repository')
    if (type(planned_runs) is not int or not 0 <= planned_runs <= 31
            or type(max_minutes_per_run) is not int
            or not 1 <= max_minutes_per_run <= 15):
        raise ValueError('invalid bounded schedule')
    reserve = _money(reserve_usd, positive=True)
    supplied = (included_compute_usd, consumed_compute_usd,
                runner_rate_usd_per_minute)
    if any(item is not None for item in supplied):
        if any(item is None for item in supplied):
            raise ValueError('partial billing data is not trustworthy')
        included, consumed, rate = (
            _money(included_compute_usd),
            _money(consumed_compute_usd),
            _money(runner_rate_usd_per_minute, positive=True))
    else:
        included = consumed = rate = None

    verified = (included is not None
                and usage_checked_period == billing_period
                and owner_verified_remaining)
    minutes = planned_runs * max_minutes_per_run
    estimated = (Decimal(minutes) * rate if verified else None)
    remaining = (
        included - consumed - estimated if verified else None)
    if not verified:
        status = 'blocked_until_current_billing_credit_verified'
    elif remaining < reserve:
        status = 'blocked_to_preserve_compute_credit_reserve'
    elif not hard_stop_budget_reviewed:
        status = 'blocked_until_spending_stop_reviewed'
    elif not secret_controls_reviewed:
        status = 'blocked_until_private_secret_controls_reviewed'
    elif not storage_billing_reviewed:
        status = 'blocked_until_storage_billing_reviewed'
    else:
        status = 'eligible_for_separate_manual_security_review'

    return {
        'status': status,
        'estimated_max_monthly_runner_minutes': minutes,
        'estimated_compute_usd': str(estimated) if estimated is not None else None,
        'post_plan_remaining_compute_credit_usd': (
            str(remaining) if remaining is not None else None),
        'minimum_reserve_usd': str(reserve),
        'billing_figures_verified_by_code': False,
        'current_runner_rate_verified_by_code': False,
        'shared_credit_usage_checked_by_code': False,
        'private_environment_secrets_assumed_available_on_free_plan': False,
        'workflow_activated': False,
        'budget_changed': False,
        'additional_cost_guaranteed_zero': False,
    }
