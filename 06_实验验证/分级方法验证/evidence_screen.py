"""Metadata screening only; never impute missing operational parameters."""

REQUIRED_EVENT_FIELDS = (
    'cohort_entry', 'decision_snapshot', 'initial_backlog_B0',
    'direction_arrivals', 'joint_forecast', 'effective_service',
    'activation_end', 'shared_service', 'holding_goal_K',
    'completion_goal_H', 'same_cohort_departures',
    'same_cohort_completion', 'network_and_safety',
)


def event_readiness(event):
    """Derive blockers from field statuses, not a hand-written ready flag.

    COMPLETE and NOT_APPLICABLE require a documented scope justification;
    partial/missing/unknown fields are not promoted to complete here.
    """
    fields = event.get('fields', {})
    missing = [name for name in REQUIRED_EVENT_FIELDS
               if fields.get(name) not in ('complete', 'not_applicable')]
    return {'ready': not missing, 'unresolved_fields': missing}


def screen_candidate(candidate, target):
    """Check necessary metadata conditions, without issuing an actual F grade.

    Alignment is not an independent safety certification or proof that a
    resource commitment is executable. Applicable window is distinct from
    the publication date; old publication alone does not invalidate a rule.
    """
    mismatches, unknown = [], []
    for field, expected in target.items():
        actual = candidate.get(field)
        if actual is None:
            unknown.append(field)
        elif actual != expected:
            mismatches.append(field)
    status = ('REJECT_SCOPE' if mismatches else
              'UNRESOLVED_METADATA' if unknown else 'ALIGNED_REFERENCE')
    return {'status': status, 'mismatches': mismatches,
            'unknown': unknown, 'actual_parameter_assigned': False}
