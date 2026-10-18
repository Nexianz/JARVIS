# Historisk ETH-arbitrasje: forskningspakke, ikke handelsbot

**Ny arbeidsflyt: først [KVOTE.md](KVOTE.md). De eldre kommandoene og rapportflyten er ikke godkjent for den nye pilot-/samplingsprosessen.**

**Start her for API-nøkkel og endpoint: [ALCHEMY.md](ALCHEMY.md).** `python rpc_setup.py` lager lokal `.env` med skjult nøkkelinntasting; `python rpc_setup.py --check` tester lesetilgang uten Foundry.

**Status: Ingen historisk avkastning er målt i leveransemiljøet.** Alchemy ga transportfeil; DNS-oppslag feilet, også etter separat tilgangsforsøk. Foundry/Anvil og Solidity-kompilatoren er ikke installert der. Python-koden er syntakskontrollert og enhetstestet med uttrykkelig syntetiske test-fixtures. Solidity-kompilering, arkivinnsamling og EVM-integrasjon må derfor verifiseres på din maskin med stegene nedenfor. Dette er ikke en påstand om ferdig verifisert backtest eller at alle krav er empirisk oppfylt.

**Konklusjonen nå er ukjent**, ikke overskudd, tap eller null. Ingen eksempelkurver eller fabrikkert resultatfil følger med. Rapportgeneratoren nekter å rapportere en ufullstendig innsamling eller en kort smoke-test som et historisk resultat.

## Hva som erstatter de gamle ZIP-filene

Den gamle koden sammenlignet samtidige quotes og trakk fra modellerte kostnader. Papirporteføljen var ikke dokumentasjon på hva en liten searcher kunne tjent. Denne pakken har ingen nettside og bygger ikke videre på de fiktive paper-fills.

Den bruker Ethereum mainnet USDC/WETH på Uniswap V2, SushiSwap V2, Uniswap V3 500 og Uniswap V3 3000, begge ruteretninger mellom ulike pooler. Basistoken for lån og egenkapitalhandel er USDC. Dette dekker markedene i vedleggene, ikke alle mulige Ethereum-arbitrasjer.

Følgende ord har konsekvent betydning:

- **MÅLT**: blokkhoder, arkiverte `eth_call`-svar, Chainlink-observasjoner, `eth_feeHistory` og swap-events fra mainnet. Historisk USD/NOK er også MÅLT, men fra Norges Bank, ikke fra kjeden.
- **BEREGNET**: priser/size-søk, lokalt simulerte EVM-profitter og gass, konkurranseindikatorer, porteføljekurver, drawdown, sensitiviteter, walk-forward og Monte Carlo. De siste utfallene er betinget på antakelser.
- **ANTATT**: startkapital, posisjonsgrenser, bud, inklusjon, usikkerhetsfradrag, feilrate, etableringskostnad og risikogrenser. Et scenario kalt «realistisk» er en ukalibrert arbeidshypotese, ikke en empirisk målt sannsynlighet.

Alle rapporttabeller merkes med status. `results.json` har kildekart. Rå observasjoner i SQLite/JSON beholder feltnavn for maskinlesing; deres kildeklassifisering er beskrevet her og i rapporten.

## Hva som måles, og hva som ikke kan fastslås

For hver sammenhengende blokk **b** leses handelsinformasjon ved slutten av **b−1**. Ruter screenes med reelle historiske reserver/V3-priser og fee tiers. V2 bruker den eksakte heltallsformelen med protokollens faste 0,30 % swapgebyr. V3 QuoterV2 utfører faktisk tick-/likviditetslogikk via `eth_call` på eksplisitt blokknummer. V3 har konsentrert likviditet, ikke V2-lignende reserver. Historisk V3 `slot0`, aktiv likviditet og tokenbalanser beholdes; selve quote-/fork-kjøringen leser også ticks fra arkivnoden.

Hele transaksjonen kjøres på en lokal Anvil-fork fra b−1: flash loan når valgt, USDC→WETH, WETH→USDC, Aave-tilbakebetaling, `minProfit` og en ikke-null coinbase-betaling. Aaves premium hentes historisk, og den faktiske Aave-koden bestemmer tilbakebetalingen i simuleringen. Gass kommer fra lokale transaksjonskvitteringer, ikke et fast 500 000-estimat. En bevisst sen `minProfit`-revert må nå siste guard; en annen feiltype stopper innsamlingen. De simulerte gasstallene er **BEREGNET**, ikke historisk gass faktisk brukt av en egen transaksjon.

