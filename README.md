# JARVIS — ekte marked, fiktive penger

**Historisk undersøkelse: [kvotesikring](KVOTE.md), deretter [døgnpilot](PILOT.md) på Windows. Ikke start gamle fullkjøringskommandoer før pilot og kvote er avklart. Nettsiden nedenfor er en separat paper-demo.**

Godkjent bredere test med åtte datoer, hver 20. blokk og delt CU-tak: [BATCH.md](BATCH.md). Batchen starter bare med `--run`; uten flagget vises kun estimatet, uten nettverkskall.

Netlify-hostet nettside som følger USDC/WETH på Ethereum mainnet og viser en agents beslutninger og paperhandler. Startkapitalen er **ANTATT 5000 NOK**. Ingen wallet, privatnøkler eller ekte handler. **Ingen Ubuntu, Python eller Foundry er nødvendig for nettsiden.**

Agenten sjekker Uniswap V2, SushiSwap V2 og Uniswap V3 0,05/0,30 %. Netlify Functions holder nøkler på serveren; Netlify Blobs beholder porteføljen mellom besøk og deployer. En planlagt funksjon skanner omtrent hvert minutt når agenten er startet. Det går også uten at nettleseren er åpen.

## Få den på Netlify

1. Åpne Netlify → **Add new project / Import an existing project** → GitHub → velg **Nexianz/JARVIS**, branch **main**.
2. Behold prosjektroten som base directory. `netlify.toml` angir automatisk:
   - Build command: `npm run build`
   - Publish directory: `web`
   - Functions directory: `netlify/functions`
   - Node: 22
3. I prosjektets **Environment variables**, legg inn følgende som hemmelige verdier med tilgang for **Functions** i **Production**:

|Navn|Hva du legger inn|
|---|---|
|`ALCHEMY_API_KEY`|Din **nye** Alchemy Ethereum Mainnet API-nøkkel|
|`PAPER_ADMIN_TOKEN`|Et selvvalgt, langt og tilfeldig eierpassord, minst 16 tegn. Dette er **ikke** Alchemy-nøkkelen.|

Alternativ til `ALCHEMY_API_KEY`: sett `ETH_RPC_URL` til hele HTTPS-URL-en fra Alchemy. Den overstyrer separat nøkkel. Standard `ALCHEMY_ENDPOINT` er `https://eth-mainnet.g.alchemy.com/v2/{API_KEY}`; normalt trenger du ikke sette den. **Ingen nøkkel i Git, HTML eller frontend-kode. Ikke bruk et `VITE_`-/offentlig frontend-prefiks.**

4. Deploy prosjektet. Hvis variablene ble lagt inn etter første deploy, kjør en ny deploy.
5. Åpne nettsiden. Trykk **Eiertilgang**, skriv **eierpassordet**, og trykk **Start agent**. Trykk **Skann nå** for første måling. Deretter går planlagte skanninger automatisk på produksjonsdeployen.
6. Trykk **Pause agent** når du vil stoppe. Planlagte kall hopper da over markedslesing. Kanal kan endres mellom privat bundle og offentlig mempool mens agenten er pauset.

Bruk Git-import, **ikke** Netlify Drop med bare HTML-mappen: siden trenger serverfunksjoner, planlagte funksjoner og varig lagring. Planlagte kjøringer virker på den publiserte produksjonssiden, ikke som en garanti i deploy-preview. Kontroller at Netlify-planen tillater Functions, Scheduled Functions og Blobs, og se `pulse` i Functions-visningen for kjørestatus. Netlify tilfører Blobs-tilgang automatisk i sine funksjoner; ingen egen database- eller wallet-nøkkel er nødvendig.

Netlify- og Alchemy-kreditter kan brukes selv om pengene i porteføljen er fiktive. En skanning gjør omtrent 55 lesekall, flere hvis en pending-rute må sjekkes for konkurranse. Både Netlify-kvoter og Alchemy-rate limits kan begrense frekvensen. Ingen kontinuerlig blokk-for-blokk-bot påstås.

## Vil du at en faktisk språkmodell skal velge?

Uten OpenAI-nøkkel viser nettsiden **Regelbasert agent**. Den velger høyest beregnet netto blant ruter som passerer risikogrenser. Dette skal ikke fremstilles som at en språkmodell har tatt beslutningen.

