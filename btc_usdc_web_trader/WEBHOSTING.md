# BTC/USDC robot – webes kiadás

Ez az önálló webes projekt az ELIN Bronze tárhelyre készült. A további webes
fejlesztések ebben a mappában történnek; a szomszédos Python-projekt ettől
függetlenül megmarad.

## Feltöltés

Az ELIN tárhelykezelőjében nyisd meg a választott domain `web` mappáját, majd
töltsd fel ebbe a három kliensfájlt ebből a projektmappából:

- `index.html`
- `styles.css`
- `app.js`
- `manifest.webmanifest`
- `sw.js`
- `icons/btc-usdc-robot.svg` (az `icons` almappával együtt)

Ne töltsd fel a Python robot fájljait, a `robot.cfg` fájlt, build- és
release-fájlokat. A `robot.cfg` tartalmazza a Binance-kulcsokat, ezért kizárólag
a mini PC-n maradhat.

## Közös MySQL tárolás beállítása

Ez a lépés teszi lehetővé, hogy minden gépen és böngészőben ugyanaz a
stratégia-, idősík- és kockázati vezérlőállapot jelenjen meg. A valós
Binance-számlakép külön runtime-rekordból érkezik.

1. A tárhely MySQL-kezelőjében hozz létre egy adatbázist és egy hozzá tartozó,
   teljes jogosultságú adatbázis-felhasználót.
2. A phpMyAdminban futtasd újra a projekt `api/schema.sql` fájlját. Ez létrehozza
   a vezérlőállapot `btc_usdc_robot_state` és a külön robot-futási
   `btc_usdc_robot_runtime` táblát is; a meglévő állapot nem törlődik.
3. A projekt `api` mappájában másold a `config.php.example` fájlt `config.php`
   néven, és töltsd ki a tárhelyes MySQL-adatokkal.
4. A tárhely `web` mappájában hozd létre az `api` almappát, majd töltsd fel ide
   a `state.php`, `robot-runtime.php` és a kitöltött `config.php` fájlt. A
   `schema.sql` csak az importhoz kell, feltöltése nem szükséges.

A `config.php` adatbázisjelszót tartalmaz: ne küldd el, ne tedd nyilvános
letöltési mappába, és ne töltsd fel Gitbe. A kliens automatikusan megkeresi az
`api/state.php` végpontot. Ha az elérhető, onnantól minden módosítás MySQL-be
mentődik; ha még nincs beállítva, a korábbi helyi böngészős tárolás marad aktív.

A `config.php` fájlba a `robot_runtime_token` értéket is vedd fel ugyanazzal a
legalább 24 karakteres titokkal, amely a mini PC `robot.cfg` fájljában szerepel.
Ezt a titkot csak a mini PC küldi el a robot futási állapotának írásakor; a
böngésző soha nem kapja meg.

Az API minden SQL-művelete előkészített `mysqli` lekérdezést használ. A
mentések állapotverziót is használnak: ha két eszköz egyszerre módosítana,
az oldal a legfrissebb közös állapotot tölti vissza, nem írja felül csendben.

Mivel ez egy saját, közös állapot, javasolt a tárhely kezelőfelületén jelszóval
védeni legalább az `api` mappát, vagy magát az egész webes robotot. A MySQL
jelszava így soha nem kerül böngészőbe vagy JavaScript-fájlba.

## Működés a tárhelyen

A feltöltött oldal a nyilvános Binance USDⓈ-M BTCUSDC ár- és gyertyaadatokat
közvetlenül a böngészőből kéri le. A négy stratégia és a tervezett kockázati
beállítások működnek; böngészős pozíciószimuláció nincs. A lebegő chart 394 CSS
pixel szélességtől látható;
az iPhone 16 álló nézetének megfelelő, 393 px-es vagy keskenyebb kijelzőn
rejtve marad.

A Binance USDⓈ-M fiókegyenleg panel a mini PC által a
`api/robot-runtime.php` végpontba írt, megtisztított számlaképet mutatja. A
titkos kulcs ettől még soha nem kerül a böngészőbe vagy a webtárhelyre.

## Progresszív webalkalmazás (PWA)

A projekt telepíthető PWA-ként is. Ehhez HTTPS-en kell megnyitnod az oldalt,
mert a service worker biztonságos kapcsolatot igényel. Chrome/Edge alatt a
címsor melletti telepítés ikonra kattintva, mobilon pedig a böngésző
„Telepítés” vagy „Kezdőképernyőhöz adás” menüpontjával telepíthető.

A PWA az alkalmazás felületét gyorsítótárazza, ezért az oldal megnyitható akkor
is, ha rövid időre nincs hálózat. A MySQL `api` végpont és az élő piaci adatok
viszont nem kerülnek cache-be: kapcsolat nélkül a MySQL jelző piros lesz, és
az elavult robot-szívverést és Binance-számlaképet figyelmeztetéssel jelöljük.

## Korlátok

- A közös MySQL-mentés csak akkor aktív, ha a fenti `api/state.php` és
  `api/config.php` telepítve van. Enélkül a vezérlőbeállítások böngészőnként,
  helyben tárolódnak.
- Az oldal internetkapcsolatot és elérhető Binance publikus API-t igényel.
- A külön Python robotnak folyamatosan futnia kell a valós számlaadat
  frissítéséhez.
- A jelenlegi `live_read_only` kiadás nem küld valódi tőzsdei megbízást.

A Binance API-kulcsot és secretet nem szabad webtárhelyre vagy böngészőbe
feltölteni; ezek csak a mini PC `robot.cfg` fájljában lehetnek.
