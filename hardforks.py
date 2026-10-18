"""Explicit mainnet execution rules; fail closed at upgrade boundaries.

Schedule verified against go-ethereum params/chainspecs/mainnet.json.
BPO blob-only changes do not alter execution of these non-blob transactions.
The supported horizon is deliberately limited; never guess later upgrades.
"""
import datetime

SOURCE = 'https://github.com/ethereum/go-ethereum/blob/master/params/chainspecs/mainnet.json'
SCHEDULE = ((1710338135, 'cancun'), (1746612311, 'prague'), (1764798551, 'osaka'))
SUPPORTED_END = int(datetime.datetime(2026, 3, 1, tzinfo=datetime.timezone.utc).timestamp())


def hardfork_at(timestamp):
    if not SCHEDULE[0][0] <= timestamp < SUPPORTED_END:
        raise ValueError('Supported mainnet replay: after Cancun activation, before 2026-03-01 UTC. Later upgrades require verification.')
    return next(name for t, name in reversed(SCHEDULE) if timestamp >= t)


def hardfork_for_range(start, end):
    if end <= start:
        raise ValueError('Empty replay period')
    name = hardfork_at(start)
    # Prior-block state and candidate block must use the same execution rules.
    if hardfork_at(start - 12) != name or hardfork_at(end - 1) != name:
        raise ValueError('Period crosses a hardfork activation; split/omit the transition day')
    return name
