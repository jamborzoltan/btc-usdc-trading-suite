# Biztonsági szabályok

Ez pénzügyi fiókhoz kapcsolódó, saját használatú projekt. A repository legyen
privát, és a hozzáférést csak a szükséges GitHub-fiókok kapják meg.

## Soha ne commitold

- Binance API-kulcs vagy API-secret;
- MySQL felhasználónév vagy jelszó;
- `robot_runtime_token` értéke;
- `auth_setup_token` értéke vagy a webapp jelszava;
- valódi `robot.cfg`, `binance.cfg`, `.env` vagy `api/config.php` fájl;
- olyan napló, amely hitelesítési adatot vagy aláírt API-kérést tartalmaz.

Ha egy kulcs valaha commitba, issue-ba vagy beszélgetésbe került, ne csak töröld
a fájlból: vond vissza a szolgáltatónál, és készíts új kulcsot.

## Binance

- Használj külön API-kulcsot ehhez a robothoz.
- Korlátozd a mini PC nyilvános IP-címére.
- Az első, `live_read_only` tesztek alatt a kereskedési jogosultság maradjon
  kikapcsolva.
- A kiutalási jogosultság mindig maradjon kikapcsolva.
- Éles módhoz használd a kötelező acknowledgement reteszt, pozitív order- és
  napi veszteséglimitet, valamint a pozíció PnL%-ában megadott stopkorlátot.
- Az `execution_state.json` a mini PC helyi biztonsági állapota; ne töltsd fel
  webtárhelyre, ne szerkeszd kézzel és ne commitold.
- A jelenlegi stopok szoftveresen felügyeltek. A mini PC vagy a hálózat leállása
  alatt nem adható ki automatikus zárás, ezért az éles kitettséget ennek
  megfelelően korlátozd.

## Probléma bejelentése

Biztonsági hibához ne csatolj valódi kulcsot, konfigurációt vagy számlaadatot.
Privát repó esetén is maszkolt naplórészletet használj.