Vi kjenner neste blokks base fee fra b−1s gasUsed/baseFee/gasLimit. Den kontrolleres mot b. «Faktisk priority fee per blokk» er ikke ett tall: hver transaksjon har sin egen effektive tip. Vi lagrer gas-vektet median fra hver blokk via `eth_feeHistory`, med reservevei via fullstendig kontrollerte historiske kvitteringer (`effectiveGasPrice − baseFeePerGas`) dersom metoden feiler. Kilden lagres per blokk. Vårt **ANTATTE** gasstilbud bruker bare b−1s målte median. b sin median brukes utelukkende som diagnostikk, aldri til å velge handler. Det er ingen påstand om at et slikt bud ville blitt inkludert.

Neste blokks tidsstempel antas til forrige +12 sekunder; coinbase antas lik forrige blokks. Faktisk fremtidig coinbase og tidsstempel får ikke påvirke pretrade-valget. Denne antatte konteksten brukes i lokal EVM, som kjører Prague-regler. Derfor er det støttede historiske vinduet avgrenset til **2025-05-08 til 2025-12-02, slutt eksklusiv**. Standardeksemplet er **2025-06-01 til 2025-08-30**, 90 kalenderdager. Dette er ikke en tilbakeprøving av dagens siste 90 dager. Andre hardfork-epoker må implementeres og kontrolleres før denne sperren utvides.

Når en rute og størrelse er valgt uten neste-blokkdata, undersøkes swap-events i b. En transaksjon med begge ruteleggene og riktige retninger behandles konservativt som «tatt av andre». Dette er en **BEREGNET proxy**, ikke en full identifikasjon av lønnsom arbitrørhandel: router-handler kan gi falske treff, og flere separate transaksjoner kan overses. Private tapende bundles og alle builder-bud er ikke offentlig observerbare. Verktøyet kan derfor ikke oppfylle en bokstavelig garanti om å finne hver arbitrør eller bevise hvilke konkurranser vi faktisk ville vunnet.

Ruten velges før konkurransedata leses inn i utfallsmodellen. Vi velger ikke den ruten som vi i ettertid vet ble stående. En vunnet simulert handel får ikke høste samme uendrede pooltilstand på nytt; minst én brukt pool sperres inntil historikken viser en ny tilstand for den. Dette er en beskyttelse mot gjentatt fantomprofitt, men **ikke** en komplett omskriving av senere historiske blokker etter våre kontrafaktiske handler.

Vi spiller ikke om alle andre transaksjoner inni b og rekonstruerer ikke privat ordreflyt eller et builder-auksjonsmarked. Rekkefølgeendringer, ugunstig prisendring og ikke-observert konkurranse modelleres eksplisitt med **ANTATTE** haircut-, feil- og inklusjonsparametere. En eksakt fasit på «hva som faktisk ville skjedd» finnes ikke i offentlig kjedehistorikk alene. Resultatet må leses som en betinget kontrafaktisk backtest, ikke realisert PnL.

## Størrelse, kapital og kostnader

Per rute søkes først et logaritmisk størrelsesgitter og deretter en lokal numerisk forbedring. Både gitterstørrelsene og den forbedrede størrelsen EVM-simuleres, slik at analysen kan velge etter gass, bud og nettoprofitt, ikke bare bruttospread. Prisimpact inngår i hvert quote og i hele swapsekvensen. Det er et numerisk søk, ikke et bevis på globalt optimum i en vilkårlig tick-struktur.

Hver rute begrenses til 10 % av målte USDC-balansene i begge poolene. Flash loan begrenses også til 90 % av tilgjengelig USDC i Aaves aToken, og en eksplisitt maksimal søkegrense på 10 millioner USDC. `at_search_cap` viser når løsningen nærmer seg en grense. En grensebundet løsning skal ikke kalles globalt optimal.

- **A, flash loan:** ANTATT 5000 NOK konverteres til ETH for gass og builder-bud. Hovedstolen lånes og returneres atomisk. Profitt beholdes i USDC. Ingen hovedstol trekkes fra egenkapitalen.
- **B, egenkapital:** ANTATT 20 % av 5000 NOK settes av i ETH til gass, 80 % i USDC. Størrelser søkes innen 25/50/75/100 % av den opprinnelige USDC-rammen. Beste simulerte, tilgjengelige størrelse velges per anledning. Ingen lån. Lavere løpende saldo kan gi underutnyttelse mellom størrelsesrammene; høyere saldo øker ikke opprinnelig hovedstolsramme automatisk.

Startkonvertering koster ANTATT 0,30 %. Gassbeholdningen etterfylles ikke automatisk; hvis den blir for lav, stoppes handler, også om det finnes USDC-gevinster. Dette er en bevisst, sporbar driftsregel, ikke en påstand om optimal treasury-styring. Resultatet sammenlignes med en passiv beholdning med samme fordeling og etableringskostnad. En separat handels-PnL vises ved handelsdagens FX. Dermed blir en ETH-kursoppgang ikke forvekslet med arbitrasjeprofitt.

