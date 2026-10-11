"""Resolve a published PLAN calendar, never infer executed service rates."""
from datetime import datetime, timedelta


def window(route, operating_date, last_train_arrival=None):
    if operating_date not in route['operating_dates']:
        return None
    day = datetime.fromisoformat(operating_date)
    start = (None if route['start_clock'] is None else
             datetime.fromisoformat(operating_date + 'T' + route['start_clock']))
    rule = route['end_rule']
    kind = rule['kind']
    if kind == 'next_day_fixed':
        end = datetime.fromisoformat((day + timedelta(days=1)).date().isoformat() + 'T' + rule['clock'])
    elif kind == 'same_day_fixed':
        end = datetime.fromisoformat(operating_date + 'T' + rule['clock'])
    elif kind == 'last_train_arrival_plus_minutes':
        arrival = None if last_train_arrival is None else datetime.fromisoformat(last_train_arrival)
        if arrival is not None and (start is None or arrival < start or arrival >= start + timedelta(days=1)):
            raise ValueError('last train arrival must belong to this operating night')
        end = None if arrival is None else arrival + timedelta(minutes=rule['minutes'])
    else:
        raise ValueError('unknown service end rule: ' + str(kind))
    if start is not None and end is not None and end < start:
        raise ValueError('service window ends before it starts')
    return start, end
