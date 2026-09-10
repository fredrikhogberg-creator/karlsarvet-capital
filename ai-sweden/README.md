# Karlsarvet AI Sweden v1.0

## Aktuellt läge

Körbar datahämtning och **basranking** för svenska Large/Mid Cap. Basmodellen använder momentum, värdering och kvalitet: 60 % av den avtalade sexfaktorsmodellens ursprungliga vikt. Resultatet kallas därför baspoäng, inte fullständigt AI-betyg.

Den befintliga portföljappen ligger separat i repositoryts rot. Denna kod finns i `ai-sweden/`.

## Körningar

```bash
pip install -r requirements.txt
python -m unittest -v test_core
# BORSDATA_API_KEY måste redan finnas i miljön.
python run_pipeline.py --as-of 2026-09-09
```

GitHub Actions: **AI Sweden Data and Ranking**, `.github/workflows/ai-sweden-ranking.yml`.
Den läser befintlig repository-secret `BORSDATA_API_KEY`. Ingen nyckel skrivs i kod, filer eller felmeddelanden.
Körningen sker vid ändringar på utvecklingsgrenen och kan startas manuellt när workflow-filen finns på standardgrenen.
Inget tidsschema och ingen orderläggning har aktiverats.

Utdata i `results/`:
- `RESULTAT.md`: läsbar sammanfattning.
- `top10.csv`: tio likaviktade modellinnehav, endast när datahämtningen lyckats och minst tio bolag är jämförbara.
- `ranking.csv`: råa nyckeltal, delpoäng, täckning och kvalificering.
- `data_coverage.csv`: tillgänglig kurs- och rapporthistorik per bolag.
- `run_summary.json`, `excluded.json`, `errors.json`: metod, status, bortval och fel.

Rådata sparas i `data/` under körningen, separat från resultatfilerna. Rådata checkas inte in och laddas inte upp som GitHub-artifact.
Resultat-artifact sparas i 14 dagar. Varje körning hämtar data på nytt.

## Basmodellens metod

- Land och Large/Mid Cap löses från Börsdatas metadata.
- Primära vanliga aktier (`instrument=0`) noterade i SEK används; sekundära aktieslag och preferensaktier tas bort.
- Minst 270 kursobservationer, senaste kurs högst fyra kalenderdagar gammal.
- Kurs minst 5 kr, medianomsättning över 63 handelsdagar minst 1 Mkr/dag.
- Momentum: medel av 63/126/252 handelsdagars prisförändring, därefter percentilranking.
- Värdering: vinst/börsvärde och fritt kassaflöde/börsvärde.
- Kvalitet: vinst/eget kapital (periodslutsvärde), rörelsemarginal, omvänd nettoskuld/tillgångar och operativt kassaflöde/vinst.
- Negativa vinster straffas i vinstavkastningen; kassakonvertering kräver positiv vinst. Alla sex fundamentala delmått krävs för jämförbar basranking.
- Varje delmått winsoriseras vid 2/98-percentilen. Sektorjämförelse används vid minst fem giltiga observationer, annars hela urvalet.
- Baspoäng = (25 × momentum + 20 × värdering + 15 × kvalitet) / 60.
- Samtliga tre basfaktorer krävs för Top 10. Bristande hämtning stoppar Top 10 i stället för att ranka ett tyst förminskat urval.

Värderingen använder ännu inte EV/EBITA eller relativ historisk värdering. Kvaliteten använder ännu inte ROIC. Delmåtten är öppet redovisade förenklingar i basversionen.
Prisbaserat momentum är ännu inte verifierat som totalavkastning.
Finansbolag och bolag med ofullständiga rapportmått kan falla bort; bortfallet visas i täckningen.

## Låst full modell

| Faktor | Ursprunglig vikt | Status |
|---|---:|---|
| Momentum | 25 % | Basversion |
| Estimatrevideringar | 20 % | Saknar historisk estimatkälla |
| Värdering | 20 % | Basversion |
| Kvalitet | 15 % | Basversion |
| Rapportreaktion | 10 % | Ej implementerad |
| Rapport-AI | 10 % | Ej implementerad |

`total_score` lämnas tomt tills alla sex faktorer är giltiga. `coverage` anger andelen av hela sexfaktorsmodellen. Ett tillgängligt delbetyg ersätter aldrig det fullständiga betyget.

## Backtest

Avtalade inställningar: 1 Mkr, 2010-01-01–2026-09-09, månatlig Top 10, 10 % per aktie, SIXRX, 5/15/30 baspunkter per köp/sälj.

Motorn har korrigerats:
- En ranking efter dagens stängning verkställs först vid nästa handelsdags stängning.
- Tidigare innehav bär avkastningen fram till affären.
- Antalet andelar hålls fast mellan rebalanseringar; vikter driver med priserna.
- Avgifter beräknas på faktiskt omsatt belopp med självfinansierad likaviktning.
- Startkapitalet ingår i avkastnings- och drawdownberäkningen.
- Saknad kurs på ett innehav stoppar testet; den fylls inte automatiskt framåt.
- Färre än tio valbara instrument stoppar testet.

```bash
python run_backtest.py --inputs /path/to/verified-inputs
```

Inputmappen ska innehålla:
- `prices.csv`: datumindex, instrument-ID-kolumner, positiva totalavkastningsjusterade priser.
- `scores.csv`: datumindex, en ranking per månad, samma instrument-ID-kolumner, tomt för ej valbara.
- `membership.csv`: datumindex som täcker rankingdagarna, instrument-ID-kolumner, 0/1 för historisk valbarhet.
- `sixrx.csv`: datumindex och kolumnen `SIXRX`, totalavkastningsindex.
- `manifest.json`: proveniens enligt `manifest.example.json`.

Manifestet är en dokumentation av kontrollerat källunderlag, inte en automatisk garanti för datans riktighet. Sätt inga verifieringsflaggor till true utan att källmaterialet stöder dem.
Backtestkörningen kräver också täckning av hela perioden, månatliga rankingar och medlemskap för varje poängsatt instrument.
Den exporterar kapitalutveckling, årsresultat, affärer, kostnader, CAGR, volatilitet, Sharpe/Sortino (riskfri ränta 0), drawdown, beta och annualiserad regressionsalpha.
Rullande jämförelser använder 252/756/1260 handelsdagar som approximation av 1/3/5 år.

**Inget riktigt historiskt resultat finns ännu.** Dagens börslista får inte användas som om den vore listan från 2010. Senast nedladdade rapportdata kan vara reviderade trots historiskt rapportdatum. Utdelningar, avnoteringar, bolagshändelser, historiskt medlemskap och SIXRX måste verifieras innan full körning.

## Officiell dokumentation

- [Börsdata API](https://github.com/Borsdata-Sweden/API)
- [Kursdata](https://github.com/Borsdata-Sweden/API/wiki/Stockprice)
- [Rapportdata och valutakonvertering](https://github.com/Borsdata-Sweden/API/wiki/Reports)
- [Instrumenttyper och föränderliga relationer](https://github.com/Borsdata-Sweden/API/wiki/Instruments)
- [Officiella datamodeller](https://github.com/Borsdata-Sweden/API-CSharp-Client/tree/master/Borsdata.Api.Dal/Model)
