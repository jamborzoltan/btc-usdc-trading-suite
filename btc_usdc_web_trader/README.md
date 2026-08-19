# BTC/USDC robot – önálló webes projekt

Ez a mappa a BTC/USDC robot webtárhelyre szánt kezelőfelülete. A valós Binance
USDⓈ-M USDC-egyenleget (EEA Futures Credits módban BNFCR-egyenleget) és a nyitott pozíciókat a külön Python robot által írt,
megtisztított runtime-adatból mutatja. API-kulcs nem kerül a webtárhelyre vagy a
böngészőbe.

A jelenlegi kiadás `live_read_only`: valós számlát olvas, de a megbízásküldés
kód szinten zárolt. A stratégia, idősík és kockázati beállítások a közös MySQL
vezérlőállapotba kerülnek.

## Fájlok

- `index.html` – felület szerkezete
- `styles.css` – megjelenés
- `auth.js` – rövid webes session, PWA-passkey/Face ID és CSRF-védelem
- `app.js` – piaci adatok, stratégia, Binance-runtime megjelenítés és vezérlés
- `manifest.webmanifest` és `sw.js` – telepíthető PWA és offline alkalmazáshéj
- `icons/btc-usdc-robot.svg` – alkalmazásikon
- `api/auth.php` és `api/webauthn.php` – jelszavas és passkey-hitelesítés
- `api/state.php` – strukturált botbeállítás-API, revision-alapú ütközésvédelemmel
- `api/robot-runtime.php` – strukturált státusz-, stratégia-, számla- és pozíció-API
- `api/schema.sql` – az alkalmazás MySQL-tábláinak létrehozása
- `api/config.php.example` – kitöltendő MySQL konfigurációs minta

## Tárhelyre feltöltés

A részletes lépéseket a `WEBHOSTING.md` tartalmazza. Az új `schema.sql`-t is
importálni kell, majd az összes webes fájlt – az `api`, `vendor`, `icons`
almappákkal és a gyökér `.htaccess` fájllal együtt – fel kell tölteni.

A `config.php` bizalmas adatot tartalmaz, ezért nem kerül verziókezelésbe és nem
szabad elküldeni vagy nyilvánossá tenni.

## Strukturált MySQL-adatmodell

A tartós robotbeállítások nem egyetlen JSON-payloadban, hanem a
`btc_usdc_bot_settings` oszlopaiban vannak. A mini PC futási pillanatképe négy
logikai táblára bomlik: `btc_usdc_robot_status`,
`btc_usdc_strategy_snapshot`, `btc_usdc_binance_account` és
`btc_usdc_open_positions`. Így phpMyAdminban közvetlenül olvashatók és
szűrhetők az értékek.

Frissítéskor a régi `btc_usdc_robot_state` payloadját a state API egyszer,
automatikusan átemeli az új beállítástáblába. A régi runtime helyett az első új
Python-szívverés tölti fel a strukturált runtime-táblákat. A legacy táblák nem
törlődnek automatikusan.

## PWA telepítés

HTTPS-es tárhelyen a böngésző telepíthető alkalmazásként kínálja fel a robotot.
A service worker csak az alkalmazás felületét gyorsítótárazza; a MySQL állapot
és az élő áradatok mindig hálózatról érkeznek.

Az első jelszavas belépést követő öt percben a „Face ID beállítása” gombbal
regisztrálható passkey. iPhone-on a rendszer a beállított Face ID-t használhatja,
de az iOS szükség esetén készülékkódot is kérhet. A biometrikus adat és a privát
kulcs nem kerül a szerverre. Telepített PWA-ban az „Auto Face ID” kapcsolóval
bekapcsolható az indításkori, egyszeri automatikus passkey-próba.

## Elkülönítés

A folyamatosan futó, böngészőtől független robot új, önálló projektje a
`../btc_usdc_trading_robot` mappában van. A webapp feladata a kezelőfelület és
a PHP/MySQL-adatkapu; a külön Python roboté a 0–24-es Binance-számlaolvasás és
jelzésfigyelés. A későbbi éles végrehajtás kizárólag a Python projektben kap
helyet, külön biztonsági retesz mögött.
