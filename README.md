# BTC/USDC trading suite

Saját használatú BTC/USDC kereskedési rendszer két, egymástól elkülönített
komponenssel:

- `btc_usdc_trading_robot/` – a mini PC-n folyamatosan futó Python worker;
- `btc_usdc_web_trader/` – mobilbarát PWA kezelőfelület PHP/MySQL adatkapuval.

## Jelenlegi biztonsági állapot

A Python worker `live_read_only` módban valódi Binance USDⓈ-M USDC-egyenleget
és BTCUSDC pozíciókat olvas. Valódi megbízást még nem küldhet: az order-réteg
kód szinten zárolt, a webapp pedig nem tartalmaz Binance API-kulcsot.

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
node --check app.js
```

Ezek az ellenőrzések helyben futtathatók; automatikus GitHub Actions CI később
külön workflow-ként adható a repóhoz.

## Titkok kezelése

Soha ne kerüljön commitba API-kulcs, API-secret, MySQL-jelszó vagy runtime
token. A repository létrehozása előtt és minden push előtt ellenőrizd a
`git status` és `git diff --cached` kimenetét. További szabályok:
`SECURITY.md`.