For faktiske AI-beslutninger legger du til følgende servervariabel i Netlify og redeployer:

|Navn|Verdi|
|---|---|
|`OPENAI_API_KEY`|Din egen OpenAI API-nøkkel, kun Functions-scope|
|`OPENAI_MODEL`|Valgfritt; standard `gpt-4.1-mini`|

Da viser nettsiden **AI + faste risikogrenser**. Modellen kan velge en av de kvalifiserte rutene eller vente. Den får bare markedsmålinger og kostnadsanslag, ingen hemmeligheter. Ugyldig svar eller AI-feil betyr vent, ikke automatisk regelhandel. Modellen kan ikke øke beløp eller omgå risikokrav. OpenAI API kan koste penger; denne integrasjonen er testet med en simulert API-respons, ikke en ekte OpenAI-konto i leveransemiljøet.

## Hva nettsiden faktisk viser

- **MÅLT:** observert mainnet-blokk, ETH/USD og USDC/USD fra Chainlink, en liten DEX-quote på 0,01 WETH for prisgrafen, pool-quotes og Aave-premium på samme eksplisitte blokknummer. Ruter bruker USDC → WETH → USDC i ulike pooler. Swapgebyr og prisimpact er inkludert i DEX-quotes.
- **BEREGNET:** prisforskjeller, forventet netto og NOK-regnskap for virtuelle handler.
- **ANTATT:** startkapital, gassmengde, gasstilbud for neste forsøk, builder-bud, inklusjon og simulerte fills/reverteringer. En paper-fill er ikke en EVM-verifisert transaksjon eller bevist gjennomførbar arbitrase.

USD/NOK er en målt ECB-dagskurs fra Frankfurter når tilgjengelig. Ved feil brukes en eksplisitt **ANTATT** kurs på 10,5, synlig i et varsel og i hver paperhandel. Beholdningen er en forenklet virtuell NOK-kontantbeholdning, ikke en virkelig ETH/USDC-wallet med kursrisiko. Den virtuelle flash-loan-hovedstolen er ikke porteføljens egenkapital.

Ingen demopriser eller eksempelgevinster fyller dashboardet. Før første vellykkede markedsskanning vises tomme felt og den tydelig fiktive startkapitalen. Ingen trades er et legitimt utfall.

### Beslutning og utførelse

1. Les ny blokk og quotes for 1000 / 10 000 / 50 000 USDC. Dette er et størrelsesgitter, ikke et globalt størrelsesoptimum.
2. Trekk faktisk lest Aave-premium, antatt gass, builder-bud og utførelsesbuffer fra bruttoquote.
3. Filtrer ruter mot risiko. Regelagent eller AI velger et signal, som **ikke** straks bokføres som gevinst.
4. På neste måling prises **samme rute og beløp** på nytt. Vi bytter ikke til den ruten som først i ettertid ser best ut. Signaler eldre enn tre minutter droppes.
5. Les swap-events mellom målingene. Begge rutelegg i samme transaksjon behandles konservativt som tapt konkurranse. Dette er en proxy: aggregator-kundehandler kan gi falske treff, og separate arbitrørtransaksjoner kan overses. Ukjente data betyr ingen fill.
6. Hvis ruten fortsatt passerer kontrollene, brukes en **ANTATT capture-sjanse på 10 %**. Utfallet trekkes reproduserbart fra en hash av signalblokk/rute, ikke fra faktisk builder-inkludering. Privat ikke-inkludering koster null; offentlig modell har i tillegg 20 % antatt revertsjanse gitt capture. Et kollisjonstreff kan gi offentlig, modellert revert. Forsøk som allerede har falt under risikokrav avvises før modellert innsending; dette rekonstruerer ikke en tidligere sendt mempooltransaksjon.
7. Bare dette **SIMULERTE** utfallet bokføres, med kostnader og kildemerking.

Dette bekrefter på neste **måling**, ofte flere blokker senere. Det er ikke neste-blokk-execution, replay av full transaksjon, faktisk privat ordreflyt eller en historisk backtest. Skatter, abonnement, maskinvare og revisjon er ikke trukket fra paper-PnL. En positiv kurve beviser ikke at strategien ville tjent penger i virkeligheten.

### Faste sperrer og synlige antakelser

