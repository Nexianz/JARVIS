# Kjør på Windows, trinn for trinn

Fra GitHub-klonen: se [ALCHEMY.md](ALCHEMY.md) for nøkkeloppsett. Bruk `python3 rpc_setup.py` i Ubuntu-klonen eller lokal `.env`. ZIP-utpakking nedenfor er alternativet til Git-kloning.

Dette bruker Windows med WSL2/Ubuntu for Foundry/Anvil. Python-koden har ingen tredjeparts-Python-avhengigheter. Du trenger ingen wallet eller privatnøkkel. De eneste eksterne dataene er lesetilgang til Ethereum og Norges Bank.

**Les STATUS.md først:** jeg kunne ikke verifisere Solidity-kompilering, reell arkivtilgang eller EVM-integrasjonen her. Kjør derfor preflight før en lang innsamling. Hvis noe stopper, lim inn den redigerte feilen, ikke API-URL eller `.env`. Ingen historisk resultatsum skal tolkes før alle obligatoriske kontroller har bestått.

## 1. Bytt API-nøkkelen

Revoker den gamle nøkkelen hos Alchemy. Den finnes i den opprinnelige dashboard-ZIP-filen. Lag en ny app/nøkkel med **Ethereum mainnet HTTPS, archive eth_call, historiske logs og eth_feeHistory**. Kontroller historisk tilgang og abonnementets kredittgrenser. Ikke bruk en wallet-nøkkel; Alchemy-nøkkelen gir RPC-tilgang, ikke signeringsrettigheter.

## 2. Pakk ut

Last ned `ETH_Arbitrage_Historical_Backtest.zip` til Downloads. I PowerShell:

```powershell
New-Item -ItemType Directory -Force C:\arb-lab | Out-Null
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\ETH_Arbitrage_Historical_Backtest.zip" -DestinationPath C:\arb-lab
Set-Location C:\arb-lab\eth-arbitrage-backtest
Copy-Item .env.example .env
notepad .env
```

Erstatt `REPLACE_WITH_NEW_KEY` i `.env` med den nye nøkkelen. Én linje:

```text
ETH_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/REPLACE_WITH_NEW_KEY
```

Ikke lim den ferdige linjen inn i chat. `.env` skal ikke lagres i Git eller ZIP. Hvis mappen allerede finnes, bruk en ny tom utpakkingsmappe for å unngå å overskrive egne resultater.

## 3. Installer WSL2 og Foundry

Hvis WSL2 ikke allerede finnes, åpne PowerShell **som administrator**:

```powershell
wsl --install -d Ubuntu
```

Start Windows på nytt hvis installasjonen ber om det. Fullfør Ubuntus lokale brukernavn/passord. Dette er passord til din lokale Linux-bruker, ikke en Ethereum-nøkkel.

Åpne så vanlig PowerShell:

```powershell
wsl -d Ubuntu
```

De neste kommandoene er **inne i Ubuntu**:

```bash
sudo apt-get update
sudo apt-get install -y python3 curl ca-certificates git unzip
curl --fail --location --proto '=https' --tlsv1.2 https://foundry.paradigm.xyz -o /tmp/foundry-installer.sh
bash /tmp/foundry-installer.sh
export PATH="$HOME/.foundry/bin:$PATH"
foundryup --install v1.3.6
anvil --version
forge --version
python3 --version
cd /mnt/c/arb-lab/eth-arbitrage-backtest
```

Installeringsskriptet kommer fra Foundrys offisielle domene; `foundryup` henter verktøyene fra prosjektets utgivelser med standard verifikasjon. Ikke bruk `--force`, ikke slå av TLS og ikke overse en signatur-/checksum-/attestasjonsfeil. Hvis den fastsatte utgivelsen ikke kan verifiseres eller leverandøren endrer installasjonsmåten, stopp og send den redigerte feilen. Se offisiell dokumentasjon: https://getfoundry.sh/introduction/installation/ og https://github.com/foundry-rs/foundry/releases/tag/v1.3.6 .

Python må være minst 3.10. WSL2/Ubuntu 24.04 gir normalt nyere Python. Verktøypinnen og Prague-vinduet er valgt for det historiske eksemplet, ikke for å simulere alle senere mainnet-oppgraderinger.

## 4. Kompiler og kjør lokale tester

Fortsatt inne i Ubuntu, i prosjektmappen:

```bash
forge build
python3 -m unittest discover -s tests -v
python3 preflight.py --date 2025-06-01
```

`forge build` må lykkes og produsere `out/Replay.sol/Replay.json`. Solidity-kompilatoren er låst til 0.8.26 i `foundry.toml`.

Enhetstestene bruker syntetiske data og er ikke en historisk backtest. Preflight bruker ekte data: chain ID, historiske blokkdata, poolenes alder/tokens, fee tiers, reserver/V3-state, Aave-premium, priority-fees, Norges Bank og en lokal full swapsekvens i begge finansieringsformer. Preflight gir flash-harnessen en liten, lokal testreserve via storage override, slik at selv en tapsbringende testrute kan tilbakebetale og nå siste guard. Denne reserven brukes ikke i profittinnsamlingen og er aldri ekte USDC. Den bevisst umulige minProfit skal revertere **på siste minProfit-sjekk**, ikke tidligere. Bare en slik forventet lokal revert regnes som bestått. Ingen preflight-resultat er avkastningsdata.

Hvis Alchemy sier 401/403: kontroller den **nye** appen og nøkkelens restriksjoner. Ved rate-/credit-limit, reduser belastning eller bruk et egnet abonnement; ikke prøv uendelig. Ved manglende historisk state må arkivtilgang aktiveres. Skriptene faller aldri tilbake til live-priser eller mockdata.

