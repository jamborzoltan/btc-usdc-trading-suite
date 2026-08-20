# BTC/USDC robot – önálló webes projekt

Ez a mappa a BTC/USDC robot webtárhelyre szánt kezelőfelülete. A valós Binance
USDⓈ-M USDC-egyenleget (EEA Futures Credits módban BNFCR-egyenleget) és a nyitott pozíciókat a külön Python robot által írt,
megtisztított runtime-adatból mutatja. API-kulcs nem kerül a webtárhelyre vagy a
böngészőbe.

A Python worker alapból `live_read_only`: valós számlát olvas, de nem küld
megbízást. A külön, helyi konfigurációban engedélyezhető `live` worker a webes
stratégia-, idősík- és kockázati beállításokat market orderekkel hajtja végre.
A Binance API-kulcs ekkor is kizárólag a mini PC-n marad.

A tervezett tőkeáttétel 1–125× között állítható. A tervezett marginfelhasználás
konkrét USDC-összegként, kézzel adható meg két tizedes pontossággal. Éles
belépésnél ez a tervezett kezdeti margin; a névérték ennek és a tőkeáttételnek
a szorzata.

A stop-loss közvetlenül a pozíció becsült, tőkeáttételes PnL%-ában állítható
1–100% között. Például 50% PnL-stop 125× mellett megközelítőleg 0,4%-os
kedvezőtlen BTC-ármozgásnak felel meg, a díjak, funding és csúszás előtt. A
trailing és profitküszöbök továbbra is BTC-ármozgás%-ot jelentenek.

A felület két külön kártyán mutatja az RSI(14) reguláris bullish/bearish
divergenciát 1 órás és 1 napos lezárt gyertyákon. A megerősített pivot-jelzés
információs: nem kapcsolódik közvetlenül az automatikus orderküldéshez.

A kezelőfelület Binance ihlette grafitszürke–sárga színrendszert és kompakt
vezérlőket használ. A fejléc „Chart elrejtése/megjelenítése” gombja a lebegő
gyertyadiagramot kapcsolja; a választást a böngésző vagy a telepített PWA
helyben megjegyzi. Mobilon a visszakapcsolt chart a kijelző szélességéhez igazodik.

## Fájlok

- `index.html` – felület szerkezete
- `styles.css` – megjelenés
- `auth.js` – rövid webes session, PWA-passkey/Face ID és CSRF-védelem
- `app.js` – piaci adatok, stratégia, Binance-runtime megjelenítés és vezérlés
- `manifest.webmanifest` és `sw.js` – telepíthető PWA és offline alkalmazáshéj
- `icons/btc-usdc-robot.svg` – alkalmazásikon
- `api/auth.php` és `api/webauthn.php` – jelszavas és passkey-hitelesítés
- `api/state.php` – strukturált botbeállítás-API, revision-alapú ütközésvédelemmel
- `api/robot-runtime.php` – strukturált státusz-, stratégia-, divergencia-, számla- és pozíció-API
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
`btc_usdc_bot_settings` oszlopaiban vannak. A mini PC futási pillanatképe öt
logikai táblára bomlik: `btc_usdc_robot_status`,
`btc_usdc_strategy_snapshot`, `btc_usdc_divergence_snapshot`,
`btc_usdc_binance_account` és `btc_usdc_open_positions`. Így phpMyAdminban
közvetlenül olvashatók és szűrhetők az értékek.

Meglévő telepítés frissítésekor a `schema.sql` idempotens módon hozzáadja a
`margin_usdc` oszlopot. A korábbi `margin_percent` oszlop megmaradhat legacy
adatként, de az új API már nem olvassa és nem írja.

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
a PHP/MySQL-adatkapu; a külön Python roboté a 0–24-es Binance-számlaolvasás,
jelzésfigyelés és a helyileg, többszörösen reteszelt végrehajtás. Az éles mód
beállítását és működési korlátait a Python projekt `README.md` fájlja írja le.