Builder-bud er ANTATT 80/90/95/99 % av overskuddet etter flash-premium og basisgass. Ingen historisk builder-betaling for vår ikke-eksisterende transaksjon hevdes målt. Lokalforken måler gasstien for en liten ikke-null coinbase-betaling; den økonomiske modellen belaster det antatte ETH-beløpet. Gasstall får en ANTATT buffer på 512 gas for blant annet ulik calldata i minProfit. Sikkerhetsmarginen er et krav til gjenværende overskudd, ikke en fiktiv utgift.

Offentlig mempool: inkluderte kollisjoner antas å revertere og betale lokalt målt sen-revert-gass. Andre feil kan koste mer eller mindre. Private bundles: ikke-inkludering koster null; når modellen antar inklusjon kan en annen state-/utførelsesfeil fortsatt gi revert. Dette er konservativt for bundles som faktisk har vellykket buildersimulering. Ingen betaling ved mislykket coinbase-/minProfit-transaksjon, ettersom hele EVM-transaksjonen reverterer.

RPC-abonnement, skatter, VPS, revisjon og øvrige driftskostnader er ikke inkludert. De kan ikke forbedre resultatet. USDC/USD måles historisk via Chainlink; 1 USDC antas ikke alltid lik 1 USD. Norges Banks kurs for siste tilgjengelige dag brukes i helger, maksimalt fem dagers foreldelse. Ingen fremtidig FX fylles bakover.

## Risikogrenser implementert i koden

Se `model.py` og `contracts/Replay.sol`.

|Regel|Standard, alle ANTATT|Håndheving|
|---|---:|---|
|Minste netto|1 NOK + 25 % av gasskostnaden i sikkerhetsmargin|Filter etter premium, gass og builder-bud; minProfit-budsjett i USDC|
|Maks dagstap|50 NOK|Neste forsøk nektes hvis full antatt reverteringskostnad kan bryte grensen|
|Maks ukestap|150 NOK|ISO-uke, UTC; overlever døgnskifte|
|Maks gasskostnad per forsøk|30 NOK|Prospektiv kontroll|
|Maks gasstilbud|100 gwei|Prospektiv kontroll; ikke universell fast gasspris|
|Maks inkluderte feil siste time|3|Rullerende 3600 sekunder, pause til utløp|
|Tokenfilter|Kun kanoniske USDC og WETH|Andre tokens, inkludert ukjente fee-on-transfer/honeypots, er ikke kvalifisert|
|Poolfilter|Minst 30 dager gammel; minst 1 million USD USDC-side|Historisk bytecode, kanonisk factory, token0/1, V3 fee og historiske balanser|
|Kontraktsvern|minProfit og verifisert flash-callback|Revert dersom sluttbalansen ikke dekker hovedstol + avtalt tokenprofitt; gas/bid-budgett oversettes til minProfit av modellen|

Dag-/uketap summerer negative handelsutfall, ikke urealiserte kursbevegelser. Gevinster nullstiller ikke tapstelleren. Gass-taket gjelder inkludert antatt gasbuffer. Privat ikke-inkludering regnes ikke som inkludert feil. En kill switch mot kursrisiko i passiv ETH-beholdning er ikke implementert; den er synlig separat i egenkapital og hold-referanse.

USDC kan fryses eller oppgraderes; en allowlist eliminerer ikke dette. Kodens filter er et restriktivt univers, ikke en generell honeypot-detektor. Swap-/repayment-feil stanser eller forkaster den aktuelle EVM-simuleringen; de skjules ikke som passerte tester.

## Scenarioer, sensitivitet, walk-forward og Monte Carlo

Alle tall i neste tabell er **ANTATT**, ikke estimert fra egne faktiske handler:

|Navn|Privat inklusjon etter ikke-påvist kollisjon|Offentlig inklusjon|Ekstra feilrate gitt inklusjon|Maks ugunstig profittfradrag|Builder-andel|
|---|---:|---:|---:|---:|---:|
|Pessimistisk|1 %|95 %|25 %|25 %|99 %|
|Realistisk, ukalibrert|10 %|95 %|10 %|10 %|95 %|
|Optimistisk|50 %|95 %|2 %|2 %|80 %|

For hver inkludert transaksjon trekkes adverse haircut uniformt mellom null og scenarioets maksimum. Hvis beholdt tokenprofitt ikke møter kontraktens minProfit-budgett, modelleres revert selv uten en ekstra tilfeldig feil. Builder-budet blir ikke magisk redusert etter at den ugunstige prisendringen er kjent.

Bud-sensitiviteten holder inklusjonsantakelsen konstant mens kostnadsandelen varieres. Den måler kostnadseffekten, ikke en kalibrert bud/inkluderingskurve; en slik kurve krever faktiske egne bundles eller tilsvarende data som ikke finnes her.

