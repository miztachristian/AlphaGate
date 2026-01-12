"""Outcome evaluation module for post-alert analysis.

Computes MFE/MAE and forward returns for triggered alerts to enable
objective evaluation and confidence score calibration.

Key components:
- outcome_logger: Core evaluation logic and database operations
- reporting: Summary reports by score bucket and regime
"""

from .outcome_logger import (
    load_alerts_needing_evaluation,
    compute_outcomes_for_alert,
    upsert_outcome,
    run_outcome_evaluation,
    generate_alert_id,
    get_interval_minutes,
    EvaluationStatus,
)
from .reporting import (
    generate_reports,
    compute_bucket_stats,
    compute_regime_stats,
)

__all__ = [
    # Core functions
    "load_alerts_needing_evaluation",
    "compute_outcomes_for_alert",
    "upsert_outcome",
    "run_outcome_evaluation",
    "generate_alert_id",
    "get_interval_minutes",
    "EvaluationStatus",
    # Reporting
    "generate_reports",
    "compute_bucket_stats",
    "compute_regime_stats",
]
