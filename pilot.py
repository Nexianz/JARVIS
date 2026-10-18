"""One UTC day of sampled, guarded historical replay. No live trading or deployment."""
import argparse
import dataclasses
import datetime
import json
import pathlib
import sys

import collect
from chain import RPCError, BudgetStop, load_env, rpc_url
from market import Market, day, timestamp
from model import SCENARIOS, simulate
from quota import QuotaClient, DEFAULT_MAX_CU


def load_rows(folder, manifest):
    rows = [json.loads(line) for line in (folder / 'blocks.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = set(range(manifest['first'], manifest['last'] + 1))
    if not manifest.get('complete') or len(rows) != len(expected) or {r['block'] for r in rows} != expected:
        raise ValueError('Incomplete pilot: no full-day result or CU extrapolation will be produced. Resume the same command.')
    if manifest.get('smoke_only') or timestamp(manifest['end_exclusive']) - timestamp(manifest['start']) != 86400:
        raise ValueError('Pilot report requires exactly one UTC day without smoke truncation')
    return sorted(rows, key=lambda r: r['block'])


def build_report(manifest, rows, valuations, cu):
    evaluated = [r for r in rows if r.get('selection') == 'evaluated']
    replay_rows = [valuations['initial']] + evaluated + [valuations['final']]
    counts = {}
    for mode in ('A', 'B'):
        opportunities = set()
        contested = set()
        for r in evaluated:
            for c in r['candidates']:
                if c['mode'] != mode:
                    continue
                key = (r['block'], c['first'], c['second'])
                opportunities.add(key)
                if c['competition']['same_route_cycle_txs']:
                    contested.add(key)
        counts[mode] = dict(route_block_opportunities=len(opportunities), competitor_proxy=len(contested))
    sensitivity = []
    for mode in ('A', 'B'):
        for channel in ('private', 'public'):
            for bid in (.80, .90, .95, .99):
                settings = dataclasses.replace(SCENARIOS['realistisk'], bid=bid)
                sensitivity.append(simulate(replay_rows, manifest, settings, mode, channel, seed=17))
    scenarios = []
    for mode in ('A', 'B'):
        for channel in ('private', 'public'):
            for settings in SCENARIOS.values():
                scenarios.append(simulate(replay_rows, manifest, settings, mode, channel, seed=17))
    return dict(
        scope='One sampled UTC day; no unsampled-block PnL extrapolation or actual trades.',
        labels=dict(chain_inputs='MÅLT: historical mainnet headers, eth_call and Swap logs',
                    fx='MÅLT: Norges Bank historical USD/NOK, prior business day when necessary',
                    counts='BEREGNET from measured data in selected blocks only',
                    cu='BEREGNET from ANTATTE method costs, not Alchemy billing',
                    pnl='BEREGNET counterfactual conditional on ANTATTE inclusion, failures, haircut and bids',
                    gas='BEREGNET by local EVM replay against measured historical state; not gas spent on mainnet'),
        selected_blocks=len(evaluated), total_blocks=len(rows), every_n_blocks=manifest['every_n_blocks'],
        raw_opportunities=counts, cu=cu, sensitivity=sensitivity, scenarios=scenarios,
        caveats=[
            'Both-leg same-transaction Swap matches are a conservative competition proxy, not proven profitable arbitrage.',
            'Actual number we would win is UNKNOWN. Model wins/failures are assumed outcomes, not observations.',
            'Previous-block swaps select observations; opportunities without a previous-block swap are omitted.',
            'No multiplying sampled profit by sampling interval; no full-day or 30/90-day profit claim.',
            'Local replay is at the front of the next block, not its actual transaction ordering.',
            'Priority bid uses prior-block measured median; current-block measured median is diagnostic only.',
            'Minimum-profit gas guard uses measured replay gas plus an assumed 512-unit allowance; bid size may change gas.',
            'Size optimization uses a logarithmic grid and local refinement, not a proof of the global optimum.',
            'USDC/WETH allowlist and pool-age/depth checks do not replace an independent contract/security audit.',
            'Gas-wallet ETH and USDC exposure can move portfolio value without any arbitrage.',
            'This pilot has no walk-forward or Monte Carlo; full study requires review and approval separately.',
        ])


def markdown(report):
    lines = ['# PILOT — ett døgn, utvalg av blokker', '',
             'Ingen faktiske handler. Dette er ikke et målt svar for alle blokkene i døgnet.', '',
             '| Verdi | Resultat | Status |', '|---|---:|---|',
             f'| Blokker i perioden | {report["total_blocks"]} | BEREGNET fra målte blokkgrenser |',
             f'| Blokker simulert etter sampling og Swap-filter | {report["selected_blocks"]} | BEREGNET |',
             f'| Sampling: hver N. blokk | {report["every_n_blocks"]} | ANTATT valg |']
    for label, key in [('CU reservert totalt i delt kvotelogg', 'cumulative'), ('CU tilført av piloten inkl. resume', 'pilot'),
                       ('CU for 30 lignende døgn', 'days30'), ('CU for 90 lignende døgn', 'days90')]:
        lines.append(f'| {label} | {report["cu"][key]} | BEREGNET fra ANTATTE CU-satser |')
    lines += ['', 'CU-framskrivningen er pilotkostnaden ganger antall døgn, med samme sampling. '
              'Den inkluderer oppstart/cache-effekter, er ikke et pristilbud og er ikke faktisk fakturert CU.', '']
    for mode, title in [('A', 'Flash loan; 5000 NOK er gas-lommebok'), ('B', 'Egenkapital; 20 % ETH / 80 % USDC')]:
        c = report['raw_opportunities'][mode]
        lines += [f'## {mode}: {title}', '',
                  f'BEREGNET: {c["route_block_opportunities"]} rute/blokk-muligheter med positivt EVM-overskudd etter '
                  f'poolavgifter og eventuell flash-premie, før gas/builder. Flere størrelser på samme rute telles én gang. '
                  f'BEREGNET: {c["competitor_proxy"]} med konkurranseproxy fra MÅLTE Swap-events i neste blokk. '
                  'Disse behandles som tapt for oss; det beviser ikke faktisk arbitrørprofitt.', '',
                  '| Kanal | Builder-andel | Gas NOK | Builder NOK | Netto arbitrasje NOK | Sluttverdi NOK | Modellvinner | Modellrevert | Privat avvist |',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
        for r in report['sensitivity']:
            if r['mode'] != mode:
                continue
            c = r['counts']
            lines.append(f'| {r["channel"]} | {r["assumptions"]["bid"]:.0%} | {r["gas_nok_at_trade_fx"]:.2f} | '
                         f'{r["builder_bid_nok_at_trade_fx"]:.2f} | {r["incremental_vs_hold_nok"]:.2f} | '
                         f'{r["final_nok"]:.2f} | {c.get("wins", 0)} | {c.get("failed", 0)} | {c.get("private_rejected", 0)} |')
    lines += ['', 'Alle resultater i tabellene er BEREGNET med ANTATTE utfall. Builder-andel er av positivt overskudd etter gas; '
              'historisk Aave-premie og poolavgifter inngår allerede i EVM-profitt. Netto arbitrasje er resultat mot '
              'å holde samme ETH/USDC-portefølje; sluttverdi inkluderer markedsbevegelse og ANTATT vekslingskostnad på 0,3 %.', '',
              'ANTATT: privat inkludering 10 %, offentlig inkludering 95 %, ekstra feilandel 10 %, '
              'tilfeldig profittreduksjon 0–10 %. Samme tilfeldighetsfrø brukes for sammenligning. '
              'Dette er én modellbane, ikke en forventningsverdi eller sannsynlighetsprognose. '
              'Private bundle-reverter blir ikke inkludert og betaler verken gas eller builder; offentlige reverter betaler gas.', '',
              'ANTATTE risikogrenser håndheves i koden: netto minst 1 NOK + 25 % av gas, '
              'maks 50 NOK dagstap / 150 NOK ukestap, maks 30 NOK gas per transaksjon, 100 gwei og 3 reverter per time.', '',
              '## Scenarioer', '', '| Modus | Kanal | ANTATT scenario | BEREGNET netto arbitrasje NOK |', '|---|---|---|---:|']
    for r in report['scenarios']:
        lines.append(f'| {r["mode"]} | {r["channel"]} | {r["assumptions"]["name"]} | {r["incremental_vs_hold_nok"]:.2f} |')
    lines += ['', 'Fullstendige antakelser, gas-enheter, risikoblokkeringer og modellhandler finnes i pilot.json. '
              'Pessimistisk/realistisk/optimistisk er antakelser, ikke kalibrerte sannsynligheter.', '', '## Begrensninger', '']
    lines += ['- ' + text for text in report['caveats']]
    lines += ['', 'Ingen konklusjon om lønnsomhet for hele døgnet eller 30/90 dager kan trekkes fra dette utvalget. '
              'Ingen privatnøkler eller wallet brukes. Kontrakten er et lokalt forskningsverktøy; før eventuell bruk med '
              'ekte penger kreves uavhengig revisjon, tilgangskontroll, reentrancy-gjennomgang og separat nøkkelhåndtering.']
    return '\n'.join(lines) + '\n'


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date', default='2025-06-01')
    ap.add_argument('--every-n-blocks', type=int, default=60)
    ap.add_argument('--max-cu', type=int, default=DEFAULT_MAX_CU)
    ap.add_argument('--quota-dir', default='.cache/alchemy')
    ap.add_argument('--output')
    ap.add_argument('--max-cu-per-day',type=int,help='Persistent per-date ceiling, in addition to cumulative --max-cu')
    ap.add_argument('--verify-replay',action='store_true',help='Require date-specific minProfit replay before collection')
    ap.add_argument('--quiet-report',action='store_true',help='Save full report but print only its location')
    ap.add_argument('--retry-uncertain', action='store_true')
    args = ap.parse_args(argv)
    start = datetime.date.fromisoformat(args.date)
    end = (start + datetime.timedelta(days=1)).isoformat()
    folder = pathlib.Path(args.output or f'results/pilot-{args.date}-n{args.every_n_blocks}')
    ca = collect.parser().parse_args(['--start', args.date, '--end', end, '--output', str(folder),
                                      '--every-n-blocks', str(args.every_n_blocks), '--max-cu', str(args.max_cu),
                                      '--quota-dir', args.quota_dir])
    collect.validate_args(ca, pilot=True)
    ca.verify_replay=args.verify_replay
    load_env()
    folder.mkdir(parents=True, exist_ok=True)
    baseline_path = folder / 'pilot-cu-start.json'
    scope='pilot:USDC-WETH:'+args.date if args.max_cu_per_day is not None else None
    with QuotaClient(rpc_url(), args.quota_dir, args.max_cu, retry_uncertain=args.retry_uncertain,
                     scope=scope,scope_max_cu=args.max_cu_per_day) as meter:
        try:
            baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else dict(
                cu=meter.summary()['estimated_cu_reserved'], quota_dir=str(pathlib.Path(args.quota_dir).resolve()))
            if baseline['quota_dir'] != str(pathlib.Path(args.quota_dir).resolve()):
                raise ValueError('Resume requires the same shared quota directory')
            baseline_path.write_text(json.dumps(baseline), encoding='utf-8')
            collect.run(ca, meter)
            manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
            rows = load_rows(folder, manifest)
            market = Market(meter.rpc, manifest['first'] - 1)
            valuations = {}
            for name, b in [('initial', manifest['first'] - 1), ('final', manifest['last'])]:
                header = meter.rpc.block(b)
                valuations[name] = dict(block=b, timestamp=int(header['timestamp'], 16),
                                        day=args.date, snapshot=market.snapshot(b), candidates=[])
            summary = meter.summary()
            spent = summary['estimated_cu_reserved'] - baseline['cu']
            cu = dict(cumulative=summary['estimated_cu_reserved'], pilot=spent, days30=spent * 30, days90=spent * 90)
            report = build_report(manifest, rows, valuations, cu)
            report.update(date=args.date,pair='USDC-WETH',hardfork=manifest['hardfork'],replay_verified=manifest.get('replay_verified',False),
                          per_day_cu=summary['scope_estimated_cu_reserved'])
            (folder / 'pilot.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            text = markdown(report)
            (folder / 'PILOT.md').write_text(text, encoding='utf-8')
            if not args.quiet_report:print(text)
            print('Rapport lagret:', folder / 'PILOT.md', flush=True)
            return report
        finally:
            meter.write_summary()
            s = meter.summary()
            print('BEREGNET samlet CU-estimat:', s['estimated_cu_reserved'], '(ANTATTE satser; ikke fakturert CU)', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (RPCError, BudgetStop, RuntimeError, ValueError, FileNotFoundError) as e:
        print(type(e).__name__ + ': ' + str(e), file=sys.stderr)
        print('Ingen ferdig pilotkonklusjon. Behold cache og kvotelogg; lim inn feilen uten nøkkel.', file=sys.stderr)
        sys.exit(2)
