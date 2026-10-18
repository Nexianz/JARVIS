# Døgnpilot på Windows — ingen handler med ekte penger

Kjør én ting om gangen med veiledningen i chatten. Fullkjøring er ikke neste steg før pilotresultatet er vurdert.

Forutsetninger: Netlify-agent pauset, ny nøkkel bare i lokal `.env`, kvotetester bestått, Anvil/Forge tilgjengelig i **samme PowerShell-vindu**, `forge build` og `preflight.py` bestått. Ingen Ubuntu/WSL er nødvendig med Foundrys Windows-utgave. Gamle nøkler fra ZIP/chat må tilbakekalles.

Etter at siste kode er hentet i JARVIS-mappen, er pilotkommandoen:

```powershell
python pilot.py --date 2025-06-01 --every-n-blocks 60 --max-cu 1500000
```

Dette dekker 1. juni 2025 UTC, med neste dato som eksklusiv slutt. Antall blokker hentes fra faktiske tidsstempler, ikke et fast anslag på 7200. Hver 60. blokk vurderes, og bare hvis poolene hadde Swap-events i **forrige** blokk. Ingen utvalgsprofitt skaleres opp til hele døgnet.

Alle Alchemy-lesinger, også Anvils arkivlesinger, går gjennom samme varige cache/kvotevakt som preflight. `1500000` er et **kumulativt beregnet** tak med allerede registrerte forsøk medregnet. Satsene og sikkerhetsfaktoren er **ANTATT**, ikke verifisert Alchemy-fakturering. Kontroller faktisk forbruk i Alchemy også. Ikke kjør andre jobber mot samme kvotelogg under piloten.

Ved avbrudd: behold `.cache/alchemy` og `results`. Samme kommando fortsetter fra lagrede blokker. Ukjent levering etter nettverksfeil stopper uten automatisk repetisjon; ikke legg til `--retry-uncertain` uten å undersøke feilen. Kode- eller parameterendringer kan kreve en ny resultatmappe, men behold alltid delt kvotedatabase/cache. Et ufullført døgn får ingen ferdig resultatrapport eller 30/90-dagersframskrivning.

Rapportene lagres i `results/pilot-2025-06-01-n60/PILOT.md` og `pilot.json`. Ikke forveksle denne filen i repository-roten med den genererte rapporten. Rapporten skriver også innholdet til terminalen. Lim inn terminalresultatet, aldri `.env` eller endpoint med nøkkel.

Rapporten viser:

- **MÅLT:** historiske blokkdata, pooltilstand/avgifter, Aave-premie, Swap-events og Norges Bank USD/NOK er inngangsdata. Ingen standardverdi erstatter manglende gas/FX.
- **BEREGNET:** simulerte route/block-muligheter, lokal EVM-gas, konkurranseproxy og CU-estimater for pilot/30/90 like døgn med samme sampling. Framskrivningen antar lik aktivitet og inkluderer oppstart/cache-effekter.
- **BEREGNET med ANTATTE utfall:** flash loan / egenkapital, privat/offentlig innsending og builder-andeler 80/90/95/99 %. Risikogrenser håndheves. Privat bundle som reverterer utelates uten gasbetaling; offentlig modellrevert betaler simulert gas. Inkludering, ekstra feil og profittreduksjon er antakelser, ikke målte seire eller feil.

En konkurransematch krever samme transaksjon med begge pool-legger i riktig retning i neste blokk. Dette er en konservativ proxy. Vi kan ikke fastslå at hver match var lønnsom arbitrasje, eller at manglende match betyr at vi ville vunnet. Rapporten viser en modellbane, ikke en prognose. Ingen lønnsomhetskonklusjon for alle døgnet sine blokker er gyldig ved denne samplingen.

Full 30/90-dagers studie, kalibrering, walk-forward og Monte Carlo inngår ikke i piloten. Periode og sampling må vurderes og godkjennes etter pilotresultatet. Ingen fullkjøring startes automatisk.

Verifisering i leveransemiljøet: offline tester med syntetiske fixtures; ingen ekte Alchemy-pilot kjørt der. Brukerens Windows-preflight har bekreftet historiske data, begge lokale replay-moduser og USD/NOK. Dette er ingen historisk avkastningsmåling.
