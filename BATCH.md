# Godkjent batchpilot: åtte separate døgn

Brukeren har godkjent datoene og takene nedenfor. Ingen kjedeinnsamling for batchen er kjørt i leveransemiljøet; kun offline tester og innhenting av eksterne daglige ETH-priser for datovalg. Ingen API-nøkkel er tilgjengelig her.

## Datovalg og kilde

Kilde: [Coin Metrics, historisk ETH PriceUSD](https://github.com/coinmetrics/data/blob/master/csv/eth.csv). Uttrukne kildeverdier og SHA-256 av kildefilen finnes i `batch_dates.json`. Prisene er **MÅLT hos ekstern dataleverandør**, ikke fra Ethereum-poolene. Daglige endringer under er **BEREGNET** mot forrige dags observasjon. Selve utvalget er et **ANTATT** stress-/kontrollutvalg, ikke representativt og ikke valgt etter backtestprofitten.

| Dato | BEREGNET daglig ETH-endring | Begrunnelse | EVM-regler |
|---|---:|---|---|
| 2025-03-10 | −6,75 % | stort fall | Cancun |
| 2025-04-09 | +13,04 % | stor oppgang | Cancun |
| 2025-06-19 | +0,02 % | liten nettoendring | Prague |
| 2025-07-29 | −0,001 % | liten nettoendring | Prague |
| 2025-08-22 | +14,41 % | stor oppgang | Prague |
| 2025-10-10 | −11,49 % | stort fall | Prague |
| 2026-01-24 | −0,03 % | liten nettoendring | Osaka |
| 2026-02-05 | −13,85 % | stort fall | Osaka |

Liten nettoendring er **ikke dokumentasjon på lav intradagvolatilitet**. Store daglige bevegelser er heller ingen garanti for arbitrasjemuligheter. Coin Metrics-prisene brukes bare til datovalg; pooltilstand, avgifter, Aave-premie, gass og Swap-events hentes historisk fra mainnet under kjøringen.

## Før-kjøringsestimat

Referansen er brukerens gjennomførte pilot fra 2025-06-01: 290 544 **BEREGNET** CU med hver 60. blokk. Den hadde ingen positive kandidater. Arbeidssatsene er fortsatt **ANTATT**, ikke bekreftet Alchemy-fakturering. Baseline og metodeprofil-hash ligger i `batch_reference.json`; endrede CU-satser krever ny kalibrering.

| Verdi | BEREGNET estimat fra ANTATTE satser |
|---|---:|
| Per døgn, hver 20. blokk: 290 544 × 60/20 | 871 632 CU |
| Åtte døgn | 6 973 056 CU |
| Åtte døgn med ANTATT 25 % planleggingsmargin | 8 716 320 CU |
| Med tidligere brukeroppgitt kvotelogg på 301 308 CU | 9 017 628 CU kumulativt |

**ANTATTE tak, godkjent av bruker:** 1 200 000 estimert CU per historisk dato, 10 000 000 estimert CU totalt i den delte kvoteloggen. Estimatet er ingen øvre grense: størrelseoptimalisering/EVM-replay på positive ruter kan koste mye mer enn null-kandidat-piloten. 25 % er en planleggingsmargin, ikke en statistisk sikkerhetsgrense.

Programmet leser faktisk lokalt reservert estimat fra kvoteloggen før start, så ditt nåværende tall vises. Tidligere bruk teller mot totalgrensen. Annen bruk utenfor denne kvoteloggen må kontrolleres hos Alchemy. Hvis faktisk fakturert CU avviker fra satstabellen, er ikke dette en garanti om Alchemy-kontotaket.

## Windows-kommandoer

Fra PowerShell i JARVIS, etter siste `git pull`, med Anvil på PATH og `forge build` ferdig. Netlify-agenten skal være pauset. Ingen nøkler skal limes inn i chat, kommandoer eller Git.

Bare vis estimat, uten `.env`, nettverk, simulering eller initialisering av kvotedatabase:

```powershell
python batch_pilot.py --dates 2025-03-10,2025-04-09,2025-06-19,2025-07-29,2025-08-22,2025-10-10,2026-01-24,2026-02-05 --every-n-blocks 20 --max-cu-per-day 1200000 --max-total-cu 10000000
```

Start de godkjente datoene; estimatet skrives først:

```powershell
python batch_pilot.py --dates 2025-03-10,2025-04-09,2025-06-19,2025-07-29,2025-08-22,2025-10-10,2026-01-24,2026-02-05 --every-n-blocks 20 --max-cu-per-day 1200000 --max-total-cu 10000000 --run
```

Datoene ovenfor er også standard dersom `--dates` utelates. `--run` er alltid nødvendig for å starte. Ingen full 30/90-dagers studie starter automatisk.

## Vern og gjenopptak

Batchen kaller `pilot.py` direkte for hver dato; alle jobber deler `.cache/alchemy/rpc.sqlite`. Både total- og dagstak kontrolleres i **samme SQLite-transaksjon før hvert nettverksforsøk**, også Anvils arkivlesinger. Dagstak betyr per historisk testdato, ikke datamaskinens veggklokkedag. Gamle uskopede forsøk teller fortsatt mot totaltaket. Nye forsøk får vedvarende datoidentitet; ny prosess eller ny resultatmappe nullstiller ikke dagstelleren. Cachetreff koster null. Mislykkede og usikkert leverte forsøk beholder reservasjonen. Datoer, parametere og kildekode fryses for resume.

Ved feil eller ethvert kvotetak stopper **hele batchen**, og resterende datoer får `NOT_RUN`. Ufullførte datoer utelates fra handels-/profittsummer og vises ikke som null muligheter. Behold cache, kvotelogg og resultater. Samme kommando gjenopptar uten å samle fullførte blokker på nytt; fullførte dagsrapporter gjenbrukes. Ukjent nettverkslevering krever separat gjennomgang; ingen automatisk retry. Ikke slett databasen for å få mer budsjett.

## Ny datostøtte og begrensninger

`hardforks.py` velger Cancun/Prague/Osaka etter mainnets aktiveringstidspunkter i [go-ethereum](https://github.com/ethereum/go-ethereum/blob/master/params/chainspecs/mainnet.json). Ingen av de godkjente dagene krysser en oppgradering. Dager som krysser en oppgradering avvises. Perioder fra 2026-03-01 og senere avvises inntil videre verifisering; senere nettverksregler gjettes ikke. BPO-oppgraderingene gjelder blobparametere; våre simulerte transaksjoner har ingen blobs.

Før hver dato må en lokal, målt-tilstand-basert prøve nå kontraktens sluttkontroll `minProfit` i både flash- og egenkapitalmodus. Dette tester at ruten faktisk kan eksekveres på datoen, ikke at den er lønnsom. Replay bruker lokal kode-/saldooverstyring og dummyavsender, aldri en ekte wallet eller deploy. Ny dato-/Osaka-støtte er offline-testet her; historisk integrasjon må bestå på Windows med Alchemy. Manglende data, uventet revert eller manglende Anvil-støtte stopper, uten faste erstatningsverdier.

## Rapport

`results/batch-n20/BATCH.md` og `batch.json` oppdateres etter hver fullført dato og ved avbrudd. Hver dato har dessuten egen `PILOT.md`, `pilot.json`, `manifest.json` og `blocks.jsonl` i datomappen. Samlet rapport viser dato/totalt, muligheter A/B, konkurranseproxy, CU og modellert netto, med samlet sensitivitet for privat/offentlig innsending og 80/90/95/99 % builder-bud. Fullstendige scenarioantakelser finnes i dagsrapportene.

Hver dato starter som et **uavhengig forsøk med 5000 NOK**, ikke en sammenhengende portefølje. Summer av nettoresultater er diagnostikk, ikke en egenkapitalkurve. Sluttverdier summeres ikke. Tapsgrenser virker innen hvert døgnforsøk; ingen sammenhengende uketapsbane simuleres mellom de spredte datoene. Ingen profitt skaleres fra utvalget til alle blokkene. Modellerte seire er ikke faktiske seire; konkurranseproxyen beviser ikke konkurrenters lønnsomhet eller vår prioritet hos builderen.

## Flere par

**Ikke lagt til eller blandet inn i denne kjøringen:** WBTC/USDC og DAI/USDC. Eksisterende Replay-kontrakt, fabrikkoppslag og rutekoder er spesifikke for de fire USDC/WETH-poolene. Flere par krever egen kontrakts-/ABI-endring, historisk validering av token/pool/fee-tier (inkludert relevante stablecoin-fees), egne likviditets-/risikosjekker og samme-dato-replay. En adresseendring alene gir ingen validert test. En eventuell ny kjøring må merkes som ny, holdes separat i rapporten og fortsatt inngå i det delte totale CU-taket; ingen ekstra par startes automatisk.

Ærlig status: ennå ingen batchresultater og ingen påvist lønnsomhet. Selv en positiv modelltabell kan ikke vise at vi ville vunnet kappløpet om blokkplass. Ingen Monte Carlo, walk-forward eller kontinuerlig 30-dagers studie inngår i denne batchen.
