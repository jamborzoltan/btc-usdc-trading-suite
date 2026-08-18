# BTC/USDC robot – önálló webes projekt

Ez a mappa a BTC/USDC robot webtárhelyre szánt kezelőfelülete. A valós Binance
USDⓈ-M USDC-egyenleget és a nyitott pozíciókat a külön Python robot által írt,
megtisztított runtime-adatból mutatja. API-kulcs nem kerül a webtárhelyre vagy a
böngészőbe.

A jelenlegi kiadás `live_read_only`: valós számlát olvas, de a megbízásküldés
kód szinten zárolt. A stratégia, idősík és kockázati beállítások a közös MySQL
vezérlőállapotba kerülnek.

## Fájlok

- `index.html` – felület szerkezete
- `styles.css` – megjelenés
- `app.js` – piaci adatok, stratégia, Binance-runtime megjelenítés és vezérlés
- `manifest.webmanifest` és `sw.js` – telepíthető PWA és offline alkalmazáshéj
- `icons/btc-usdc-robot.svg` – alkalmazásikon
- `api/state.php` – közös MySQL állapot API, prepared `mysqli` lekérdezésekkel
- `api/schema.sql` – MySQL tábla létrehozása
- `api/config.php.example` – kitöltendő MySQL konfigurációs minta

## Tárhelyre feltöltés

A részletes lépéseket a `WEBHOSTING.md` tartalmazza. Röviden: a három kliensfájlt
és az `api/state.php` fájlt töltsd fel, a `schema.sql`-t importáld phpMyAdminban,
majd a saját MySQL-adataiddal kitöltött `api/config.php` fájlt is töltsd fel.

A `config.php` bizalmas adatot tartalmaz, ezért nem kerül verziókezelésbe és nem
szabad elküldeni vagy nyilvánossá tenni.

## PWA telepítés

HTTPS-es tárhelyen a böngésző telepíthető alkalmazásként kínálja fel a robotot.
A service worker csak az alkalmazás felületét gyorsítótárazza; a MySQL állapot
és az élő áradatok mindig hálózatról érkeznek.

## Elkülönítés

A folyamatosan futó, böngészőtől független robot új, önálló projektje a
`../btc_usdc_trading_robot` mappában van. A webapp feladata a kezelőfelület és
a PHP/MySQL-adatkapu; a külön Python roboté a 0–24-es Binance-számlaolvasás és
jelzésfigyelés. A későbbi éles végrehajtás kizárólag a Python projektben kap
helyet, külön biztonsági retesz mögött.
