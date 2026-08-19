# BTC/USDC robot – webes kiadás

Ez az önálló webes projekt az ELIN Bronze tárhelyre készült. A további webes
fejlesztések ebben a mappában történnek; a szomszédos Python-projekt ettől
függetlenül megmarad.

## Feltöltés

Az ELIN tárhelykezelőjében nyisd meg a választott domain `web` mappáját. Töltsd
fel a projekt teljes webes tartalmát, beleértve ezeket is:

- `index.html`
- `styles.css`
- `auth.js`
- `app.js`
- `manifest.webmanifest`
- `sw.js`
- `icons/btc-usdc-robot.svg` (az `icons` almappával együtt)
- `.htaccess`
- az `api` mappa PHP-fájljai
- a `vendor/lbuchs/webauthn` mappa és a `vendor/.htaccess`

Ne töltsd fel a Python robot fájljait, a `robot.cfg` fájlt, build- és
release-fájlokat. A `robot.cfg` tartalmazza a Binance-kulcsokat, ezért kizárólag
a mini PC-n maradhat.

## Frissítési sorrend a jelenlegi oldalhoz

1. Először másold a mini PC-re a friss Python-projektet, a meglévő titkos
   `robot.cfg` megtartásával, majd indítsd újra a robotot. Az új kliens már
   elküldi a meglévő `runtime_token` értéket a state API-nak is; a régi PHP API
   ezt az extra fejlécet még egyszerűen figyelmen kívül hagyja.
2. Importáld az új `schema.sql` fájlt és egészítsd ki a tárhelyes `config.php`-t.
3. Ezután töltsd fel a webes fájlokat. Így az új, védett state API megjelenésekor
   a robot már rendelkezik a szükséges gépi hitelesítéssel.
4. Végezd el az egyszeri webes jelszóbeállítást, majd az iPhone-on regisztráld a
   Face ID/passkey-t.

## Közös MySQL tárolás beállítása

Ez a lépés teszi lehetővé, hogy minden gépen és böngészőben ugyanaz a
stratégia-, idősík- és kockázati vezérlőállapot jelenjen meg. A valós
Binance-számlakép külön runtime-rekordból érkezik.

1. A tárhely MySQL-kezelőjében hozz létre egy adatbázist és egy hozzá tartozó,
   teljes jogosultságú adatbázis-felhasználót.
2. A phpMyAdminban futtasd újra a projekt `api/schema.sql` fájlját. A két
   robottábla mellett létrejön a felhasználó-, passkey- és belépéskorlátozó
   tábla is; a meglévő robotállapot nem törlődik.
3. A projekt `api` mappájában másold a `config.php.example` fájlt `config.php`
   néven, és töltsd ki a tárhelyes MySQL-adatokkal.
4. A saját, már kitöltött `api/config.php` fájlodba másold át a minta új
   `auth_*` és session-beállításait. Az `auth_rp_id` pontosan a webapp domainje
   legyen, például `moldaxis.hu`, `https://` és elérési út nélkül. Az
   `auth_setup_token` egy új, legalább 32 karakteres véletlen titok legyen.
5. Töltsd fel az `api/auth-common.php`, `auth.php`, `webauthn.php`, `state.php`
   és `robot-runtime.php` fájlokat, majd külön a saját `config.php` fájlodat.
   A `schema.sql` csak az importhoz kell.
6. Nyisd meg az oldalt HTTPS-en. Az első képernyőn add meg a configban lévő
   `auth_username` és `auth_setup_token` értéket, továbbá hozz létre legalább
   12 karakteres jelszót. Ez a beállítás csak egyszer hajtható végre.

Új setup- vagy robot-token például ezzel készíthető; a két célhoz két külön
eredményt használj:

```powershell
py -c "import secrets; print(secrets.token_urlsafe(48))"
```

A `config.php` adatbázisjelszót, setup tokent és robot-tokent tartalmaz: ne küldd el, ne tedd nyilvános
letöltési mappába, és ne töltsd fel Gitbe. A kliens automatikusan megkeresi az
`api/state.php` végpontot. Ha az elérhető, onnantól minden módosítás MySQL-be
mentődik; ha még nincs beállítva, a korábbi helyi böngészős tárolás marad aktív.

A `config.php` fájlba a `robot_runtime_token` értéket is vedd fel ugyanazzal a
legalább 24 karakteres titokkal, amely a mini PC `robot.cfg` fájljában szerepel.
Ezt a titkot a mini PC a vezérlőállapot olvasásakor és a futási állapot írásakor
küldi; a böngésző soha nem kapja meg.

Az API minden SQL-művelete előkészített `mysqli` lekérdezést használ. A
mentések állapotverziót is használnak: ha két eszköz egyszerre módosítana,
az oldal a legfrissebb közös állapotot tölti vissza, nem írja felül csendben.

Az oldal és a valósadat-API-k most már beépített session-hitelesítést használnak.
Az állapotmódosítások CSRF-tokenhez kötöttek, a hibás jelszavak száma pedig
MySQL-ben korlátozott. A gyökér `.htaccess` letiltja a könyvtárlistázást és
közvetlenül védi a konfigurációs fájlneveket.

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

### Face ID / passkey

1. Először jelszóval jelentkezz be az iPhone-on.
2. Öt percen belül válaszd a „Face ID beállítása” gombot.
3. Fogadd el az iOS passkey-létrehozását.
4. A következő belépéskor válaszd a „Belépés Face ID-val / passkey-jel” gombot.

A WebAuthn csak HTTPS-en működik, és a passkey az `auth_rp_id` domainhez kötődik.
Az alkalmazás kötelező felhasználó-ellenőrzést kér; hogy az iOS éppen Face ID-t
vagy készülékkódot használ, azt maga a rendszer dönti el. A normál webes session
alapból 15 perc inaktivitás után, de legkésőbb 1 óra múlva lejár. A telepített
PWA sikeres passkey-belépése alapból 12 órás inaktivitási és 24 órás abszolút
korlátot kap. Ezek az `api/config.php` fájlban rövidíthetők.

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
