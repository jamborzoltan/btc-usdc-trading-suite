# BTC/USDC külön futó kereskedő robot

Ez a mappa a webapptól teljesen különálló Python folyamat. A mini PC-n fog futni,
így a jelzésfigyeléshez nem kell nyitva hagyni sem a weboldalt, sem egy böngészőt.

## Jelenlegi fázis – valós Binance-számla, zárolt végrehajtás

A robot jelenlegi feladatai:

- 1–60 másodperces ciklusban kéri a Binance USDⓈ-M BTCUSDC árat és gyertyákat;
- hitelesített, aláírt végpontokról olvassa a valós USDC-egyenleget és a nyitott
  USDⓈ-M pozíciókat;
- kiszámítja a webappból választott EMA, Momentum, Mean reversion vagy Trend +
  Momentum jelzést;
- a HTTPS/PHP API-n keresztül írja a szívverést, a megtisztított számlaképet, az
  árat és a jelzést egy külön MySQL-futási rekordba;
- a böngészőtől függetlenül fut.

Ebben a fázisban **nem nyit vagy zár pozíciót**. Az API-kulcs kizárólag a mini
PC-n lévő, verziókezelésből kizárt `robot.cfg` fájlban marad. A Python kliensben
nincs order-küldő metódus, a `[live_trading] enabled = true` pedig indítási
hibát okoz. Ez szándékos biztonsági retesz.

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
   `robot.cfg.example` alapján másold bele: `mode = live_read_only`, továbbá a
   `[binance_usdm]` részben az API-kulcs, secret és `BTCUSDC` szimbólum kell. Az
   első ellenőrzéshez a Binance-kulcson csak olvasási jogosultságot használj.
   Töltsd ki az `url` és `runtime_url` címet, valamint a `runtime_token` titkot. A két URL
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

Az első sikeres `--once` próba után a webappban a valós USDC-tárcaegyenlegnek,
az elérhető egyenlegnek és az esetleges BTCUSDC pozíciónak kell megjelennie.
Hibás kulcs, IP-korlátozás vagy jogosultság esetén a robot csak hibastátuszt ír;
megbízást nem próbál küldeni.

## Webes védelem

A webappot és különösen az `api` útvonalat célszerű jelszóval védeni. Ha HTTP
Basic Auth van beállítva, a robot `robot.cfg` fájljában is töltsd ki a
`username` és `password` értékeket. Ezek a hitelesítési adatok csak a mini PC-n
maradnak; a konfigurációt a `.gitignore` kizárja.