Walk-forward bruker første tredel av kalenderdagene til å velge bare én parameter: minimumsnetto 1, 2 eller 5 NOK. Samme risikogrenser og priorer beholdes. Scoren er gjennomsnitt av åtte faste modellfrø i treningsperioden, deretter fryses terskelen før siste to tredeler testes. Holdout starter med ny ANTATT 5000 NOK. Dette er modellkalibrering, ikke empirisk estimering av en searchers suksessrate. Hvis trening har null handler, er det ingen datastøttet finjustering; lik-score velger høyeste terskel.

Monte Carlo kjører minst 1000 trekk **per modus og kanal på holdout**, med faste frø og parametere trukket per hel kjøring: privat inklusjon 1–50 %, offentlig 80–100 %, ekstra feil 2–25 %, maks haircut 2–25 %, builder-andel 80–99 %. Disse uavhengige uniformpriorene er ANTATTE, og virkelige korrelasjoner er ukjente. Rapporten viser derfor betingede fordelinger, ikke en objektiv sannsynlighet for å tjene penger. MC bruker hendelsesblokker og dagsslutt for hastighet; sluttsaldo er bevart, og MC påstår ikke å måle intradag-drawdown fra den komprimerte serien. Hovedscenarioenes drawdown beregnes på hele blokkserien.

## Smartkontraktrisiko, nøkkelhåndtering og ekte penger

`Replay.sol` er en **urevidert forskningsharness**. Den installeres med `anvil_setCode` på en engangsfork, ikke med en mainnet-deploy. Den har en hard sperre på chain ID 31337. Python tillater bare lesemetoder til arkiv-RPC. Lokale skriveoperasjoner må treffe en ny Anvil som programmet selv startet på 127.0.0.1 og som bekrefter riktig klient og chain ID. Ingen brukerprivatnøkkel, wallet-tilkobling eller mainnet-broadcast finnes i arbeidsflyten. De lokale impersonerte adressene er fiktive, ikke dine wallets.

`minProfit` gjør ikke et system sikkert alene: godkjennelser, callback-autentisering, reentrancy, revert-data, ruter-/pooladresser, tokenoppgraderinger, rounding, kjedespesifikk EVM, builder-betaling og USDC/Aave-infrastruktur må gjennomgås. Harnessen er ikke en sikker produksjonskontrakt; blant annet mangler den produksjonsmessig tilgangskontroll og uttaksdesign. Den skal ikke få reelle midler.

Før noen separat produksjonsvurdering må et uavhengig revisjonsteam revidere en egen produksjonsimplementasjon, kontrollere compiler/dependency-proveniens, skrive fuzz-/invariant- og adversarielle fork-tester, verifisere worst-case minProfit/gas/bid, callbacks og godkjennelser, dokumentere nødprosedyrer og kontrollere distribusjonsbytecode. En backtest eller disse enhetstestene erstatter ikke revisjon. Eventuelle fremtidige nøkler må forvaltes separat i maskinvare-/MPC-/tilsvarende sikker løsning, med minst mulige rettigheter; aldri i prosjektfil, chat eller ZIP. Denne leveransen ber ikke om eller bruker slike nøkler.

**Den gamle Alchemy-nøkkelen lå i vedlagte ZIP og må roteres/revokeres hos Alchemy.** Bruk en ny nøkkel i en lokal `.env` som `.gitignore` utelukker. Ingen gammel nøkkel eller `.env` følger denne leveransen. Ikke last opp din `.env`, original-ZIP med gammel nøkkel eller prosesslogger som viser endpointet.

## Filer

- `WINDOWS.md`: eksakt kjøreoppskrift med Windows + WSL2.
- `chain.py`: Ethereum Keccak/ABI, lesesperre, SQLite-cache og redigerte feil.
- `market.py`: reell historisk state, orakler, FX, størrelsessøk og konkurranseproxy.
- `contracts/Replay.sol`, `fork.py`: atomisk lokal EVM, gas og revert/minProfit-kontroll.
- `preflight.py`: liten reell arkiv-/fork-test før stor innsamling.
- `collect.py`: sammenhengende blokkinnsamling, checkpoint, manglende-data-sperrer og proveniens.
- `model.py`: portefølje, begge finansieringsformer og kanaler, risikostyring og antakelser.
- `analyze.py`: NOK-kurver, drawdown, tellere, sensitiviteter, walk-forward, minst 1000 Monte Carlo per kombinasjon og merket rapport.
- `tests/`: syntetiske enhetstester; de produserer ingen historiske resultatrapporter.
- `STATUS.md`: nøyaktig hva som faktisk ble kjørt i leveransemiljøet.
