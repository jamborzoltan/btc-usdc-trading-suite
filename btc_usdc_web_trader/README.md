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
„Részleges zárás” és a tartás jelhez tartozó, PnL-csúcstól mért visszaesés
szintén közvetlen, tőkeáttételes pozíció-PnL%-ot jelent. Egyedül a trailing stop
marad BTC-ármozgás%-ban megadva.

A 10-es botverzióra frissítés a korábbi két profitküszöböt egyszer
`régi ármozgás% × leverage` képlettel alakítja át, így a már beállított tényleges
aktiválási pont nem változik meg. Az új PnL-küszöbök 0–2500% között, kézzel
írhatók be; a 0 érték kikapcsolja az adott funkciót.

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
- `api/auth.php` és `api/webauthn.php` – többfelhasználós jelszavas és passkey-hitelesítés
- `api/users.php` – adminisztrátori felhasználólétrehozás és robot-token csere
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

## Több felhasználó, külön robotok

Az első, már létező felhasználó automatikusan adminisztrátor lesz, és megtartja
a jelenlegi `state_key` alatti beállításait, runtime-adatait, passkey-jeit és a
`config.php`-ban megadott robot-tokenét. Az admin a bejelentkezés utáni
„Robotok” panelen hozhat létre további felhasználókat. Minden új fiók külön
véletlen `state_key` értéket és külön robot-tokent kap, ezért a beállításai,
Binance-számlaképe és robot-szívverése nem keveredhet más fiókéval.

A nyers robot-token nem kerül MySQL-be; ott kizárólag a SHA-256 hash marad. A
felület a tokent csak létrehozáskor vagy cserekor mutatja meg. Felhasználónként
külön Python folyamatot és külön `robot.cfg` fájlt kell indítani; abba a panelen
kapott `runtime_token` tartozik. Egy robot tokenje a state API olvasásakor és a
runtime API írásakor is ugyanazt a felhasználói teret választja ki.

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
