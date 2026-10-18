"""Preview a historical batch without RPC. Only --run starts the approved dates.

Every pilot shares the same persistent ledger, global cap and per-date scopes.
No real transaction, wallet or deployment.
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import math
import pathlib
import sqlite3
import sys
import urllib.parse

import pilot
from chain import BudgetStop, RPCError
from hardforks import hardfork_for_range
from market import timestamp

TOTAL_LIMIT = 10_000_000
DEFAULT_DATES = '2025-03-10,2025-04-09,2025-06-19,2025-07-29,2025-08-22,2025-10-10,2026-01-24,2026-02-05'


def dates_list(text):
    dates = [datetime.date.fromisoformat(x.strip()).isoformat() for x in text.split(',')]
    if not dates or len(dates) != len(set(dates)):
        raise ValueError('Dates must be nonempty and unique; do not count the same day twice')
    if dates != sorted(dates):
        raise ValueError('Dates must be in chronological order')
    for date in dates:
        hardfork_for_range(timestamp(date), timestamp(date) + 86400)
    return dates


def ledger_used(directory):
    path = pathlib.Path(directory).resolve() / 'rpc.sqlite'
    if not path.exists():
        return 0
    # Read-only inspection; preview neither initializes the ledger nor loads .env.
    with contextlib.closing(sqlite3.connect('file:' + urllib.parse.quote(path.as_posix(), safe='/:') + '?mode=ro', uri=True)) as db:
        return db.execute('SELECT COALESCE(SUM(cu),0) FROM attempts').fetchone()[0]


def make_plan(args):
    dates = dates_list(args.dates)
    if args.every_n_blocks < 1 or not 0 < args.max_total_cu <= TOTAL_LIMIT or not 0 < args.max_cu_per_day <= args.max_total_cu:
        raise ValueError('Positive sampling/limits required; total cumulative cap cannot exceed 10,000,000 CU')
    reference = json.loads(pathlib.Path(__file__).with_name('batch_reference.json').read_text(encoding='utf-8'))
    profile=json.loads(pathlib.Path(__file__).with_name('cu_costs.json').read_text(encoding='utf-8'))
    if reference['cu_profile_sha256']!=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest():
        raise ValueError('CU rates changed; recalibrate the planning reference instead of reusing an incompatible estimate')
    base_day = math.ceil(reference['estimated_pilot_cu'] * reference['every_n_blocks'] / args.every_n_blocks)
    cushion_day = math.ceil(base_day * 1.25)
    used = ledger_used(args.quota_dir)
    return dict(dates=dates,pair='USDC-WETH',every_n_blocks=args.every_n_blocks,
                per_day_limit=args.max_cu_per_day,total_cumulative_limit=args.max_total_cu,
                already_reserved=used,remaining=max(0,args.max_total_cu-used),base_per_day=base_day,
                base_batch=base_day*len(dates),planning_margin='ANTATT 25%',
                planning_per_day=cushion_day,planning_batch=cushion_day*len(dates),
                planning_cumulative=used+cushion_day*len(dates),
                reference=reference,quota_dir=str(pathlib.Path(args.quota_dir).resolve()),
                hardforks={d:hardfork_for_range(timestamp(d),timestamp(d)+86400) for d in dates})


def print_plan(plan):
    print('BEREGNET CU-estimat fra ANTATTE satser; ikke fakturert Alchemy-forbruk.',flush=True)
    print('Dato | hardfork | basis CU | CU med ANTATT 25% margin | dagstak (ANTATT)',flush=True)
    for d in plan['dates']:
        print(f'{d} | {plan["hardforks"][d]} | {plan["base_per_day"]} | {plan["planning_per_day"]} | {plan["per_day_limit"]}',flush=True)
    print(f'BEREGNET batch: {plan["base_batch"]}; med margin {plan["planning_batch"]}; allerede reservert {plan["already_reserved"]}.',flush=True)
    print(f'BEREGNET samlet etter plan: {plan["planning_cumulative"]}; kumulativ grense {plan["total_cumulative_limit"]}.',flush=True)
    if plan['planning_batch']>plan['remaining'] or plan['planning_per_day']>plan['per_day_limit']:
        print('ADVARSEL: planleggingsestimatet overskrider tilgjengelig tak; kjøringen kan ikke forventes fullført innen grensene.',flush=True)
    print('Lineær skalering fra én null-kandidat-pilot er usikker, særlig ved aktive ruter. Taket stopper før nye RPC-reservasjoner.',flush=True)


def aggregate(plan, reports, statuses):
    daily = []
    for date in plan['dates']:
        report = reports.get(date)
        baseline=[r for r in report['sensitivity'] if r['channel']=='private' and r['assumptions']['bid']==.95] if report else []
        daily.append(dict(date=date,status=statuses.get(date,'NOT_RUN'),
                          selected_blocks=report['selected_blocks'] if report else None,
                          opportunities=report['raw_opportunities'] if report else None,
                          per_day_cu=report.get('per_day_cu') if report else None,
                          private95={r['mode']:dict(net_nok=r['incremental_vs_hold_nok'],gas_nok=r['gas_nok_at_trade_fx'],builder_nok=r['builder_bid_nok_at_trade_fx']) for r in baseline}))
    totals = dict(complete_days=len(reports),selected_blocks=sum(r['selected_blocks'] for r in reports.values()),
                  opportunities={m:sum(r['raw_opportunities'][m]['route_block_opportunities'] for r in reports.values()) for m in ('A','B')},
                  competitor_proxy={m:sum(r['raw_opportunities'][m]['competitor_proxy'] for r in reports.values()) for m in ('A','B')})
    sensitivity = []
    for mode in ('A','B'):
        for channel in ('private','public'):
            for bid in (.8,.9,.95,.99):
                if not reports:continue
                runs = [x for r in reports.values() for x in r['sensitivity'] if x['mode']==mode and x['channel']==channel and x['assumptions']['bid']==bid]
                sensitivity.append(dict(mode=mode,channel=channel,bid=bid,
                    net_vs_hold_nok=sum(x['incremental_vs_hold_nok'] for x in runs),
                    gas_nok=sum(x['gas_nok_at_trade_fx'] for x in runs),
                    builder_nok=sum(x['builder_bid_nok_at_trade_fx'] for x in runs),
                    gas_units=sum(x['counts'].get('gas_units',0) for x in runs),
                    wins=sum(x['counts'].get('wins',0) for x in runs),
                    failed=sum(x['counts'].get('failed',0) for x in runs)))
    return dict(plan=plan,daily=daily,totals=totals,sensitivity=sensitivity,
                cu_reserved_now=ledger_used(plan['quota_dir']),
                labels=dict(chain='MÅLT historical mainnet input',counts='BEREGNET for selected observations only',
                            economics='BEREGNET conditional on ANTATTE outcomes',cu='BEREGNET from ANTATTE method costs'),
                warning='Each date is an independent 5000 NOK experiment. Sums are diagnostics, NOT one portfolio return or an equity curve.')


def table(result):
    lines = ['# Batchpilot — USDC/WETH', '',
             'BEREGNET fra MÅLTE kjededata og ANTATTE modellutfall. Ikke en faktisk handelslogg.', '',
             '| Dato | Status | Vurderte blokker | Muligheter A/B | Konkurranseproxy A/B | Netto NOK A/B (privat 95 %) | CU-estimat for dato |',
             '|---|---|---:|---:|---:|---:|---:|']
    for r in result['daily']:
        if r['opportunities'] is None:
            lines.append(f'| {r["date"]} | {r["status"]} | — | — | — | — | se kvotelogg |')
            continue
        op=r['opportunities']
        lines.append(f'| {r["date"]} | {r["status"]} | {r["selected_blocks"]} | {op["A"]["route_block_opportunities"]}/{op["B"]["route_block_opportunities"]} | '
                     f'{op["A"]["competitor_proxy"]}/{op["B"]["competitor_proxy"]} | '
                     f'{r["private95"]["A"]["net_nok"]:.2f}/{r["private95"]["B"]["net_nok"]:.2f} | {r["per_day_cu"]} |')
    t=result['totals']
    nets={m:sum(r['private95'][m]['net_nok'] for r in result['daily'] if r['opportunities'] is not None) for m in ('A','B')}
    net_text=f'{nets["A"]:.2f}/{nets["B"]:.2f}' if t['complete_days'] else '—'
    lines += [f'| TOTALT fullførte datoer | {t["complete_days"]} | {t["selected_blocks"]} | {t["opportunities"]["A"]}/{t["opportunities"]["B"]} | '
              f'{t["competitor_proxy"]["A"]}/{t["competitor_proxy"]["B"]} | {net_text} | {result["cu_reserved_now"]} kumulativt |', '',
              'Kjedeinnganger er MÅLT; alle tellinger og CU er BEREGNET. CU-satser, utvalg og risikogrenser er ANTATT. '
              'Ufullførte datoer utelates fra resultatssummer, ikke behandlet som null muligheter.', '',
              '## BEREGNET sensitivitet med ANTATTE utfall — summer av uavhengige døgn', '',
              '| Modus | Kanal | ANTATT builder | Netto mot hold NOK | Gas NOK | Builder NOK | Gas-enheter | Modellvinner | Modellrevert |',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for s in result['sensitivity']:
        lines.append(f'| {s["mode"]} | {s["channel"]} | {s["bid"]:.0%} | {s["net_vs_hold_nok"]:.2f} | {s["gas_nok"]:.2f} | {s["builder_nok"]:.2f} | {s["gas_units"]} | {s["wins"]} | {s["failed"]} |')
    lines += ['', 'Hver dato starter med en separat ANTATT portefølje på 5000 NOK. Summer er ikke avkastningen til én '
              'portefølje, og sluttverdier legges ikke sammen til en egenkapitalkurve. Dag/uketapsgrenser gjelder innen hvert døgnforsøk; '
              'en sammenhengende uke eller kapitalbane er ikke modellert på tvers av de spredte datoene.', '',
              '## Konklusjon og begrensninger', '']
    if not t['complete_days']:
        lines.append('Ingen døgn fullført; ingen resultatkonklusjon kan trekkes.')
    elif t['opportunities']['A']+t['opportunities']['B']==0:
        lines.append('Ingen positive EVM-kandidater funnet i det fullførte utvalget. Ingen arbitrasjeinntekt er vist. Dette beviser ikke fravær av muligheter mellom utvalgsblokkene.')
    else:
        lines.append('Positive EVM-kandidater finnes i utvalget. Netto i tabellen er betinget på antakelser om inkludering og feil; dette er ikke dokumentasjon på realiserbar lønnsomhet.')
    lines += ['', 'Utvalgte store prisbevegelser gir seleksjonsskjevhet; liten dagsendring beviser ikke lav intradagvolatilitet. '
              'Hver 20. blokk og forrige-blokk-Swap-filteret utelater muligheter. Konkurranseproxyen beviser verken lønnsom '
              'arbitrasje hos andre eller at vi ville vunnet blokkplassen. Lokal replay antar plass først i blokken. '
              'Ingen empirisk gevinstsannsynlighet, kontinuerlig 30-dagers backtest, Monte Carlo eller walk-forward er produsert. '
              'Modellert NOK-verdi kan endre seg uten handler. Faktisk Alchemy-fakturering må sjekkes hos Alchemy. '
              'Kun de fire eksisterende USDC/WETH-poolene inngår; WBTC/USDC og DAI/USDC inngår ikke. '
              'Ingen ekte penger, wallet eller deploy brukes.']
    return '\n'.join(lines)+'\n'


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dates',default=DEFAULT_DATES)
    ap.add_argument('--every-n-blocks',type=int,default=20)
    ap.add_argument('--max-cu-per-day',type=int,default=1_200_000)
    ap.add_argument('--max-total-cu',type=int,default=TOTAL_LIMIT)
    ap.add_argument('--quota-dir',default='.cache/alchemy')
    ap.add_argument('--output',default='results/batch-n20')
    ap.add_argument('--run',action='store_true',help='Run only after reviewing estimates and approving dates')
    args=ap.parse_args(argv)
    plan=make_plan(args);print_plan(plan)
    if not args.run:
        print('PREVIEW ONLY: no RPC, no .env read, no simulation. Review/approve dates before --run.',flush=True)
        return 0
    if plan['already_reserved']>=plan['total_cumulative_limit']:
        raise ValueError('Total cumulative CU ceiling already reached; do not delete/reset the ledger')
    folder=pathlib.Path(args.output);folder.mkdir(parents=True,exist_ok=True)
    config={k:plan[k] for k in ('dates','pair','every_n_blocks','per_day_limit','total_cumulative_limit','quota_dir')}
    config['source_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in list(pathlib.Path('.').glob('*.py'))+list(pathlib.Path('contracts').glob('*.sol'))+[pathlib.Path('cu_costs.json'),pathlib.Path('batch_reference.json'),pathlib.Path('foundry.toml')]}
    artifact=pathlib.Path('out/Replay.sol/Replay.json')
    config['artifact_sha256']=hashlib.sha256(artifact.read_bytes()).hexdigest() if artifact.exists() else None
    path=folder/'batch-config.json'
    if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=config:
        raise ValueError('Batch settings/source changed. Use a new output folder; keep shared quota/cache')
    path.write_text(json.dumps(config,indent=2),encoding='utf-8')
    reports={};statuses={};exitcode=0
    try:
        for date in plan['dates']:
            daily_folder=folder/date
            existing=daily_folder/'pilot.json'
            if existing.exists():
                report=json.loads(existing.read_text(encoding='utf-8'))
                manifest=json.loads((daily_folder/'manifest.json').read_text(encoding='utf-8'))
                pilot.load_rows(daily_folder,manifest)
                if report.get('date')!=date or report.get('every_n_blocks')!=args.every_n_blocks or not report.get('replay_verified'):
                    raise ValueError('Mismatched/unverified existing date report')
                reports[date]=report;statuses[date]='COMPLETE (cached)'
            else:
                statuses[date]='INCOMPLETE'
                reports[date]=pilot.main(['--date',date,'--every-n-blocks',str(args.every_n_blocks),
                    '--max-cu',str(args.max_total_cu),'--max-cu-per-day',str(args.max_cu_per_day),
                    '--quota-dir',args.quota_dir,'--output',str(daily_folder),'--verify-replay','--quiet-report'])
                statuses[date]='COMPLETE'
            result=aggregate(plan,reports,statuses)
            (folder/'BATCH.md').write_text(table(result),encoding='utf-8')
            (folder/'batch.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
            print('Fullført:',date,'; BEREGNET blokker',reports[date]['selected_blocks'],flush=True)
    except (RPCError,BudgetStop,RuntimeError,ValueError,OSError) as e:
        print(type(e).__name__+': '+str(e),file=sys.stderr)
        print('Batch stopped. No automatic retries or later dates after an error/limit.',file=sys.stderr)
        exitcode=2
    except KeyboardInterrupt:
        print('Avbrutt; checkpoints beholdes. Ingen automatisk fortsettelse.',file=sys.stderr);exitcode=130
    finally:
        result=aggregate(plan,reports,statuses)
        (folder/'batch.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
        text=table(result);(folder/'BATCH.md').write_text(text,encoding='utf-8');print(text)
        print('Rapport:',folder/'BATCH.md',flush=True)
    return exitcode


if __name__=='__main__':
    try:sys.exit(main())
    except (ValueError,OSError) as e:
        print(type(e).__name__+': '+str(e),file=sys.stderr);sys.exit(2)
