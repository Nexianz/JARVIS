# Alchemy: hvor nøkkel og endpoint skal inn

**Revoker den gamle nøkkelen fra original-ZIP-en hos Alchemy først.** Ny nøkkel skal bare inn i din lokale `.env`, aldri i GitHub, kode, chat eller rapport.

## Windows: hent prosjektet

I PowerShell, med Git og Python 3.10+ installert:

```powershell
git clone https://github.com/Nexianz/JARVIS.git
cd JARVIS
python rpc_setup.py
```

Du kan lime inn en **komplett HTTPS-RPC-URL** i første spørsmål; da spør programmet ikke om en ekstra nøkkel. Eller trykk Enter for standard Ethereum mainnet-endpoint og skriv så **ny API-nøkkel** når programmet spør. Begge inntastinger er skjult, også URL-en, fordi den kan inneholde nøkkelen. Programmet oppretter `.env` og overskriver aldri en eksisterende fil.

Test tilgangen uten Foundry, wallet eller transaksjoner:

```powershell
python rpc_setup.py --check
```

Testen leser mainnet chain ID, `eth_call` ved historisk blokk 23000000 og historiske priority fees. Et pass er en tilkoblings-/arkivtest, ikke en bestått EVM-backtest. Feil viser aldri hele endpointet eller nøkkelen.

## Alternativ: rediger manuelt

Fra prosjektmappen, bare dersom `.env` ikke finnes:

```powershell
Copy-Item .env.example .env
notepad .env
```

Hvis `.env` allerede finnes, kjør bare `notepad .env`. Fyll inn:

```dotenv
ALCHEMY_ENDPOINT=https://eth-mainnet.g.alchemy.com/v2/{API_KEY}
ALCHEMY_API_KEY=DIN_NYE_NOKKEL
ETH_RPC_URL=
```

Behold `{API_KEY}` bokstavelig i endpointfeltet. Programmet setter inn nøkkelen i minnet. Erstatt `DIN_NYE_NOKKEL` med den faktiske nye nøkkelen **kun lokalt**.

Hvis Alchemy allerede gir deg en komplett HTTPS-URL med nøkkelen inkludert, kan du i stedet sette **hele URL-en i `ETH_RPC_URL`** i `.env`. Dette feltet overstyrer de to andre når det er utfylt. Ikke bland de to metodene under feilsøking. Miljøvariabler som allerede finnes i prosessen overstyrer `.env`; fjern gamle verdier før du tester en endret fil.

Kontroller at filen er ignorert:

```powershell
git check-ignore .env
```

Forventet svar er `.env`. Ikke bruk `git add -f .env`. `.env.example` inneholder bare eksempelfelter og er trygg å ha i Git.

## Alchemy-innstillinger

Velg **Ethereum Mainnet** i Alchemy-appen og kopier HTTPS API key/endpoint fra appens tilkoblingsvisning. Tilgangen må tillate historiske `eth_call`, blokker, logs og `eth_feeHistory`. Kontroller abonnementets arkivtilgang, compute-unit-grenser og eventuelle IP-/applikasjonsrestriksjoner. Verktøyet henter aldri wallet-/signeringsnøkler.

- HTTP 401/403: kontroller ny nøkkel, app, tilgang og restriksjoner.
- HTTP 429 eller limit-feil: kontroller compute-unit-forbruk og kvote.
- Transport-/DNS-feil: kontroller nettverk/proxy, DNS og tilgang til `eth-mainnet.g.alchemy.com`. Det beviser ikke at nøkkelen er feil.
- Manglende historisk state: kontroller archive-tilgang; live-priser er ikke en erstatning.

Tilgangen fra Codex-miljøet var tidligere blokkert på transport/DNS. Konfigurasjonen er forbedret, men ingen ny brukernøkkel er lagt inn eller verifisert her. Ikke send nøkkelen i chat.

## Kjør selve studien

For Anvil og Solidity bruker Windows-oppskriften WSL2: [WINDOWS.md](WINDOWS.md). Klon helst repoet inne i Ubuntu (`git clone ...; cd JARVIS`) og kjør `python3 rpc_setup.py` der; opprett `.env` i akkurat den klonen som skal kjøre backtesten. `.env` følger ikke med mellom kloner.

Etter Foundry-installasjonen i guiden, fra prosjektmappen i Ubuntu:

```bash
forge build
python3 -m unittest discover -s tests -v
python3 rpc_setup.py --check
python3 preflight.py --date 2025-06-01
python3 collect.py --start 2025-06-01 --end 2025-08-30 --smoke-blocks 1 --output results/smoke --rpc-budget 20000
```

Deretter full innsamling og analyse som beskrevet i Windows-guiden. Historisk EVM-integrasjon er fortsatt ikke verifisert i leveransemiljøet, og en full studie kan bruke mange RPC-kreditter. Ingen live-handel eller wallet-tilkobling inngår.

## Historisk eth_feeHistory gir HTTP 503

Mainnet/arkiv-PASS etterfulgt av 503 for `eth_feeHistory` betyr at den metoden feilet; det beviser ikke feil nøkkel. Koden prøver først feeHistory med begrensede retries, deretter `eth_getBlockReceipts`. Hvis bulk-kvitteringer ikke støttes, hentes individuelle `eth_getTransactionReceipt` for transaksjonene i blokken.

For hver kvittering brukes faktisk `effectiveGasPrice − baseFeePerGas`, vektet med faktisk `gasUsed`. Blokknummer, blokkhash, fullstendig/unik transaksjonsliste og summert block gasUsed kontrolleres. Dette er målte historiske fees, ikke et fast anslag. Tom blokk gir null; manglende/inkonsistente kvitteringer stopper kjøringen. Kilden logges i blokkradene og vises i tilkoblingstesten. Reserveveien kan bruke betydelig mer data og flere RPC-kall. Etter første metodefeil gjenbrukes reserveveien resten av prosessen.

Oppdater uten å endre `.env`:

```powershell
git pull origin main
python rpc_setup.py --check
```
