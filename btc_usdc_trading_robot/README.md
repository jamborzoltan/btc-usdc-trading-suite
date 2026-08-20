# BTC/USDC külön futó kereskedő robot

Ez a mappa a webapptól teljesen különálló Python folyamat. A mini PC-n fog futni,
így a jelzésfigyeléshez nem kell nyitva hagyni sem a weboldalt, sem egy böngészőt.

## Működési módok

A robot jelenlegi feladatai:

- 1–60 másodperces ciklusban kéri a Binance USDⓈ-M BTCUSDC árat és gyertyákat;
- hitelesített, aláírt végpontokról olvassa a valós USDC- vagy EEA Futures Credits
  módban BNFCR-egyenleget és a nyitott
  USDⓈ-M pozíciókat;
- kiszámítja a webappból választott EMA, Momentum, Mean reversion vagy Trend +
  Momentum jelzést;
- RSI(14) alapján reguláris bullish és bearish divergenciát keres az 1 órás és
  1 napos lezárt gyertyák megerősített, 3–3 gyertyás swing-pontjai között;
- a HTTPS/PHP API-n keresztül írja a szívverést, a megtisztított számlaképet, az
  árat és a jelzést egy külön MySQL-futási rekordba;
- a böngészőtől függetlenül fut.

Alapállapotban a robot továbbra is `live_read_only`: nem nyit vagy zár pozíciót.
Külön engedélyezhető `live` módban a lezárt gyertyákon számolt `buy`/`sell`
jelzések alapján egyetlen, one-way BTCUSDC pozíciót kezel market orderekkel.
A pozíció névértéke `marginUsdc × leverage`; a BTC mennyiség a Binance
`MARKET_LOT_SIZE` lépésére lefelé kerekül.

Az éles végrehajtás biztonsági tulajdonságai:

- a helyi `mode = live`, az `enabled = true`, a pontos acknowledgement mondat
  és a webes Stratégiafigyelés kapcsoló egyszerre szükséges az új belépéshez;
- a megbízások determinisztikus `newClientOrderId`-t kapnak, ezért hálózati
  timeout után a robot előbb ugyanazt az ordert kérdezi vissza;
- új belépést korlátoz a maximális order-névérték, a napi nettó realizált
  veszteség és a közvetlenül pozíció-PnL%-ban megadott stop;
- a limitek a reduce-only zárást nem blokkolják;
- a robot csak a saját, helyi `execution_state.json` állapotával igazolt
  pozícióját módosítja; egy kézzel vagy másik rendszerrel nyitott pozíciót csak
  megjelenít;
- külső pozícióbővítés, irány- vagy belépőár-változás esetén automatikusan
  lemond a pozíció kezeléséről;
- a stratégia kikapcsolása letiltja az új belépést, de a már kezelt pozíció
  stop- és trailing-védelmét nem kapcsolja le.
- a részleges profitküszöb és a tartás jel utáni profit-visszaesés közvetlenül
  a becsült, tőkeáttételes pozíció-PnL%-ot használja; a trailing stop továbbra
  is az instrumentum ármozgását méri;
- a legutóbbi kockázati beállítások a helyi állapotfájlba kerülnek; ha a webes
  state API kiesik, új belépés nem történik, de a már kezelt pozíció szoftveres
  védelme az utolsó ismert beállításokkal tovább fut.
- ticker- vagy gyertyaadat-hibánál szintén nincs új belépés és stratégiai
  fordítás, de a saját pozíció mark-price alapú stop/trailing védelme tovább
  fut a hitelesített Binance account snapshotból.

Fontos: a stop-loss, trailing, részleges profit és profit-visszaesés jelenleg a
mini PC folyamatában felügyelt market zárás. Ha a mini PC, az internet vagy a
Binance API nem érhető el, ezek nem tudnak végrehajtódni; nincs külön, tőzsdén
nyugvó védő stop order. Éles használat előtt ezt a működési kockázatot vedd
figyelembe.

## RSI-divergenciaindikátor

Az indikátor 250 gyertyát kér le idősíkonként, az aktuálisan még nyitott gyertyát
kihagyja, majd Wilder RSI(14)-et számol. Bullish reguláris divergencia akkor
keletkezik, ha az ár alacsonyabb swing-mélypontot, az RSI pedig magasabb
mélypontot képez. Bearish divergenciánál az ár magasabb swing-csúcsot, az RSI
alacsonyabb csúcsot képez. A jel a második pivot utáni három gyertya lezárásával
válik megerősítetté, és legfeljebb 20 lezárt gyertyán át számít frissnek.

Ez külön információs indikátor. Nem módosítja a kiválasztott stratégia
`buy`/`sell` jelét, ezért önmagában nem nyit és nem zár pozíciót.

## Elrendezés

```text
btc_usdc_web_trader/       # webapp: felület, vezérlés, MySQL/PHP API
btc_usdc_trading_robot/    # mini PC: folyamatos Python folyamat (ez a mappa)
```

A mini PC nem kapcsolódik közvetlenül a távoli MySQL-hez. A webapp vezérlőállapotát
csak olvassa az `api/state.php` végponton, míg a saját állapotát a külön
`api/robot-runtime.php` végpontba írja. Ez megakadályozza, hogy egy szívverés
felülírja az Automatikus mód kapcsolót. Az SQL a tárhelyen, prepared `mysqli`
lekérdezésekkel fut.

