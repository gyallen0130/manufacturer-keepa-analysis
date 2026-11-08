"""Offline supplier-docs resource-usage envelope (not a price quote).

The published US-base reference monthly free CPU and memory amounts are
shared allowances, NOT guaranteed discounts for a particular Tokyo deployment.
This tool never reads billing data or starts Cloud Run. The actual cost may
include region price differences, storage, registry, logs, API or network usage.

Reference: https://cloud.google.com/run/pricing (consult on deployment).
"""
REFERENCE_FREE_CPU_SECONDS = 240000
REFERENCE_FREE_GIB_SECONDS = 450000


def estimate_pilot_usage(*, runs_per_month=30, seconds_per_run=120,
                         vcpus=1, memory_gib=0.5, active_secret_versions=3,
                         scheduler_jobs=0):
    """Bound a proposed *manual dry-run* usage profile before deployment.

    Deliberately no predicted total amount in USD or JPY. Billing-account
    free usage and Google pricing SKUs must be checked at deployment time.
    """
    if (type(runs_per_month) is not int or not 0 <= runs_per_month <= 31
            or type(seconds_per_run) is not int
            or not 1 <= seconds_per_run <= 600
            or type(vcpus) is not int or vcpus != 1
            or type(memory_gib) not in (int, float)
            or memory_gib not in (0.5, 1.0)
            or type(active_secret_versions) is not int
            or not 0 <= active_secret_versions <= 6
            or type(scheduler_jobs) is not int or scheduler_jobs != 0):
        raise ValueError('proposed pilot exceeds approved dry-run bounds')
    cpu_seconds = runs_per_month * seconds_per_run * vcpus
    memory_seconds = runs_per_month * seconds_per_run * memory_gib
    return {
        'planned_runs': runs_per_month,
        'cpu_seconds': cpu_seconds,
        'memory_gib_seconds': memory_seconds,
        'reference_free_cpu_seconds': REFERENCE_FREE_CPU_SECONDS,
        'reference_free_memory_gib_seconds': REFERENCE_FREE_GIB_SECONDS,
        'within_reference_compute_allowances': (
            cpu_seconds <= REFERENCE_FREE_CPU_SECONDS
            and memory_seconds <= REFERENCE_FREE_GIB_SECONDS),
        'planned_active_secret_versions': active_secret_versions,
        'planned_scheduler_jobs': scheduler_jobs,
        'actual_billing_account_free_usage_known': False,
        'tokyo_region_cost_confirmed': False,
        'storage_registry_logs_network_cost_included': False,
        'automatic_execution_enabled': False,
        'requires_billing_review_before_deployment': True,
    }
