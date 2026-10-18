"""Validates completeness before reporting. No invented observations or fallback data."""
import argparse,json,pathlib,random,csv,statistics,dataclasses,html,hashlib,datetime
from model import *
from market import timestamp

def validate(folder):
    folder=pathlib.Path(folder);m=json.loads((folder/'manifest.json').read_text())
    if not m['complete'] or m['status']!='COLLECTED' or m['smoke_only']:raise ValueError('Incomplete/smoke-only collection is NOT a valid backtest')
    if timestamp(m['end_exclusive'])-timestamp(m['start'])<30*86400:raise ValueError('Minimum 30 days')
    rows=[json.loads(x) for x in (folder/'blocks.jsonl').read_text().splitlines() if x.strip()]
    if len(rows)!=m['last']-m['first']+1:raise ValueError('Missing/duplicate block rows')
    for i,r in enumerate(rows):
        if r['block']!=m['first']+i or r['state_block']!=r['block']-1:raise ValueError('Noncontiguous/wrong historical state')
        if i and r['parent']!=rows[i-1]['hash']:raise ValueError('Broken chain')
        if i and r['timestamp']<=rows[i-1]['timestamp']:raise ValueError('Nonmonotonic timestamps')
        if not 0<=r['tip_prior_wei'] or not 0<=r['tip_current_measured_wei']:raise ValueError('Missing tips')
    if not rows:raise ValueError('No data')
    return m,rows

def csv_write(path,rows):
    if not rows:return
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def plot_svg(path,results,capital):
    # Only called on validated real data, never on demo fixtures.
    w,h=1100,450;allv=[capital]+[r['equity_nok'] for x in results for r in x['curve']]
    lo,hi=min(allv),max(allv);span=max(hi-lo,1);colors=['#b91c1c','#1d4ed8','#15803d'];lines=[]
    for idx,res in enumerate(results):
        vals=[capital]+[r['equity_nok'] for r in res['curve']]
        pts=' '.join(f'{70+i*(w-100)/max(len(vals)-1,1):.2f},{h-65-(v-lo)*(h-130)/span:.2f}' for i,v in enumerate(vals))
        lines.append(f'<polyline points="{pts}" fill="none" stroke="{colors[idx]}" stroke-width="2"/>')
        lines.append(f'<text x="80" y="{30+idx*20}" fill="{colors[idx]}">{html.escape(res["assumptions"]["name"])} — BEREGNET</text>')
    lines.append(f'<text x="10" y="100">{hi:.0f} NOK</text><text x="10" y="{h-65}">{lo:.0f} NOK</text>')
    lines.append(f'<text x="70" y="{h-20}">Daglige verdier fra validert datasett. BEREGNET; inkluderer ANTATTE utfall.</text>')
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><rect width="100%" height="100%" fill="white"/>'+''.join(lines)+'</svg>')

def compact(rows):
    keep={0,len(rows)-1}
    for i,r in enumerate(rows):
        if r['candidates'] or i==len(rows)-1 or rows[i+1]['day']!=r['day']:keep.add(i)
    return [r for i,r in enumerate(rows) if i in keep]

def monte_carlo(rows,m,n,mode,channel,seed,min_net):
    rng=random.Random(seed);fast=compact(rows);final=[];delta=[];pnl=[]
    # Entire-run parameter draws preserve persistent regime uncertainty. Not independent certainty per block.
    for i in range(n):
        s=Assumptions(name='MonteCarlo',private_inclusion=rng.uniform(.01,.50),public_inclusion=rng.uniform(.80,1.),failure=rng.uniform(.02,.25),adverse_profit_haircut=rng.uniform(.02,.25),bid=rng.uniform(.80,.99),minimum_net_nok=min_net)
        r=simulate(fast,m,s,mode,channel,seed+i,record_curve=False)
        final.append(r['final_nok']);delta.append(r['incremental_vs_hold_nok']);pnl.append(r['strategy_pnl_trade_fx_nok'])
    return dict(status='BEREGNET betinget på ANTATTE priorer; ikke empirisk sannsynlighet',runs=n,final_nok_p05=quantile(final,.05),final_nok_p50=quantile(final,.5),final_nok_p95=quantile(final,.95),vs_hold_p05=quantile(delta,.05),vs_hold_p50=quantile(delta,.5),vs_hold_p95=quantile(delta,.95),fraction_above_initial=sum(x>m['capital_nok'] for x in final)/n,fraction_beating_hold=sum(x>0 for x in delta)/n,fraction_trading_pnl_positive=sum(x>0 for x in pnl)/n)

