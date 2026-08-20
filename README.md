# BTC/USDC trading suite

Saját használatú BTC/USDC kereskedési rendszer két, egymástól elkülönített
komponenssel:

- `btc_usdc_trading_robot/` – a mini PC-n folyamatosan futó Python worker;
- `btc_usdc_web_trader/` – mobilbarát PWA kezelőfelület PHP/MySQL adatkapuval.

## Végrehajtási módok

A Python worker alapból `live_read_only` módban valódi Binance USDⓈ-M USDC-
(EEA Futures Credits módban BNFCR-) egyenleget és BTCUSDC pozíciókat olvas.
Külön helyi konfigurációval `live` mód is engedélyezhető; ilyenkor one-way
BTCUSDC market ordereket küld, kötelező névérték-, napi veszteség- és becsült
pozícióveszteség-limittel. A webapp továbbra sem tartalmaz Binance API-kulcsot.
Az aktiválás részletei a `btc_usdc_trading_robot/README.md` fájlban vannak.

A worker ettől független, információs RSI(14) reguláris bullish/bearish
divergenciaindikátort is számol 1 órás és 1 napos lezárt BTCUSDC gyertyákon.
Ez az indikátor nem része az automatikus belépési jelnek.

## Első indítás

### Python robot

1. Másold a `btc_usdc_trading_robot/robot.cfg.example` fájlt `robot.cfg` néven.
2. A helyi `robot.cfg` fájlban add meg a webes runtime végpontot és a Binance
   kulcsokat. Ezt a fájlt a Git kizárja.
3. Egyszeri ellenőrzés:

   ```powershell
   cd .\btc_usdc_trading_robot
   py .\run_robot.py --once
   ```

4. Folyamatos futtatás:

   ```powershell
   py .\run_robot.py
   ```

### Webapp

A telepítési leírás a
`btc_usdc_web_trader/WEBHOSTING.md` fájlban található. A tárhelyes
`api/config.php` fájlt a Git szintén kizárja.

## Ellenőrzések

```powershell
cd .\btc_usdc_trading_robot
py -m unittest discover -s tests -v

cd ..\btc_usdc_web_trader
node --check auth.js
node --check app.js
```

Ezek az ellenőrzések helyben futtathatók; automatikus GitHub Actions CI később
külön workflow-ként adható a repóhoz.

## Titkok kezelése

Soha ne kerüljön commitba API-kulcs, API-secret, MySQL-jelszó vagy runtime
token. A repository létrehozása előtt és minden push előtt ellenőrizd a
`git status` és `git diff --cached` kimenetét. További szabályok:
`SECURITY.md`.