## Első indítás Windows alatt

1. Telepíts Python 3.11 vagy újabb változatot a mini PC-re.
2. Másold ezt a teljes `btc_usdc_trading_robot` mappát a mini PC-re.
3. A meglévő `robot.cfg` titkos fájlt ne írd felül. Az új mezőket a
   `robot.cfg.example` alapján másold bele: elsőként `mode = live_read_only`, továbbá a
   `[binance_usdm]` részben az API-kulcs, secret és `BTCUSDC` szimbólum kell. Az
   első ellenőrzéshez a Binance-kulcson csak olvasási jogosultságot használj.
   Töltsd ki az `url` és `runtime_url` címet, valamint a `runtime_token` titkot.
   Többfelhasználós telepítésnél ezt az adott felhasználó „Robotok” paneljén
   kapott konfigurációból másold át. Az első, korábbról meglévő admin robotjánál
   ez megegyezhet a webapp `api/config.php` fájljának `robot_runtime_token`
   értékével. A robot ezzel olvassa a védett állapot-API-t is. A két URL
   ugyanazon webapphoz tartozik: ha például az oldal címe
   `https://sajatdomain.hu/robot/`, akkor a két cím rendre
   `https://sajatdomain.hu/robot/api/state.php` és
   `https://sajatdomain.hu/robot/api/robot-runtime.php`.
4. Nyiss PowerShellt a mappában, majd egyszeri kapcsolati próbához futtasd:

   ```powershell
   py .\run_robot.py --once
   ```

5. Ha ez rendben lefut, a folyamatos megfigyelő robot indítása:

   ```powershell
   py .\run_robot.py
   ```

Leállítás: `Ctrl+C`. A későbbi, 0–24-es telepítésnél ezt Windows Feladatütemező
vagy szolgáltatás indítja automatikusan a gép indulásakor.

## Több felhasználó futtatása

Minden webapp-felhasználóhoz külön Python robot tartozik. A folyamatok ugyanazt
a programkódot használhatják, de külön `robot.cfg`, Binance API-kulcs és
`execution_state.json` kell nekik. A `--config` kapcsolóval több példány
indítható ugyanazon a gépen:

```powershell
py .\run_robot.py --config .\users\anna\robot.cfg
py .\run_robot.py --config .\users\bela\robot.cfg
```

Az egyedi `runtime_token` választja ki a felhasználó saját webes beállításait és
runtime-rekordjait. Ne másold ugyanazt a tokent két felhasználó konfigurációjába,
és minden konfigurációban adj külön `state_file` elérési utat.

Az első sikeres `--once` próba után a webappban a valós USDC- (EEA Futures Credits
módban BNFCR-) tárcaegyenlegnek,
az elérhető egyenlegnek és az esetleges BTCUSDC pozíciónak kell megjelennie.
Hibás kulcs, IP-korlátozás vagy jogosultság esetén a robot csak hibastátuszt ír;
megbízást nem próbál küldeni.

## Éles mód engedélyezése

Csak a sikeres read-only próba után állítsd a Binance fiókot **one-way**
pozíciómódra, adj a külön API-kulcsnak USDⓈ-M Futures kereskedési jogosultságot,
és lehetőleg korlátozd a mini PC publikus IP-címére. Ezután a helyi, gitből
kizárt `robot.cfg` releváns része például:

```ini
[robot]
mode = live

[live_trading]
enabled = true
acknowledgement = ENGEDÉLYEZEM_A_BTCUSDC_ÉLES_KERESKEDÉST
max_order_notional_usdc = 25
max_daily_loss_usdc = 5
max_position_loss_percent = 50
state_file = execution_state.json
```

A példaszámok nem ajánlások. A `max_order_notional_usdc` a teljes tőkeáttételes
névértéket korlátozza, nem csak a felhasznált margint. A
`max_position_loss_percent` a webes `stopLossPercent` PnL%-ot korlátozza. A
stophoz tartozó közelítő kedvezőtlen BTC-ármozgás
`stopLossPercent / leverage`; ez díjakat, fundingot, csúszást és maintenance
margint nem modellez. Ha a webes beállítás a helyi korlát fölé kerül, a worker
blokkolja az új belépést. A 8-as botverzió korábbi ármozgás%-os stopját a rendszer
egyszer `régi stop × leverage` értékkel migrálja PnL%-ra, legfeljebb 100%-ig.
A 10-es verzió ugyanígy migrálja a korábbi ármozgás-alapú részleges profit- és
profit-visszaesési küszöböt PnL%-ra, legfeljebb 2500%-ig.

Az első éles próbánál használj kicsi limiteket, futtasd egyszer `--once`
kapcsolóval úgy, hogy a Stratégiafigyelés ki van kapcsolva, majd ellenőrizd a
felületen az „Éles megbízás engedélyezve” állapotot. A kapcsolót csak ezután
kapcsold be. A `robot.cfg` és az `execution_state.json` ne kerüljön a webtárhelyre
vagy verziókezelésbe.

## Webes védelem

A webapp böngészős elérését saját PHP-session és passkey-védelem kezeli. A mini
PC nem használja a webes jelszót: a felhasználónként egyedi `runtime_token`
kerül az `X-Robot-Token` fejlécbe. Ha a tárhelyen ezen felül HTTP Basic Auth is aktív, a `username` és
`password` mezők továbbra is használhatók; ezek csak a mini PC-n maradnak.