def walkforward(rows,m,mode,channel,seed):
    days=sorted(set(r['day'] for r in rows));split=days[max(1,len(days)//3)];train=[r for r in rows if r['day']<split];test=[r for r in rows if r['day']>=split]
    # Fit exactly one trading parameter on training only. Risk limits and MC prior ranges are NOT fitted.
    trials=[]
    for floor in [1.,2.,5.]:
        s=dataclasses.replace(SCENARIOS['realistisk'],minimum_net_nok=floor)
        results=[simulate(compact(train),m,s,mode,channel,seed+i,False)['incremental_vs_hold_nok'] for i in range(8)]
        trials.append((statistics.mean(results),floor))
    best=max(trials,key=lambda x:(x[0],x[1]));chosen=dataclasses.replace(SCENARIOS['realistisk'],minimum_net_nok=best[1])
    result=simulate(test,m,chosen,mode,channel,seed+1000)
    return dict(status='BEREGNET walk-forward; kalibrering bruker ANTATT modell, ikke observerte egne handler',train_start=days[0],train_end=train[-1]['day'],test_start=split,test_end=days[-1],chosen_min_net_nok=best[1],train_scores=trials,heldout=result),test

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--input',default='results/run');ap.add_argument('--mc',type=int,default=1000);ap.add_argument('--seed',type=int,default=20261018);a=ap.parse_args()
    if a.mc<1000:raise ValueError('At least 1000 Monte Carlo runs required')
    m,rows=validate(a.input);out=pathlib.Path(a.input)/'analysis';out.mkdir(exist_ok=True)
    allresults=[];sens=[];walk={};mc={}
    for mode in ['A','B']:
        for channel in ['private','public']:
            scenario_results=[]
            for name,s in SCENARIOS.items():
                r=simulate(rows,m,s,mode,channel,a.seed);allresults.append(r);scenario_results.append(r)
                stem=f'{mode}-{channel}-{name}'
                csv_write(out/f'equity-{stem}.csv',r['curve']);csv_write(out/f'events-{stem}.csv',r['events'])
            plot_svg(out/f'equity-{mode}-{channel}.svg',scenario_results,m['capital_nok'])
            for bid in [.80,.90,.95,.99]:
                r=simulate(rows,m,dataclasses.replace(SCENARIOS['realistisk'],bid=bid),mode,channel,a.seed)
                sens.append(dict(mode=mode,channel=channel,bid=bid,final_nok=r['final_nok'],vs_hold_nok=r['incremental_vs_hold_nok'],wins=r['counts'].get('wins',0),failed=r['counts'].get('failed',0)))
            key=f'{mode}-{channel}';w,test=walkforward(rows,m,mode,channel,a.seed);walk[key]=w
            mc[key]=monte_carlo(test,m,a.mc,mode,channel,a.seed,w['chosen_min_net_nok'])
            csv_write(out/f'equity-heldout-{key}.csv',w['heldout']['curve'])
    csv_write(out/'bid-sensitivity.csv',sens)
    output=dict(schema=1,manifest=m,results=allresults,bid_sensitivity=sens,walk_forward=walk,monte_carlo_heldout=mc,labels={'chain_blocks_reserves_fee_tiers_premium_priority_percentiles_swap_events':'MÅLT — Ethereum mainnet','fx':'MÅLT — Norges Bank, ikke kjeden','local_fork_profit_gas_and_competition_proxy':'BEREGNET fra MÅLT kjedetilstand','portfolio_drawdown_counts_mc_and_walk_forward':'BEREGNET, betinget på ANTATTE utfall','initial_capital_limits_bid_capture_failure_haircut_conversion_costs':'ANTATT','priority_fee_of_our_transaction':'ANTATT bud fra MÅLT forrige-blokkmedian; ikke observert egen transaksjon'})
    (out/'results.json').write_text(json.dumps(output,indent=2,ensure_ascii=False))
    report=['# Historisk arbitrasje-backtest','',f'Periode {m["start"]} til {m["end_exclusive"]} (slutt eksklusiv); antall blokker **MÅLT**: {len(rows)}.',
      '', '**Dette er en kontrafaktisk simulering. Ingen faktisk egen handel eller realisert avkastning er målt.**',
      '', 'MÅLT: blokkhoder, historiske eth_call-svar, Chainlink-observasjoner og swap-events. USD/NOK er MÅLT hos Norges Bank. BEREGNET: fork-gass/profitt og alle porteføljeutfall. ANTATT: startkapital, grenser, bud, inklusjon, feil og adverse execution.',
      '', 'Alle tall i tabellen under er **BEREGNET**, betinget på **ANTATTE** scenarioer. Både kursavkastning og strategiens bidrag vises. Hold-referansen har samme startfordeling og etableringskostnad.',
      '', '|Scenario|Modus / kanal|Slutt NOK|Mot hold NOK|Handels-PnL ved handels-FX NOK|Maks DD %|Mulighetsblokker|Tatt-proxy|Vunnet|Feilet|Gass NOK|Builder NOK|', '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in allresults:
        c=r['counts'];report.append(f'|{r["assumptions"]["name"]}|{r["mode"]} / {r["channel"]}|{r["final_nok"]:.2f}|{r["incremental_vs_hold_nok"]:.2f}|{r["strategy_pnl_trade_fx_nok"]:.2f}|{r["max_drawdown_fraction"]*100:.2f}|{c.get("opportunity_blocks",0)}|{c.get("taken_by_other_proxy",0)}|{c.get("wins",0)}|{c.get("failed",0)}|{r["gas_nok_at_trade_fx"]:.2f}|{r["builder_bid_nok_at_trade_fx"]:.2f}|')
    report+=['','## Walk-forward og Monte Carlo','', 'Første tredel av kalenderdagene brukes bare til valg av minimumsprofitt. Siste to tredeler er holdout og starter med ny, ANTATT kapital på 5000 NOK (eller kapitalparameteren). Det er modellkalibrering, ikke kalibrering mot observerte egne fills. Se results.json for treningsscore og testresultat. Ingen holdout-data velger terskelen.','', 'Alle verdier i neste tabell er **BEREGNET**. Intervallene uttrykker de valgte **ANTATTE** priorene og er ikke objektive konfidensintervaller for fremtidig avkastning.','', '|Modus / kanal|Kjøringer|Slutt NOK p05 / median / p95|Andel over start|Andel bedre enn hold|','|---|---:|---|---:|---:|']
    for k,v in mc.items():report.append(f'|{k}|{v["runs"]}|{v["final_nok_p05"]:.2f} / {v["final_nok_p50"]:.2f} / {v["final_nok_p95"]:.2f}|{v["fraction_above_initial"]:.1%}|{v["fraction_beating_hold"]:.1%}|')
    realistic=[r for r in allresults if r['assumptions']['name']=='realistisk']
    report+=['','## Konklusjon','']
    for r in realistic:
        p=r['strategy_pnl_trade_fx_nok'];word='overskudd' if p>.01 else 'tap' if p<-.01 else 'omtrent ingenting'
        report.append(f'- {r["mode"]} / {r["channel"]}: **BEREGNET {word} fra handel og etablering**, {p:.2f} NOK ved handelsdagens valutakurs. Sluttverdi {r["final_nok"]:.2f} NOK inkluderer også markedsbevegelse i beholdningen.')
    report+=['','Sikkerhet: høy om de validerte kjedeobservasjonene; begrenset om kontrafaktisk inklusjon, reverteringer og builder-bud. Dette kan ikke bevise at vi faktisk ville vunnet. Et nullfunn gjelder bare valgte ruter, størrelsesgrenser og periode.','', '## Begrensninger som påvirker tolkningen','', '- Konkurranse: samme transaksjon med swap i begge ruteretningene er en konservativ **BEREGNET proxy**, ikke bevist arbitrørfortjeneste. Aggregerte kundeswapper kan feiltolkes; separate transaksjoner/private tapende bud kan overses. Slike treff behandles som tap for oss.','- Priority fee finnes ikke som ett universelt tall per blokk. For hver blokk lagres gas-vektet median fra feeHistory eller verifiserte historiske kvitteringer. Budet vårt bruker bare forrige blokks median; dagens median er diagnostikk. Faktisk builder-bud er ukjent.','- EVM kjører hele lånet, begge swappene, tilbakebetaling, minProfit og en liten coinbase-betaling på lokal fork med state b−1. Beløpet på betalingen er ANTATT i økonomimodellen; fast ikke-null betaling måler betalingsbanens gass. Neste tidsstempel antas til forrige +12 sekunder og coinbase fra forrige blokk; faktisk ordre inne i b er ikke rekonstruert.','- Andre handler i b og vår påvirkning av senere blokker er ikke spilt om i global kjedehistorikk. Adverse haircut og feilrate er ANTATTE. Resultatet er en betinget historisk kontrafaktisk modell, ikke et bevis på realisert PnL.','- Offentlig kollisjon antas å gi revert med målt lokal sen-revert-gass; andre feil kan koste annerledes. Private ikke-inkluderte bundles koster null.','- V2 prisimpact er heltallsberegnet fra reelle reserver med protokollens faste 0,30 % swapgebyr. V3 QuoterV2 bruker faktiske ticks, likviditet og kontrollerte fee tiers; V3 har ikke V2-reserver.','- Størrelsen er numerisk søkt innenfor likviditets- og lånerammer, ikke matematisk bevist globalt optimal. Egenkapital velger beste simulerte størrelse fra fire kapitalrammer; redusert saldo kan gi underutnyttelse. Ingen reinvestering utover opprinnelig hovedstolsramme.','- Etter en simulert gevinst sperres gjenbruk av samme historisk uendrede pooltilstand. Dette hindrer gjentatt fantomprofitt, men erstatter ikke en full omskriving av den senere kjeden.',
      '- Gass-lommeboken etterfylles ikke automatisk. USDC-gevinster beholdes. Modus B starter med ANTATT 20 % ETH til gass, 80 % USDC til handel. Modus A starter helt i ETH; flash loan-hovedstol er ikke egen kapital.','- Etableringskostnad ANTATT 0,30 %. Onramp, skatter, RPC-abonnement, maskinvare og revisjon er ikke tatt med; netto etter slike kostnader kan bare være lavere. Ubenyttet NOK ville unngått beholdningsrisiko.','- Sikkerhetsbuffer er et krav til gjenværende overskudd, ikke en oppdiktet kontantutgift. Alle risikogrenser og priorer finnes i results.json. Se README.md for smartkontrakt- og nøkkelrisiko.','', 'Fullstendige BEREGNEDE tellerverdier, gassenheter, ETH-kostnader, daglige NOK-kurver og bud-sensitivitet finnes i CSV/JSON.']
    (out/'REPORT.md').write_text('\n'.join(report),encoding='utf-8')
    print('Written validated historical analysis to',out)
if __name__=='__main__':main()