## 5. Kjør én virkelig blokk først

```bash
python3 collect.py --start 2025-06-01 --end 2025-08-30 --smoke-blocks 1 --output results/smoke --rpc-budget 20000
```

Dette verifiserer hele innsamlingsløpet for én blokk. En smoke-test kan ikke analyseres som gyldig historisk resultat. Det er riktig at `analyze.py --input results/smoke` avviser den.

## 6. Samle 90 dager — eller start med minst 30

**Stor datamengde:** 90 dager er i størrelsesorden flere hundre tusen Ethereum-blokker. Hver blokk har flere arkivkall, og mulige ruter krever flere quotes og Anvil-arkivoppslag. Dette kan bli mange millioner forespørsler og ta dager eller mer, avhengig av maskin, faktisk aktivitet og RPC-plan. Dette er et ressursanslag, ikke en målt kjøretid eller et målt antall muligheter. API-kreditter kan koste penger; sjekk Alchemy-planen før du starter. Ingen slike innsamlinger ble gjennomført i leveransemiljøet.

For 90 dager:

```bash
python3 collect.py --start 2025-06-01 --end 2025-08-30 --output results/run90 --rpc-budget 100000
```

For en full 30-dagers studie i stedet:

```bash
python3 collect.py --start 2025-06-01 --end 2025-07-01 --output results/run30 --rpc-budget 100000
```

`--end` er eksklusiv. Hver blokk i perioden må med; programmet hopper ikke over blokker for å få en penere eller billigere test. Innsamlingen stopper ved feil, ikke med oppdiktede verdier.

`--rpc-budget` begrenser nye **direkte collector-kall i denne kjøringen**, ikke antallet Alchemy compute units, og **ikke Anvils interne arkivoppslag**. Det er derfor ikke et absolutt kostnadstak. Bruk også Alchemys kontogrense/varsler. Det er med vilje satt et moderat budsjett for å unngå en ukontrollert langtidsjobb.

Når budsjettet nås: kjør **samme kommando igjen**. Ferdige blokker og SQLite-cache gjenbrukes. Hver ny prosess har nytt kallbudsjett. Du kan øke `--rpc-budget` etter å ha kontrollert forbruk, for eksempel til 500000. Ikke slett cachen. `Ctrl+C` er tillatt; en ufullstendig siste linje kan repareres ved oppstart. Endre ikke kildekode, kapital, compiler-artifact eller periode i samme resultatmappe; provenienskontrollen krever da en ny mappe.

Hvis Norges Bank-APIet er utilgjengelig: last ned **ekte** daglig USD/NOK-CSV fra https://data.norges-bank.no/ med kolonnene `TIME_PERIOD` og `OBS_VALUE`, og ta med minst ti dager før starten for helger/helligdager. Lagre som `usd-nok.csv`, og legg til:

```bash
--fx-csv usd-nok.csv
```

Ingen fremtidig kurs brukes for en tidligere dag. Ikke lag en CSV med antatte valutakurser.

## 7. Analyser først etter fullført innsamling

For 90-dagersmappen:

```bash
python3 analyze.py --input results/run90 --mc 1000 --seed 20261018
```

For 30-dagersmappen, bytt `run90` med `run30`. Analysen kontrollerer fullstendighet, fortløpende blokker, b−1-state og kjede-parent-hasher. Den nekter kort/incomplete/smoke-data. Monte Carlo kjører minst 1000 kjøringer for hver av A/B × privat/offentlig på holdoutperioden, ikke bare 1000 tilfeldige punkter fra én beregning. Det kan ta tid ved mange historiske kandidater.

Resultater:

- `results/run90/analysis/REPORT.md`: merket konklusjon og begrensninger.
- `results/run90/analysis/equity-*.csv`: daglig egenkapital i NOK, hold-referanse, ETH/USDC-saldo og handels-PnL.
- `results/run90/analysis/equity-*.svg`: statiske kurver, generert bare fra et godkjent komplett datasett.
- `results/run90/analysis/events-*.csv`: antatte inkluderte utfall og minProfit-budsjett; filen kan mangle ved null inkluderte handler.
- `results/run90/analysis/bid-sensitivity.csv`: 80/90/95/99 %.
- `results/run90/analysis/results.json`: fulle tellere, gass i enheter/ETH/NOK, builder-bud, risiko, antakelser, walk-forward og Monte Carlo.
- `results/run90/blocks.jsonl` og `archive.sqlite`: råobservasjoner og reproduserbar cache; store filer.

Eksempel på å åpne den genererte rapporten fra Ubuntu:

```bash
explorer.exe .
```

Dette åpner mappen i Windows Explorer. Det er ingen wallet eller nettside å koble til.

## 8. Send tilbake resultatet uten hemmeligheter

Lim inn innholdet i `analysis/REPORT.md`. Legg gjerne ved `analysis/results.json` og `manifest.json` hvis du vil at jeg skal kontrollere konklusjonen og datagrunnlaget. De inneholder ikke endpoint eller nøkkel. Ved feil: send kommandoen **uten hemmeligheter** og den redigerte feilmeldingen. Ikke send `.env`, originale nøkkelholdige ZIP-filer eller ufiltrerte prosess-/debuglogger.

Et positivt totalresultat er ikke nok: se handels-PnL, meravkastning mot hold, antall faktiske modellforsøk, holdout og hvordan svaret endres under bud-/inklusjonsantakelser. Hvis ingen handler passerer kostnader og sperrer, er «ingen kvalifiserte handler» et gyldig funn for dette universet — ikke bevis for at en annen strategi eller et annet marked er ulønnsomt.
