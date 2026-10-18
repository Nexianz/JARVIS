# Steg 1: kvotesikring — ikke en gjennomført backtest

**Dette steget installerer/tester vern. Ingen pilot eller full kjedeinnsamling er kjørt i leveransemiljøet. Ingen handelsresultater eller resultatkurver er produsert.** Følg én ting om gangen; ikke bruk de gamle 30/90-dagerskommandoene nå.

## Grensen

`--max-cu` har standard **1 500 000 estimert CU**: BEREGNET som 5 % av brukerens oppgitte 30 millioner CU. Beløpet er ikke et målt restbeløp hos Alchemy.

`cu_costs.json` har satser per metode, merket **ANTATT**. Den offentlige Alchemy-prislisten kunne ikke nås her. Arbeidssatsene er derfor uverifiserte for din plan og ganget med en ANTATT sikkerhetsfaktor på 2. Det er ikke en garanti for at virkelig fakturert CU holder seg under samme tall. Faktisk forbruk må kontrolleres i Alchemy; et eventuelt kontotak der er den uavhengige sperren.

Hvert forsøk reserverer estimert CU **før** sending. Når neste forsøk ikke får plass, stopper jobben uten å sende det. Også mislykkede kall telles konservativt. Ingen automatisk HTTP-retry omgår telleren. En ukjent metode blokkeres uten videresending; den må få en eksplisitt sats før støtte kan legges til.

`collect.py`, `preflight.py` og `rpc_setup.py --check` bruker samme varige vakt. Anvil får kun en tokenbeskyttet loopback-proxy; alle dens bakgrunnslesinger går gjennom samme teller/cache. Alchemy-variabler fjernes fra Anvil-prosessens miljø, slik at den ikke kan velge et eget endpoint fra dem. Lokale EVM-operasjoner belastes ikke som Alchemy-kall. Ingen kontrakt deployes; eventuell senere replay bruker bare lokal, engangs tilstandsoverstyring.

**Vakten gjelder disse Python-jobbene på denne maskinen.** Den måler ikke Netlify-agenten, andre programmer, andre maskiner eller allerede brukt månedskvote. Pause Netlify-agenten før vi senere kjører pilot dersom du vil unngå parallelt Alchemy-forbruk. Ikke slett kvotedatabasen for å nullstille telleren.

## Diskcache og resume

Standardmappe: `.cache/alchemy/` (ignorert av Git).

- `rpc.sqlite`: historiske svar, fulle blokker og varig CU-regnskap per metode. Verken endpoint eller nøkkel lagres.
- `cu-summary.json`: leselig oversikt over reserverte, estimerte CU, forsøk per metode, feil/ukjent levering og cachetreff. Satser er ANTATT, CU-summen BEREGNET, lokale forsøkstellere MÅLT i programmet.
- `results/.../blocks.jsonl`: fullførte evaluerings- og skip-checkpoints. Fullførte blokker behandles ikke på nytt. Kun en ufullstendig siste linje fra avbrudd kan fjernes automatisk.
- `results/.../manifest.json`: låste blokkgrenser, samplingvalg, kildekodehash, fremdrift og CU-sammendrag. Endrede parametere/kode krever ny resultatmappe, men samme kvote-/cachemappe kan gjenbrukes.

Fulle blokker hentes én gang og gjenbrukes for blokknummer, hash, header og transaksjonsliste. Et lagret, vellykket historisk svar koster ingen nye CU ved resume. Tallet gjelder den samme bevarte cachen; ved sletting, korrupsjon eller endrede RPC-parametere kan vi ikke love gjenbruk.

**Viktig grense for «aldri to ganger»:** Et nettverksavbrudd kan skje etter at Alchemy utførte kallet, men før svaret ble lagret. Ingen klient kan da vite sikkert om data ble levert/fakturert. Koden stopper og **gjentar ikke automatisk** slike kall. `--retry-uncertain` er et eksplisitt valg som kan gi gjentatt henting og ny CU-reservasjon; det er ikke en vanlig resume-kommando vi ber deg kjøre nå.

Grensen er kumulativ i databasen. Å starte programmet igjen nullstiller ikke budsjettet. Å øke `--max-cu` er en eksplisitt økning av samme totale estimerte ramme. Endring av CU-prisprofil uten migrering av regnskapet avvises.

## Sampling og Swap-filter

`--every-n-blocks N` velger deterministisk hver N-te evalueringsblokk fra periodens første blokk. Standard er 1; **vi har ennå ikke valgt en pilot- eller fullperiode-sampling for deg**.

Før dyr quote-/EVM-evaluering må de aktuelle poolene ha minst ett Swap-event i **forrige blokk, b−1**. Filteret bruker ikke events i b for å bestemme om et signal skal undersøkes: det ville gitt look-ahead bias. Etter at en kandidat er funnet/simulert, leses b sine events til konkurranseindikatoren.

Loggkall grupperes i maksimalt ti blokker for å begrense størrelse og bedre passe begrensninger på gratistjenester. Selv om en loggchunk inneholder flere blokker, bruker filteret bare medlemskap for akkurat b−1. Manglende/inkonsistente loggsvar gir stopp, aldri et oppdiktet «ingen aktivitet».

Checkpoints skiller:

- `sampling_skipped`: BEREGNET utelatt av sampling, ikke målt som ulønnsom.
- `no_prior_swap`: ingen Swap-events returnert for b−1 i de utvalgte poolene.
- `evaluated`: faktisk quotes/replay-evaluert blokk.

Sampling og Swap-filter kan overse muligheter, blant annet mellom prøver og ved andre typer likviditetsendringer. Det er ikke lov å ekstrapolere overskudd eller hevde «ingen arbitrasje i hele perioden» fra utvalget. Den gamle fullrapportgeneratoren avviser foreløpig slike datasett fremfor å fylle ut manglende PnL. Pilot- og fullrapportering må valideres i de senere stegene.

## Kontrollert nå

Kun offline-tester med syntetiske RPC-svar: forhåndsstopp ved grense, regnskap over resume, cache på tvers av header/fullblokk/hash, feil-CU, usikker levering, gateway, ingen nøkler i cache/logg og b−1-filter uten look-ahead. Disse testene sier ingenting om historisk avkastning.

Det er ikke gjort noen Alchemy-forespørsel, Anvil-kjøring eller smartkontraktdeploy under steg 1. Replay-forutsetninger på din Windows-maskin er ikke bekreftet; de må avklares før den ene pilotkommandoen gis. Ingen pilotkommando eller fullkjøringskommando er gitt i dette steget.
