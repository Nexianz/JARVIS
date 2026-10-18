# Faktisk kjørestatus, 18. oktober 2026

**Ingen historisk avkastningskonklusjon kan trekkes ennå.**

|Kontroll|Faktisk utfall|Hva det betyr|
|---|---|---|
|Vedlegg undersøkt|Begge ZIP-filer lest; nøkkelverdier ikke vist|Det gamle opplegget er live-quotes/paper-fills, ikke historisk avkastningsmåling|
|Eksisterende Alchemy-endpoint|Fant bindingen i den opprinnelige ZIP-ens `.env`, prøvde kun lesekall|Nøkkelen er ikke kopiert til denne pakken|
|Alchemy-tilgang her|Transportfeil før et JSON-RPC-svar, også i separat tilgangsforsøk|Ingen påvist 401/403 eller bevist ugyldig nøkkel; ingen historiske data hentet|
|DNS her|Oppslag mot Alchemy og npm-registry feilet|Kan ikke hente verktøy eller måle mainnet her|
|Foundry/Anvil/Solidity|Ikke installert i miljøet|Solidity-kompilering og EVM-integrasjon er IKKE kjørt/verifisert|
|Python|3.12 i leveransemiljøet; syntakskontroll bestått|Dette alene beviser ikke at backtesten virker mot en ekte node|
|Lokale enhetstester|49 tester kjørt, 49 bestått|Syntetiske fixtures for ABI, kostnader, sizing, konkurranseproxy, risikokontroll og datasperrer; ingen avkastningsobservasjoner|
|Historisk 30/90-dagers innsamling|IKKE kjørt|Ingen MÅLTE historiske mulighetstall eller avkastningstall|
|Monte Carlo / walk-forward på reelle data|IKKE kjørt|Implementert, men ingen resultater er påstått|
|Resultatgrafer og PnL-rapport|IKKE produsert|Ingen fabrikerte kurver, skjulte eksempel-fills eller demo-resultater|
|Ekte penger / brukerprivatnøkler / wallet|IKKE brukt|Arkivlesing og lokale fork-simuleringer er de eneste planlagte kjedeoperasjonene|

Neste steg er `WINDOWS.md`: roter Alchemy-nøkkelen, installer verifiserte verktøy, kompiler, kjør tester, preflight og én blokk, deretter full innsamling og analyse. Lim tilbake rapporten uten `.env`.

## Avgrensninger mot ønsket fasit

Skriptgrunnlaget dekker de fire markedene i vedleggene og er ment for 90 dager innen den eksplisitt støttede Prague-perioden. Det er ikke en ferdig gjennomført studie av siste 90 dager.

Noen krav krever informasjon som ikke er fullt offentlig tilgjengelig. Konkurranse baseres på en swap-event-proxy, ikke sikker identifisering av hver arbitrør. Inklusjon, fremtidig ordreflyt og builder-bud er antakelser. Gasstallet for vår hypotetiske transaksjon er BEREGNET ved lokal EVM, ikke en MÅLT egen mainnet-kvittering. Den faktisk observerte priority-fee-fordelingen per blokk lagres, mens vårt bud må bestemmes fra tidligere informasjon.

Størrelsesvalg er et numerisk gitter med lokal forbedring og likviditetsgrenser, ikke et bevist globalt nettooptimum. Den langsiktige kjeden spilles ikke om etter våre kontrafaktiske handler; gjenbruk av helt uendret pooltilstand sperres som en begrenset beskyttelse. Disse forskjellene er synlige i rapportgeneratoren og skal ikke tones ned ved tolkning av senere resultater.

**Sikkerhet om overskudd, tap eller null: ikke vurderbar før reelle data og integrasjon er kjørt.** Selv etter en kjøring vil private konkurranseforhold gi vesentlig modellusikkerhet. Et negativt funn eller null kvalifiserte handler er et akseptabelt resultat; det skal ikke erstattes av teoretiske spreads.

Tilbakemelding fra Windows viste vellykket mainnet/arkivtilgang, men HTTP 503 for feeHistory. Reservevei via verifiserte kvitteringer er nå implementert og enhetstestet; den er ikke testet mot brukerens node i leveransemiljøet.