|Innstilling|ANTATT verdi|
|---|---:|
|Startkapital|5000 NOK|
|Gas ved fill / revert|450 000 / 200 000 enheter|
|Gasstilbud|observert base fee × 1,125 + observert median-tip; RPC-anbefalt tip merkes ANTATT dersom feeHistory feiler|
|Builder-bud|90 % av overskudd etter gass og premium|
|Utførelsesbuffer|3 bp av hovedstolen; konservativt prisfradrag, ikke påstått faktisk gebyr|
|Minimum netto|2 NOK + 25 % av gasskostnaden som margin|
|Maks daglig / ukentlig tap|50 / 150 NOK, UTC|
|Maks gasskostnad / gasstilbud|30 NOK / 100 gwei|
|Maks feil siste time|3|
|Tokens|Kun kanoniske USDC og WETH|

Det finnes ingen produksjonshandelskontrakt her. Ingen minProfit-garanti på mainnet, ingen wallet-tilkobling og ingen transaksjonssignering. Hvis man en gang vurderer ekte penger, kreves en separat produksjonsimplementasjon og uavhengig revisjon; paperresultater er ikke tilstrekkelig. Den tidligere forskningsharnessen er urevidert og sperret til lokal kjede-ID 31337.

## Lokal visning på Windows — valgfritt, uten Ubuntu

Installer Node.js 22 LTS og Git. I PowerShell:

```powershell
git clone https://github.com/Nexianz/JARVIS.git
cd JARVIS
npm ci
Copy-Item .env.example .env
notepad .env
npm run dev
```

Hvis `.env` allerede finnes, åpne den; ikke overskriv den. Legg inn ny Alchemy-nøkkel/hel URL og et eget `PAPER_ADMIN_TOKEN`. Åpne nettleseren på port 3000 på din maskin. Lokal portefølje lagres i ignorert `.local/paper.json`; denne filen lastes ikke til Netlify. Netlify bruker Blobs og krever ikke at din maskin står på.

## Kontrollert i leveransemiljøet

- `npm test`: 26 tester for beslutninger, kostnader, risiko, API-autentisering, konkurranse, samtidighet og ekte SDK mot lokal Netlify Blobs-emulator. Marked/AI-responser i testene er eksplisitt syntetiske.
- `npm run build`: publiseringsmappen sjekkes; kun statiske nettsidefiler publiseres.
- Nettleser: desktop, mobil, eierdialog, ingen JavaScript-feil og kontroll av horisontal overflow.
- Ingen ny Alchemy-/OpenAI-nøkkel er tilgjengelig i leveransemiljøet. Reelle Netlify Functions, planlagt cron, ekte Alchemy-quotes og OpenAI er **ikke verifisert i en publisert Netlify-instans**. Din tidligere Windows-test viste at Alchemy-arkivtilgangen fungerer, men det er en separat test.
- 49 eksisterende Python-tester bevares for den tidligere forskningspakken. De er ikke nødvendige for nettsiden.

## Tidligere historisk forskningspakke

Den ligger fortsatt i repoet, men brukes ikke av nettsiden. Se [BACKTEST.md](BACKTEST.md), [WINDOWS.md](WINDOWS.md) og [STATUS.md](STATUS.md) for det opprinnelige backtestarbeidet. Ingen historisk avkastning påstås målt der. [ALCHEMY.md](ALCHEMY.md) beskriver også den separate Python-tilkoblingstesten; for nettsiden legger du nøklene direkte i Netlify.

### ETH-graf og hover

ETH/USD er standardvisningen. Grafen viser kun faktisk innsamlede målinger, omtrent hvert minutt mens agenten kjører; ingen historikk fylles inn med demodata. En quote på 0,01 WETH fra Uniswap V3 0,05 % gir en oppdatert, omtrentlig DEX-pris inklusive poolgebyr/prisimpact. Chainlink brukes som tydelig merket reserve ved quote-feil, og brukes fortsatt uendret til gasskostnadsberegningen. Eldre lagrede ETH-punkter var Chainlink-observasjoner; hover viser kilden per punkt.

Hover eller trykk viser pris, dato/tid, blokknummer og kilde. Piltaster/Home/End virker når grafen har tastaturfokus. X-aksen bruker reell måletid, og pauser over tre minutter og skifte av priskilde får brudd i linjen. Frontend sjekker lagrede data hvert 15. sekund; dette er ikke tick-for-tick-strømming, og pauset agent gir ingen nye punkter. Tradinggrenser og startkapital er uendret.
