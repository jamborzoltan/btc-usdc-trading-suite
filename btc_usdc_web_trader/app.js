    const KEY = "btc-usdc-live-control-v1";
    const SHARED_STATE_API_URL = "api/state.php";
    const ROBOT_RUNTIME_API_URL = "api/robot-runtime.php";
    const SHARED_STATE_TIMEOUT_MS = 4000;
    const SHARED_STATE_REFRESH_MS = 2000;
    const MIN_WORKER_HEARTBEAT_TIMEOUT_MS = 15000;
    const CHART_WINDOW_KEY = "btc-usdc-robot-chart-window-v1";
    const BINANCE_PUBLIC_API = "https://fapi.binance.com/fapi/v1";
    const BROWSER_CANDLE_INTERVALS = { 15:"15m", 60:"1h", 1440:"1d" };
    let price = null;
    let refreshTimer = null;
    let selectedInterval = 15;
    let candles = [];
    let latestStrategy = null;
    let latestBinanceAccount = null;
    let strategySignals = {};
    let chartWindowState = null;
    let chartWindowInteraction = null;
    let browserMarketData = window.location.protocol === "file:";
    const STRATEGY_TYPES = [
      { id:"trend", label:"EMA" },
      { id:"momentum", label:"Momentum" },
      { id:"mean_reversion", label:"Mean rev." },
      { id:"trend_impulse", label:"Trend+mom." },
    ];
    const sharedState = { enabled:false, revision:0, saveTimer:null, saving:false, pendingSave:false, syncing:false };
    function readLocalPortfolio() {
      try {
        const stored = JSON.parse(localStorage.getItem(KEY));
        return stored && typeof stored === "object" ? stored : {};
      } catch {
        return {};
      }
    }
    let portfolio = readLocalPortfolio();
    const el = id => document.getElementById(id);
    // Az USDC stabilcoin, nem ISO 4217 pénznemkód; ezért a feliratot kézzel tesszük hozzá.
    const money = value => `${new Intl.NumberFormat("hu-HU", { minimumFractionDigits:2, maximumFractionDigits:2 }).format(value)} USDC`;
    const assetMoney = (value, asset = "USDC") => Number.isFinite(Number(value))
      ? `${new Intl.NumberFormat("hu-HU", { minimumFractionDigits:2, maximumFractionDigits:2 }).format(Number(value))} ${String(asset || "USDC").toUpperCase()}`
      : "—";
    const usdc = value => Number.isFinite(Number(value)) ? money(Number(value)) : "—";
    const num = value => new Intl.NumberFormat("hu-HU", { maximumFractionDigits: 4 }).format(value);
    const safeHtml = value => String(value).replace(/[&<>"']/g, character => ({ "&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;" })[character]);
    function persistLocal() {
      try { localStorage.setItem(KEY, JSON.stringify(portfolio)); } catch { /* A közös mentés ettől még működhet. */ }
    }

    function queueSharedSave() {
      if (!sharedState.enabled) return;
      if (sharedState.saveTimer) clearTimeout(sharedState.saveTimer);
      sharedState.saveTimer = setTimeout(saveSharedPortfolio, 350);
    }

    const persist = () => {
      persistLocal();
      queueSharedSave();
    };

    function setSharedStateNotice(message) {
      const status = el("status");
      if (status) status.textContent = message;
    }

    function setMySqlConnectionIndicator(state) {
      const indicator = el("mysqlConnectionIndicator");
      const text = el("mysqlConnectionText");
      if (!indicator || !text) return;
      const states = {
        active:"MySQL kapcsolat aktív",
        inactive:"MySQL kapcsolat nincs",
        checking:"MySQL kapcsolat ellenőrzése…",
      };
      indicator.className = `mysql-connection-indicator ${state}`;
      text.textContent = states[state] || states.inactive;
    }

    async function readSharedResponse(response) {
      const data = await response.json().catch(() => null);
      if (!data || typeof data !== "object") throw new Error("Érvénytelen közös tárolási válasz.");
      return data;
    }

    async function requestSharedState(url, options = {}) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), SHARED_STATE_TIMEOUT_MS);
      try {
        if (!window.BtcAuth) throw new Error("A hitelesítési modul nem érhető el.");
        return await window.BtcAuth.secureFetch(url, { cache:"no-store", ...options, signal:controller.signal });
      } finally {
        clearTimeout(timeout);
      }
    }

    function applySharedPortfolio(data) {
      if (!data?.portfolio || typeof data.portfolio !== "object") return false;
      portfolio = data.portfolio;
      // A külön Python robot futási adata külön MySQL rekordból érkezik. A régi,
      // egyrekordos változatban eltárolt értéket nem jelenítjük meg új adatként.
      if (portfolio.bot && typeof portfolio.bot === "object") delete portfolio.bot.worker;
      sharedState.revision = Math.max(0, Number(data.revision) || 0);
      persistLocal();
      ensureBot();
      return true;
    }

    async function loadSharedPortfolio() {
      if (window.location.protocol === "file:") {
        setMySqlConnectionIndicator("inactive");
        return false;
      }
      try {
        const response = await requestSharedState(SHARED_STATE_API_URL, { headers:{ Accept:"application/json" } });
        if (!response.ok) {
          setMySqlConnectionIndicator("inactive");
          return false;
        }
        const data = await readSharedResponse(response);
        sharedState.enabled = true;
        sharedState.revision = Math.max(0, Number(data.revision) || 0);
        if (!applySharedPortfolio(data)) persist();
        setMySqlConnectionIndicator("active");
        return true;
      } catch {
        setMySqlConnectionIndicator("inactive");
        return false;
      }
    }

    async function refreshWorkerRuntime() {
      try {
        const response = await requestSharedState(ROBOT_RUNTIME_API_URL, { headers:{ Accept:"application/json" } });
        if (!response.ok) return;
        const data = await readSharedResponse(response);
        const worker = data?.runtime;
        ensureBot();
        if (worker && typeof worker === "object") {
          portfolio.bot.worker = worker;
          latestBinanceAccount = worker.account?.connected ? worker.account : null;
        } else {
          delete portfolio.bot.worker;
          latestBinanceAccount = null;
        }
        render();
      } catch {
        // A felület a legutóbbi ismert robot-szívverést mutatja; a MySQL-jelző
        // külön jelzi, ha a közös állapot közben nem elérhető.
      }
    }

    async function refreshSharedPortfolio() {
      // Nem húzunk vissza távoli állapotot addig, amíg a felhasználó saját
      // módosítása a 350 ms-os mentési sorban vagy tényleges mentés alatt van.
      if (!sharedState.enabled || sharedState.saveTimer || sharedState.saving || sharedState.syncing) return;
      sharedState.syncing = true;
      try {
        const response = await requestSharedState(SHARED_STATE_API_URL, { headers:{ Accept:"application/json" } });
        if (!response.ok) return;
        const data = await readSharedResponse(response);
        const remoteRevision = Math.max(0, Number(data.revision) || 0);
        if (remoteRevision <= sharedState.revision || !data?.portfolio || typeof data.portfolio !== "object") return;
        applySharedPortfolio(data);
        render();
        setMySqlConnectionIndicator("active");
      } catch {
        // Az utolsó ismert, már betöltött portfólió a képernyőn marad. A következő
        // ciklus újrapróbálja; ezzel rövid hálózati hiba nem nullázza a felületet.
      } finally {
        sharedState.syncing = false;
      }
    }

    async function saveSharedPortfolio() {
      sharedState.saveTimer = null;
      if (!sharedState.enabled) return;
      if (sharedState.saving) {
        sharedState.pendingSave = true;
        return;
      }
      sharedState.saving = true;
      const expectedRevision = sharedState.revision;
      const stateSnapshot = JSON.parse(JSON.stringify(portfolio));
      if (stateSnapshot.bot && typeof stateSnapshot.bot === "object") delete stateSnapshot.bot.worker;
      try {
        const response = await requestSharedState(SHARED_STATE_API_URL, {
          method:"POST",
          headers:{ "Content-Type":"application/json", Accept:"application/json" },
          body:JSON.stringify({ portfolio:stateSnapshot, revision:expectedRevision }),
        });
        const data = await readSharedResponse(response);
        if (response.status === 409) {
          applySharedPortfolio(data);
          render();
          setMySqlConnectionIndicator("active");
          setSharedStateNotice("A közös állapotot közben egy másik eszköz módosította; a friss adat betöltődött.");
          return;
        }
        if (!response.ok) throw new Error(data.error || "A közös mentés nem sikerült.");
        sharedState.revision = Math.max(0, Number(data.revision) || expectedRevision);
        setMySqlConnectionIndicator("active");
      } catch {
        sharedState.enabled = false;
        setMySqlConnectionIndicator("inactive");
        setSharedStateNotice("A közös MySQL mentés átmenetileg nem érhető el; a módosítás helyben megmaradt.");
      } finally {
        sharedState.saving = false;
        if (sharedState.pendingSave) {
          sharedState.pendingSave = false;
          queueSharedSave();
        }
      }
    }

    const clamp = (value, minimum, maximum) => Math.min(Math.max(value, minimum), maximum);

    function readChartWindowState() {
      try {
        const stored = JSON.parse(localStorage.getItem(CHART_WINDOW_KEY));
        return stored && typeof stored === "object" ? stored : {};
      } catch {
        return {};
      }
    }

    function normalizeChartWindowState(state = {}) {
      const margin = 12;
      const bottomBarHeight = 100;
      const maximumWidth = Math.max(240, window.innerWidth - margin * 2);
      const maximumHeight = Math.max(200, window.innerHeight - bottomBarHeight - margin * 2);
      const minimumWidth = Math.min(360, maximumWidth);
      const minimumHeight = Math.min(280, maximumHeight);
      const width = clamp(Number(state.width) || Math.min(620, maximumWidth), minimumWidth, maximumWidth);
      const height = clamp(Number(state.height) || Math.min(430, maximumHeight), minimumHeight, maximumHeight);
      const maximumLeft = Math.max(margin, window.innerWidth - width - margin);
      const maximumTop = Math.max(margin, window.innerHeight - bottomBarHeight - height - margin);
      const defaultLeft = maximumLeft;
      const defaultTop = Math.min(86, maximumTop);
      return {
        width,
        height,
        left: clamp(Number(state.left) || defaultLeft, margin, maximumLeft),
        top: clamp(Number(state.top) || defaultTop, margin, maximumTop),
      };
    }

    function applyChartWindowState(nextState, shouldPersist = false) {
      chartWindowState = normalizeChartWindowState(nextState);
      const chartWindow = el("chartWindow");
      chartWindow.style.width = `${chartWindowState.width}px`;
      chartWindow.style.height = `${chartWindowState.height}px`;
      chartWindow.style.left = `${chartWindowState.left}px`;
      chartWindow.style.top = `${chartWindowState.top}px`;
      chartWindow.style.right = "auto";
      if (shouldPersist) localStorage.setItem(CHART_WINDOW_KEY, JSON.stringify(chartWindowState));
      requestAnimationFrame(drawCandles);
    }

    function finishChartWindowInteraction(event) {
      if (!chartWindowInteraction || event.pointerId !== chartWindowInteraction.pointerId) return;
      chartWindowInteraction = null;
      el("chartWindow").classList.remove("dragging", "resizing");
      localStorage.setItem(CHART_WINDOW_KEY, JSON.stringify(chartWindowState));
    }

    function beginChartWindowInteraction(event, mode) {
      if (event.button !== 0 || chartWindowInteraction) return;
      const chartWindow = el("chartWindow");
      chartWindowInteraction = {
        mode,
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        startState: { ...chartWindowState },
      };
      chartWindow.classList.add(mode === "drag" ? "dragging" : "resizing");
      chartWindow.setPointerCapture(event.pointerId);
      event.preventDefault();
    }

    function moveChartWindowInteraction(event) {
      if (!chartWindowInteraction || event.pointerId !== chartWindowInteraction.pointerId) return;
      const interaction = chartWindowInteraction;
      const horizontalChange = event.clientX - interaction.startX;
      const verticalChange = event.clientY - interaction.startY;
      if (interaction.mode === "drag") {
        applyChartWindowState({
          ...interaction.startState,
          left: interaction.startState.left + horizontalChange,
          top: interaction.startState.top + verticalChange,
        });
      } else {
        applyChartWindowState({
          ...interaction.startState,
          width: interaction.startState.width + horizontalChange,
          height: interaction.startState.height + verticalChange,
        });
      }
    }

    function initializeChartWindow() {
      const chartWindow = el("chartWindow");
      const header = el("chartWindowHandle");
      const resizeHandle = el("chartWindowResize");
      applyChartWindowState(readChartWindowState());
      header.addEventListener("pointerdown", event => {
        if (event.target.closest("button")) return;
        beginChartWindowInteraction(event, "drag");
      });
      resizeHandle.addEventListener("pointerdown", event => {
        event.stopPropagation();
        beginChartWindowInteraction(event, "resize");
      });
      chartWindow.addEventListener("pointermove", moveChartWindowInteraction);
      chartWindow.addEventListener("pointerup", finishChartWindowInteraction);
      chartWindow.addEventListener("pointercancel", finishChartWindowInteraction);
      new ResizeObserver(drawCandles).observe(chartWindow);
    }

    function handleChartViewportResize() {
      if (chartWindowState) applyChartWindowState(chartWindowState);
      else drawCandles();
    }

    function createBot() {
      return {
        version:7,
        enabled:false,
        strategyType:"trend",
        strategyInterval:60,
        leverage:1,
        marginPercent:20,
        stopLossPercent:2,
        trailingStopPercent:1.5,
        partialTakeProfitPercent:0,
        partialClosePercent:50,
        profitFadePercent:1,
        profitFadeClosePercent:100,
        stopOnCandleClose:true,
      };
    }

    function ensureBot() {
      const legacy = portfolio.bot && typeof portfolio.bot === "object" ? portfolio.bot : {};
      const worker = legacy.worker;
      const normalized = { ...createBot(), ...legacy, version:7 };
      normalized.enabled = Boolean(normalized.enabled);
      if (!["trend", "momentum", "mean_reversion", "trend_impulse"].includes(normalized.strategyType)) normalized.strategyType = "trend";
      normalized.strategyInterval = [15, 60].includes(Number(normalized.strategyInterval)) ? Number(normalized.strategyInterval) : 60;
      normalized.leverage = clamp(Number(normalized.leverage) || 1, 1, 50);
      normalized.marginPercent = clamp(Number(normalized.marginPercent) || 20, 1, 100);
      normalized.stopLossPercent = clamp(Number(normalized.stopLossPercent) || 2, 0.25, 20);
      normalized.trailingStopPercent = clamp(Number(normalized.trailingStopPercent) || 1.5, 0.25, 20);
      normalized.partialTakeProfitPercent = clamp(Number(normalized.partialTakeProfitPercent) || 0, 0, 20);
      normalized.partialClosePercent = clamp(Number(normalized.partialClosePercent) || 50, 10, 90);
      normalized.profitFadePercent = clamp(Number(normalized.profitFadePercent) || 0, 0, 10);
      normalized.profitFadeClosePercent = clamp(Number(normalized.profitFadeClosePercent) || 100, 10, 100);
      normalized.stopOnCandleClose = Boolean(normalized.stopOnCandleClose);
      if (worker) normalized.worker = worker;
      portfolio = { bot:normalized };
    }

    function render() {
      const worker = portfolio.bot?.worker;
      renderBinanceAccount(latestBinanceAccount, worker);
      renderBot();
    }

    function renderBot() {
      ensureBot();
      const bot = portfolio.bot;
      el("strategyEnabled").checked = bot.enabled;
      el("strategyType").value = bot.strategyType;
      el("strategyInterval").value = String(bot.strategyInterval);
      renderStrategySignals();
      el("leverageRange").value = bot.leverage;
      el("leverageValue").textContent = `${bot.leverage}×`;
      el("marginRange").value = bot.marginPercent;
      el("marginValue").textContent = `${bot.marginPercent}%`;
      el("stopLossRange").value = bot.stopLossPercent;
      el("stopLossValue").textContent = `${bot.stopLossPercent.toFixed(2).replace(".", ",")}%`;
      el("trailingRange").value = bot.trailingStopPercent;
      el("trailingValue").textContent = `${bot.trailingStopPercent.toFixed(2).replace(".", ",")}%`;
      el("partialTakeProfitRange").value = bot.partialTakeProfitPercent;
      el("partialTakeProfitValue").textContent = bot.partialTakeProfitPercent
        ? `+${bot.partialTakeProfitPercent.toFixed(2).replace(".", ",")}%`
        : "Kikapcsolva";
      el("partialCloseRange").value = bot.partialClosePercent;
      el("partialCloseValue").textContent = `${bot.partialClosePercent}%`;
      el("partialCloseRange").disabled = !bot.partialTakeProfitPercent;
      el("profitFadeRange").value = bot.profitFadePercent;
      el("profitFadeValue").textContent = bot.profitFadePercent ? `${bot.profitFadePercent.toFixed(2).replace(".", ",")}%` : "Kikapcsolva";
      el("profitFadeCloseRange").value = bot.profitFadeClosePercent;
      el("profitFadeCloseValue").textContent = `${bot.profitFadeClosePercent}%`;
      const profitFadeEnabled = Boolean(bot.partialTakeProfitPercent && bot.profitFadePercent);
      el("profitFadeRange").disabled = !bot.partialTakeProfitPercent;
      el("profitFadeCloseRange").disabled = !profitFadeEnabled;
      el("confirmStopClose").checked = bot.stopOnCandleClose;
      const account = latestBinanceAccount;
      const balanceAsset = String(account?.asset || "USDC").toUpperCase();
      const positions = Array.isArray(account?.positions) ? account.positions : [];
      const position = positions.find(item => item?.symbol === "BTCUSDC") || positions[0] || null;
      const marginBalance = Number(account?.margin_balance);
      el("botValue").textContent = Number.isFinite(marginBalance) ? assetMoney(marginBalance, balanceAsset) : "—";
      el("botValueLabel").textContent = `Binance margin (${balanceAsset})`;
      const totalUnrealized = Number(account?.unrealized_pnl);
      el("botPnlValue").textContent = Number.isFinite(totalUnrealized)
        ? `${totalUnrealized >= 0 ? "+" : ""}${assetMoney(totalUnrealized, balanceAsset)}`
        : "—";
      el("botPnlLabel").textContent = `${balanceAsset} nem realizált P/L`;
      el("botPnlValue").className = `value ${totalUnrealized > 0 ? "positive" : totalUnrealized < 0 ? "negative" : ""}`;
      const markPrice = Number(position?.mark_price) || price || latestStrategy?.price || null;
      if (position) {
        const positionPnl = Number(position.unrealized_pnl) || 0;
        const positionMarginValue = Number(position.initial_margin) || 0;
        const positionPnlPercent = positionMarginValue ? positionPnl / positionMarginValue * 100 : 0;
        const positionPnlAsset = String(position.pnl_asset || balanceAsset).toUpperCase();
        el("positionPnlValue").textContent = `${positionPnl >= 0 ? "+" : ""}${assetMoney(positionPnl, positionPnlAsset)} · ${positionPnlPercent >= 0 ? "+" : ""}${positionPnlPercent.toFixed(2).replace(".", ",")}%`;
        el("positionPnlValue").className = `value ${positionPnl > 0 ? "positive" : positionPnl < 0 ? "negative" : ""}`;
      } else {
        el("positionPnlValue").textContent = "Nincs nyitott pozíció";
        el("positionPnlValue").className = "value";
      }
      el("entryPriceValue").textContent = position?.entry_price ? money(position.entry_price) : "—";
      el("currentPriceValue").textContent = markPrice ? money(markPrice) : "—";
      const liquidation = Number(position?.liquidation_price) || 0;
      el("liquidationPriceValue").textContent = liquidation ? money(liquidation) : "—";
      el("liquidationPriceValue").className = liquidation ? "negative" : "";
      if (position) {
        const isLong = position.side === "long";
        el("positionValue").textContent = `${isLong ? "Long" : "Short"} ${num(position.quantity)} BTC · ${position.leverage}×`;
        el("positionValue").className = `value ${isLong ? "positive" : "negative"}`;
      } else {
        el("positionValue").textContent = "Nincs pozíció";
        el("positionValue").className = "value";
      }
      el("stopPriceValue").textContent = "Végrehajtás zárolva";
      el("stopPriceValue").className = "value";
      const worker = bot.worker;
      const workerStatus = el("workerStatus");
      if (worker && typeof worker === "object" && worker.heartbeat_at) {
        const signal = worker.strategy?.signal;
        const signalLabel = signal === "buy" ? "LONG jel" : signal === "sell" ? "SHORT jel" : "TARTÁS";
        const heartbeat = new Date(worker.heartbeat_at);
        const heartbeatTime = heartbeat.valueOf();
        const validHeartbeat = !Number.isNaN(heartbeatTime);
        const heartbeatLabel = !validHeartbeat
          ? "időpont ismeretlen"
          : heartbeat.toLocaleTimeString("hu-HU", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
        const pollSeconds = Math.max(1, Number(worker.poll_seconds) || 5);
        const heartbeatTimeout = Math.max(MIN_WORKER_HEARTBEAT_TIMEOUT_MS, pollSeconds * 3000);
        const heartbeatExpired = !validHeartbeat || Date.now() - heartbeatTime > heartbeatTimeout;
        if (heartbeatExpired) {
          workerStatus.textContent = `Külön robot nem elérhető · utolsó szívverés: ${heartbeatLabel}`;
          workerStatus.className = "worker-status degraded";
        } else if (worker.status === "monitoring") {
          workerStatus.textContent = `Külön robot aktív · utolsó szívverés: ${heartbeatLabel} · ${signalLabel}`;
          workerStatus.className = "worker-status monitoring";
        } else if (worker.status === "paused") {
          workerStatus.textContent = `Külön robot szünetel · automatikus mód kikapcsolva · utolsó szívverés: ${heartbeatLabel}`;
          workerStatus.className = "worker-status paused";
        } else {
          workerStatus.textContent = `Külön robot figyelmeztetés · ${worker.message || "piaci adat hiba"}`;
          workerStatus.className = "worker-status degraded";
        }
      } else {
        workerStatus.textContent = "Külön robot: még nem kapcsolódott.";
        workerStatus.className = "worker-status";
      }
    }

    function updateStrategyDisplay(strategy) {
      el("indicatorLabel").textContent = strategy.indicatorLabel || "Indikátor";
      el("trendLabel").textContent = strategy.contextLabel || "Piaci kontextus";
      if (strategy.strategyType === "trend") {
        el("emaValue").textContent = `${money(strategy.fastEma)} / ${money(strategy.slowEma)}`;
        el("trendValue").textContent = strategy.context === "up" ? "Emelkedő" : "Csökkenő";
        el("trendValue").className = `value ${strategy.context === "up" ? "positive" : "negative"}`;
      } else if (strategy.strategyType === "momentum" || strategy.strategyType === "trend_impulse") {
        const momentum = Number(strategy.momentumPercent);
        el("emaValue").textContent = `${momentum >= 0 ? "+" : ""}${momentum.toFixed(2).replace(".", ",")}% · ${money(strategy.fastEma)}`;
        if (strategy.strategyType === "trend_impulse") {
          const trendText = strategy.context === "up" ? "Emelkedő" : strategy.context === "down" ? "Csökkenő" : "Semleges";
          el("trendValue").textContent = trendText;
          el("trendValue").className = `value ${strategy.context === "up" ? "positive" : strategy.context === "down" ? "negative" : ""}`;
        } else {
          el("trendValue").textContent = strategy.context === "up" ? "Ár EMA felett" : "Ár EMA alatt";
          el("trendValue").className = `value ${strategy.context === "up" ? "positive" : "negative"}`;
        }
      } else {
        el("emaValue").textContent = `${money(strategy.middleBand)} · ${money(strategy.lowerBand)}–${money(strategy.upperBand)}`;
        const contextText = strategy.context === "lower" ? "Alsó sáv alatt" : strategy.context === "upper" ? "Felső sáv felett" : "Sávon belül";
        el("trendValue").textContent = contextText;
        el("trendValue").className = `value ${strategy.context === "lower" ? "positive" : strategy.context === "upper" ? "negative" : ""}`;
      }
      el("strategyReason").textContent = strategy.reason;
    }

    function renderStrategySignals() {
      ensureBot();
      const container = el("allStrategySignals");
      const signalNames = { buy:"Vétel", sell:"Eladás", hold:"Tartás" };
      container.replaceChildren(...STRATEGY_TYPES.map(strategyType => {
        const data = strategySignals[strategyType.id];
        const signal = signalNames[data?.signal] || "—";
        const item = document.createElement("span");
        const activeClass = strategyType.id === portfolio.bot.strategyType ? ` active ${data?.signal || "hold"}` : "";
        item.className = `strategy-signal${activeClass}`;
        item.textContent = `${strategyType.label}: ${signal}`;
        item.title = `${strategyType.label}: ${signal}`;
        return item;
      }));
    }

    function setBinanceValues(values) {
      el("binanceWallet").textContent = values.wallet;
      el("binanceAvailable").textContent = values.available;
      el("binanceUnrealized").textContent = values.unrealized;
      el("binanceMargin").textContent = values.margin;
      el("binanceUnrealized").className = `value ${Number(values.unrealizedValue) > 0 ? "positive" : Number(values.unrealizedValue) < 0 ? "negative" : ""}`;
    }

    function renderBinanceAccount(account, worker = null) {
      const positions = el("binancePositions");
      if (!account?.connected) {
        setBinanceValues({ wallet:"—", available:"—", unrealized:"—", unrealizedValue:0, margin:"—" });
        positions.innerHTML = '<tr><td colspan="6" class="empty">A hitelesített Binance-fiókadatokra vár…</td></tr>';
        el("binanceAccountStatus").textContent = worker?.message || "Indítsd el a külön Python robotot a live_read_only konfigurációval.";
        return;
      }
      const balanceAsset = String(account.asset || "USDC").toUpperCase();
      el("binanceTitle").textContent = balanceAsset === "BNFCR"
        ? "Binance USDⓈ-M · Futures Credits (BNFCR)"
        : `Binance USDⓈ-M · valós ${balanceAsset} számla`;
      setBinanceValues({
        wallet:assetMoney(account.wallet_balance, balanceAsset), available:assetMoney(account.available_balance, balanceAsset),
        unrealized:assetMoney(account.unrealized_pnl, balanceAsset), unrealizedValue:account.unrealized_pnl,
        margin:assetMoney(account.margin_balance, balanceAsset),
      });
      const openPositions = Array.isArray(account.positions) ? account.positions : [];
      positions.innerHTML = openPositions.length ? openPositions.map(position => {
        const direction = position.side === "long" ? "Long" : "Short";
        const pnl = Number(position.unrealized_pnl);
        return `<tr><td data-label="Szimbólum">${safeHtml(position.symbol)}</td><td data-label="Irány" class="${direction === "Long" ? "positive" : "negative"}">${direction}</td><td data-label="Mennyiség">${num(Math.abs(position.quantity))}</td><td data-label="Belépő">${usdc(position.entry_price)}</td><td data-label="Mark ár">${usdc(position.mark_price)}</td><td data-label="Nem realizált P/L" class="${pnl > 0 ? "positive" : pnl < 0 ? "negative" : ""}">${assetMoney(pnl, position.pnl_asset || balanceAsset)}</td></tr>`;
      }).join("") : '<tr><td colspan="6" class="empty">Nincs nyitott USDⓈ-M pozíció.</td></tr>';
      const fetchedAt = new Date(account.fetched_at);
      const fetchedLabel = Number.isNaN(fetchedAt.valueOf())
        ? "ismeretlen"
        : fetchedAt.toLocaleTimeString("hu-HU", { hour:"2-digit", minute:"2-digit", second:"2-digit" });
      const heartbeat = worker?.heartbeat_at ? new Date(worker.heartbeat_at) : null;
      const heartbeatAge = heartbeat && !Number.isNaN(heartbeat.valueOf()) ? Date.now() - heartbeat.valueOf() : Infinity;
      const timeout = Math.max(MIN_WORKER_HEARTBEAT_TIMEOUT_MS, Math.max(1, Number(worker?.poll_seconds) || 5) * 3000);
      el("binanceAccountStatus").textContent = heartbeatAge > timeout
        ? `FIGYELEM: az adat elavult · utolsó Binance-frissítés: ${fetchedLabel} · a Python robot nem ad friss szívverést.`
        : `Binance ${balanceAsset} az irányadó · frissítve: ${fetchedLabel} · mód: csak olvasás · pozíciómód: ${account.position_mode === "hedge" ? "hedge" : "one-way"}.`;
    }

    function activateBrowserMarketData() {
      browserMarketData = true;
      document.body.classList.add("browser-market-data");
      if (!latestBinanceAccount) {
        el("binanceAccountStatus").textContent = "A piaci ár közvetlenül frissül; a Binance-számla csak a külön Python robotból érkezhet.";
      }
    }

    function shouldUseBrowserMarketData(error) {
      return browserMarketData || window.location.protocol === "file:" || error?.status === 404;
    }

    async function requestJson(url) {
      const response = await fetch(url, { cache:"no-store" });
      const data = await response.json().catch(() => null);
      if (!response.ok || !data || typeof data !== "object") {
        const error = new Error(data?.error || data?.message || `HTTP ${response.status}`);
        error.status = response.status;
        throw error;
      }
      return data;
    }

    async function getBrowserTicker() {
      const data = await requestJson(`${BINANCE_PUBLIC_API}/ticker/24hr?symbol=BTCUSDC`);
      const currentPrice = Number(data.lastPrice);
      const change24h = Number(data.priceChangePercent);
      if (!Number.isFinite(currentPrice) || !Number.isFinite(change24h)) throw new Error("Érvénytelen piaci ár érkezett.");
      return { price:currentPrice, change24h, source:"Binance · közvetlen böngészőkapcsolat", stale:false };
    }

    async function getBrowserCandles(interval) {
      const binanceInterval = BROWSER_CANDLE_INTERVALS[interval];
      if (!binanceInterval) throw new Error("Ismeretlen gyertya-idősík.");
      const rows = await requestJson(`${BINANCE_PUBLIC_API}/klines?symbol=BTCUSDC&limit=96&interval=${binanceInterval}`);
      const browserCandles = rows.map(row => ({
        time:Number(row[0]), open:Number(row[1]), high:Number(row[2]), low:Number(row[3]), close:Number(row[4]),
      }));
      if (!browserCandles.length || browserCandles.some(candle => !Number.isFinite(candle.close))) throw new Error("Érvénytelen gyertyaadat érkezett.");
      return { candles:browserCandles, source:"Binance · közvetlen böngészőkapcsolat", stale:false };
    }

    function average(values) {
      return values.reduce((sum, value) => sum + value, 0) / values.length;
    }

    function standardDeviation(values) {
      const mean = average(values);
      return Math.sqrt(average(values.map(value => (value - mean) ** 2)));
    }

    async function getBrowserStrategy(strategyType, interval, candleProvider) {
      const marketData = await candleProvider(interval);
      const closedCandles = marketData.candles.slice(0, -1);
      if (closedCandles.length < 51) throw new Error("Nincs elegendő lezárt gyertya a stratégiajelzéshez.");
      const closes = closedCandles.map(candle => candle.close);
      const currentPrice = closes.at(-1);
      const candleTime = closedCandles.at(-1).time;
      const timeframeLabel = interval === 15 ? "15 perces" : "1 órás";
      const base = {
        strategyType, interval, price:currentPrice, candleTime, stale:false,
        signalKey:`${strategyType}:${interval}:${candleTime}`,
      };

      if (strategyType === "trend") {
        const dailyData = await candleProvider(1440);
        const dailyCloses = dailyData.candles.slice(0, -1).map(candle => candle.close);
        const fast = calculateEma(closes, 20);
        const slow = calculateEma(closes, 50);
        const dailyEma = calculateEma(dailyCloses, 50);
        const dailyUptrend = dailyCloses.at(-1) > dailyEma.at(-1);
        const bullishCross = fast.at(-2) <= slow.at(-2) && fast.at(-1) > slow.at(-1);
        const bearishCross = fast.at(-2) >= slow.at(-2) && fast.at(-1) < slow.at(-1);
        const signal = bullishCross && dailyUptrend ? "buy" : bearishCross || !dailyUptrend ? "sell" : "hold";
        const reason = signal === "buy"
          ? `A ${timeframeLabel} EMA(20) felfelé keresztezte az EMA(50)-et, a napos trend emelkedő.`
          : signal === "sell" ? `A ${timeframeLabel} trend lefelé fordult vagy a napos trendszűrő negatív.` : "Nincs új EMA-kereszteződési jel.";
        return { ...base, signal, signalKey:`${base.signalKey}:${signal}`, strategyLabel:"Trendkövető EMA", indicatorLabel:"EMA(20) / EMA(50)", fastEma:fast.at(-1), slowEma:slow.at(-1), contextLabel:"Napos trend", context:dailyUptrend ? "up" : "down", dailyEma:dailyEma.at(-1), reason };
      }

      if (strategyType === "momentum" || strategyType === "trend_impulse") {
        const momentumPercent = (currentPrice / closes.at(-11) - 1) * 100;
        const entryEma = calculateEma(closes, 20).at(-1);
        const positiveImpulse = momentumPercent >= 0.5 && currentPrice > entryEma;
        const negativeImpulse = momentumPercent <= -0.5 && currentPrice < entryEma;
        if (strategyType === "momentum") {
          const signal = positiveImpulse ? "buy" : negativeImpulse ? "sell" : "hold";
          const reason = signal === "buy"
            ? `A ${timeframeLabel} 10 gyertyás momentum +${momentumPercent.toFixed(2)}%, az ár EMA(20) felett van.`
            : signal === "sell" ? `A ${timeframeLabel} 10 gyertyás momentum ${momentumPercent.toFixed(2)}%, az ár EMA(20) alatt van.` : `A ${timeframeLabel} momentum még nem érte el a ±0,50%-os küszöböt.`;
          return { ...base, signal, signalKey:`${base.signalKey}:${signal}`, strategyLabel:"Momentum", indicatorLabel:"10 gyertyás momentum / EMA(20)", momentumPercent, fastEma:entryEma, contextLabel:"EMA-szűrő", context:currentPrice > entryEma ? "up" : "down", reason };
        }

        const trendInterval = interval === 15 ? 60 : 1440;
        const trendCloses = (await candleProvider(trendInterval)).candles.slice(0, -1).map(candle => candle.close);
        const trendFastEma = calculateEma(trendCloses, 20).at(-1);
        const trendSlowEma = calculateEma(trendCloses, 50).at(-1);
        const trendDirection = trendFastEma > trendSlowEma ? "up" : trendFastEma < trendSlowEma ? "down" : "neutral";
        const signal = trendDirection === "up" && positiveImpulse ? "buy" : trendDirection === "down" && negativeImpulse ? "sell" : "hold";
        const trendLabel = trendInterval === 60 ? "1 órás" : "Napos";
        const reason = signal === "buy"
          ? `A ${trendLabel.toLowerCase()} EMA-trend emelkedő, a ${timeframeLabel} momentum megerősített long jel.`
          : signal === "sell" ? `A ${trendLabel.toLowerCase()} EMA-trend csökkenő, a ${timeframeLabel} momentum megerősített short jel.` : `A ${trendLabel.toLowerCase()} trend és a ${timeframeLabel} momentum még nem ad közös belépőt.`;
        return { ...base, signal, signalKey:`${base.signalKey}:${signal}`, strategyLabel:"Trend + Momentum", trendInterval, indicatorLabel:"10 gyertyás momentum / EMA(20)", momentumPercent, fastEma:entryEma, contextLabel:`${trendLabel} EMA-trend`, context:trendDirection, trendDirection, trendFastEma, trendSlowEma, reason };
      }

      const window = closes.slice(-20);
      const middleBand = average(window);
      const deviation = standardDeviation(window);
      const lowerBand = middleBand - 2 * deviation;
      const upperBand = middleBand + 2 * deviation;
      const signal = currentPrice <= lowerBand ? "buy" : currentPrice >= upperBand ? "sell" : "hold";
      const context = signal === "buy" ? "lower" : signal === "sell" ? "upper" : "inside";
      const reason = signal === "buy"
        ? `A ${timeframeLabel} záróár az alsó Bollinger-sáv alatt van; long jel.`
        : signal === "sell" ? `A ${timeframeLabel} záróár a felső Bollinger-sáv felett van; short jel.` : `Az ár a ${timeframeLabel} Bollinger-sávon belül van.`;
      return { ...base, signal, signalKey:`${base.signalKey}:${signal}`, strategyLabel:"Mean reversion", indicatorLabel:"Bollinger-sáv (20, 2σ)", middleBand, lowerBand, upperBand, contextLabel:"Árhelyzet", context, reason };
    }

    async function getBrowserStrategySignals(interval) {
      const candleCache = new Map();
      const candleProvider = requestedInterval => {
        if (!candleCache.has(requestedInterval)) candleCache.set(requestedInterval, getBrowserCandles(requestedInterval));
        return candleCache.get(requestedInterval);
      };
      return { interval, strategies:await Promise.all(STRATEGY_TYPES.map(({ id }) => getBrowserStrategy(id, interval, candleProvider))) };
    }

    async function loadStrategy() {
      try {
        ensureBot();
        const bot = portfolio.bot;
        const requestedStrategy = bot.strategyType;
        const requestedInterval = Number(bot.strategyInterval);
        let payload;
        if (browserMarketData) payload = await getBrowserStrategySignals(requestedInterval);
        else {
          try { payload = await requestJson(`/api/strategy-signals?interval=${requestedInterval}`); }
          catch (error) {
            if (!shouldUseBrowserMarketData(error)) throw error;
            activateBrowserMarketData();
            payload = await getBrowserStrategySignals(requestedInterval);
          }
        }
        if (portfolio.bot.strategyType !== requestedStrategy || Number(portfolio.bot.strategyInterval) !== requestedInterval) return;
        strategySignals = Object.fromEntries((payload.strategies || []).map(strategy => [strategy.strategyType, strategy]));
        const data = strategySignals[requestedStrategy];
        if (!data) throw new Error("Az aktív stratégia jelzése nem érkezett meg.");
        latestStrategy = data;
        renderStrategySignals();
        updateStrategyDisplay(data);
        renderBot();
        const signalLabel = data.signal === "buy" ? "LONG" : data.signal === "sell" ? "SHORT" : "TARTÁS";
        el("strategyStatus").textContent = data.stale
          ? "A kapcsolat megszakadt; csak a legutóbb ismert jelzés látható."
          : `${bot.enabled ? "Stratégiafigyelés aktív" : "Stratégia kikapcsolva"} · aktuális jel: ${signalLabel} · az éles megbízásküldés zárolva.`;
      } catch (error) {
        el("strategyStatus").textContent = `A stratégiaadatok nem érhetők el: ${error.message}`;
      }
    }

    async function loadPrice() {
      try {
        let data;
        if (browserMarketData) data = await getBrowserTicker();
        else {
          try { data = await requestJson("/api/price"); }
          catch (error) {
            if (!shouldUseBrowserMarketData(error)) throw error;
            activateBrowserMarketData();
            data = await getBrowserTicker();
          }
        }
        price = Number(data.price);
        if (!Number.isFinite(price)) throw new Error("Érvénytelen piaci ár érkezett.");
        el("price").textContent = money(price);
        const change = Number(data.change24h);
        el("change").textContent = `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
        el("change").className = change >= 0 ? "positive" : "negative";
        const staleNote = data.stale ? " · utolsó ismert ár" : "";
        el("status").textContent = `Utolsó frissítés: ${new Date().toLocaleTimeString("hu-HU")} · forrás: ${data.source}${staleNote}`;
        render();
        if (latestStrategy) {
          el("strategyStatus").textContent = `${portfolio.bot.enabled ? "Stratégiafigyelés aktív." : "Stratégia kikapcsolva."} Az éles megbízásküldés zárolva.`;
        }
      } catch (error) { el("status").textContent = `Az élő ár most nem érhető el: ${error.message}`; }
    }

    function scheduleRefresh() {
      clearTimeout(refreshTimer);
      refreshTimer = setTimeout(async () => {
        await loadPrice();
        scheduleRefresh();
      }, 1000);
    }

    function candleTime(timestamp) {
      const options = selectedInterval === 1440
        ? { day:"2-digit", month:"2-digit" }
        : { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" };
      return new Date(timestamp).toLocaleString("hu-HU", options);
    }

    function calculateEma(values, period) {
      if (!values.length) return [];
      const multiplier = 2 / (period + 1);
      const result = [values[0]];
      for (let index = 1; index < values.length; index += 1) {
        result.push((values[index] - result[index - 1]) * multiplier + result[index - 1]);
      }
      return result;
    }

    function drawEmaLine(context, values, xForIndex, priceY, color) {
      if (!values.length) return;
      context.save();
      context.strokeStyle = color;
      context.lineWidth = 1.7;
      context.lineJoin = "round";
      context.lineCap = "round";
      context.beginPath();
      values.forEach((value, index) => {
        const x = xForIndex(index);
        const y = priceY(value);
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      });
      context.stroke();
      context.restore();
    }

    function drawCandles() {
      const canvas = el("candleChart");
      const rectangle = canvas.getBoundingClientRect();
      if (!rectangle.width || !rectangle.height) return;
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.round(rectangle.width * ratio);
      canvas.height = Math.round(rectangle.height * ratio);
      const context = canvas.getContext("2d");
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, rectangle.width, rectangle.height);

      const style = getComputedStyle(document.documentElement);
      const muted = style.getPropertyValue("--muted").trim();
      const line = style.getPropertyValue("--line").trim();
      const green = style.getPropertyValue("--green").trim();
      const red = style.getPropertyValue("--red").trim();
      const ema20Color = "#67b7ff";
      const ema50Color = "#f9c74f";
      const left = 8, top = 16, right = 73, bottom = 31;
      const plotWidth = rectangle.width - left - right;
      const plotHeight = rectangle.height - top - bottom;

      context.font = "12px system-ui";
      if (!candles.length) {
        context.fillStyle = muted;
        context.textAlign = "center";
        context.fillText("Gyertyaadatokra vár…", rectangle.width / 2, rectangle.height / 2);
        return;
      }

      const closes = candles.map(candle => candle.close);
      const ema20 = calculateEma(closes, 20);
      const ema50 = calculateEma(closes, 50);
      const low = Math.min(...candles.map(candle => candle.low), ...ema20, ...ema50);
      const high = Math.max(...candles.map(candle => candle.high), ...ema20, ...ema50);
      const range = Math.max(high - low, high * 0.001);
      const minPrice = low - range * 0.08;
      const maxPrice = high + range * 0.08;
      const priceY = value => top + (maxPrice - value) / (maxPrice - minPrice) * plotHeight;
      const priceText = value => `${new Intl.NumberFormat("hu-HU", { maximumFractionDigits:0 }).format(value)} USDC`;

      context.lineWidth = 1;
      context.textBaseline = "middle";
      context.textAlign = "left";
      for (let row = 0; row < 5; row += 1) {
        const value = maxPrice - (maxPrice - minPrice) * row / 4;
        const y = priceY(value);
        context.strokeStyle = line;
        context.beginPath(); context.moveTo(left, y); context.lineTo(left + plotWidth, y); context.stroke();
        context.fillStyle = muted;
        context.fillText(priceText(value), left + plotWidth + 7, y);
      }

      const step = plotWidth / candles.length;
      const bodyWidth = Math.max(1, Math.min(step * 0.68, 10));
      candles.forEach((candle, index) => {
        const x = left + step * index + step / 2;
        const rising = candle.close >= candle.open;
        const color = rising ? green : red;
        context.strokeStyle = color;
        context.fillStyle = color;
        context.beginPath(); context.moveTo(x, priceY(candle.high)); context.lineTo(x, priceY(candle.low)); context.stroke();
        const openY = priceY(candle.open);
        const closeY = priceY(candle.close);
        const height = Math.max(1, Math.abs(closeY - openY));
        context.fillRect(x - bodyWidth / 2, Math.min(openY, closeY), bodyWidth, height);
      });

      context.save();
      context.beginPath();
      context.rect(left, top, plotWidth, plotHeight);
      context.clip();
      const candleX = index => left + step * index + step / 2;
      drawEmaLine(context, ema20, candleX, priceY, ema20Color);
      drawEmaLine(context, ema50, candleX, priceY, ema50Color);
      context.restore();

      context.textBaseline = "alphabetic";
      context.fillStyle = muted;
      context.font = "11px system-ui";
      const ticks = [0, Math.floor((candles.length - 1) / 2), candles.length - 1];
      ticks.forEach((index, tickIndex) => {
        context.textAlign = tickIndex === 0 ? "left" : tickIndex === ticks.length - 1 ? "right" : "center";
        context.fillText(candleTime(candles[index].time), left + step * index + step / 2, rectangle.height - 8);
      });
    }

    function updateTimeframes() {
      document.querySelectorAll("[data-interval]").forEach(button => {
        button.setAttribute("aria-pressed", String(Number(button.dataset.interval) === selectedInterval));
      });
    }

    async function loadCandles() {
      const requestedInterval = selectedInterval;
      el("chartStatus").textContent = "Gyertyaadatok betöltése…";
      try {
        let data;
        if (browserMarketData) data = await getBrowserCandles(requestedInterval);
        else {
          try { data = await requestJson(`/api/candles?interval=${requestedInterval}`); }
          catch (error) {
            if (!shouldUseBrowserMarketData(error)) throw error;
            activateBrowserMarketData();
            data = await getBrowserCandles(requestedInterval);
          }
        }
        if (requestedInterval !== selectedInterval) return;
        candles = data.candles;
        drawCandles();
        const staleNote = data.stale ? " · kapcsolat nélkül, utolsó ismert adat" : "";
        el("chartStatus").textContent = `96 gyertya · EMA(20) / EMA(50) · forrás: ${data.source} · frissítve: ${new Date().toLocaleTimeString("hu-HU")}${staleNote}`;
      } catch (error) {
        if (requestedInterval === selectedInterval) el("chartStatus").textContent = `A gyertyaadatok nem érhetők el: ${error.message}`;
      }
    }

    el("strategyType").addEventListener("change", event => {
      ensureBot();
      portfolio.bot.strategyType = event.target.value;
      portfolio.bot.lastSignalKey = null;
      persist();
      renderBot();
      el("strategyStatus").textContent = "Stratégia váltva; az új jelzés betöltése…";
      loadStrategy();
    });
    el("strategyInterval").addEventListener("change", event => {
      ensureBot();
      portfolio.bot.strategyInterval = Number(event.target.value);
      portfolio.bot.lastSignalKey = null;
      persist();
      renderBot();
      el("strategyStatus").textContent = "Jelzési idősík váltva; az új jelzés betöltése…";
      loadStrategy();
    });
    el("strategyEnabled").addEventListener("change", event => {
      ensureBot();
      portfolio.bot.enabled = event.target.checked;
      persist();
      renderBot();
      el("strategyStatus").textContent = portfolio.bot.enabled
        ? "A stratégiafigyelés bekapcsolva; a Python robot jelzést számol, de megbízást még nem küldhet."
        : "A stratégiafigyelés kikapcsolva; a Binance-egyenleg tovább frissül.";
    });
    el("leverageRange").addEventListener("input", event => {
      ensureBot();
      portfolio.bot.leverage = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = `Tervezett tőkeáttét: ${portfolio.bot.leverage}×. Ez még nem módosítja a Binance-beállítást és nem küld megbízást.`;
    });
    el("marginRange").addEventListener("input", event => {
      ensureBot();
      portfolio.bot.marginPercent = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = `Az elmentett tervezett USDC-felhasználás: ${portfolio.bot.marginPercent}%. Éles végrehajtás jelenleg nincs.`;
    });
    el("stopLossRange").addEventListener("input", event => {
      ensureBot();
      portfolio.bot.stopLossPercent = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = `Tervezett stop-loss: ${portfolio.bot.stopLossPercent.toFixed(2).replace(".", ",")}%. A robot még nem helyez ki stop megbízást.`;
    });
    el("trailingRange").addEventListener("input", event => {
      ensureBot();
      portfolio.bot.trailingStopPercent = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = `Tervezett trailing stop: ${portfolio.bot.trailingStopPercent.toFixed(2).replace(".", ",")}%. A robot még nem helyez ki stop megbízást.`;
    });
    el("partialTakeProfitRange").addEventListener("input", event => {
      ensureBot();
      const bot = portfolio.bot;
      bot.partialTakeProfitPercent = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = bot.partialTakeProfitPercent
        ? `Tervezett részleges zárás: ${bot.partialTakeProfitPercent.toFixed(2).replace(".", ",")}% nyereségnél. Éles záró megbízás még nincs.`
        : "A tervezett részleges zárás kikapcsolva.";
    });
    el("partialCloseRange").addEventListener("input", event => {
      ensureBot();
      portfolio.bot.partialClosePercent = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = portfolio.bot.partialTakeProfitPercent
        ? `Részleges záráskor a pozíció ${portfolio.bot.partialClosePercent}%-a záródik.`
        : `A részleges zárás aránya ${portfolio.bot.partialClosePercent}%; állíts be hozzá nyereségszintet is.`;
    });
    el("profitFadeRange").addEventListener("input", event => {
      ensureBot();
      portfolio.bot.profitFadePercent = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = portfolio.bot.profitFadePercent
        ? `Tervezett profitvédelem: a csúcstól ${portfolio.bot.profitFadePercent.toFixed(2).replace(".", ",")}% visszaesés. Éles zárás még nincs.`
        : "A tartás jelre működő profitvédelem kikapcsolva.";
    });
    el("profitFadeCloseRange").addEventListener("input", event => {
      ensureBot();
      portfolio.bot.profitFadeClosePercent = Number(event.target.value);
      persist();
      renderBot();
      el("strategyStatus").textContent = `Tartás jel és profit-visszaesés esetén a megmaradt pozíció ${portfolio.bot.profitFadeClosePercent}%-a záródik.`;
    });
    el("confirmStopClose").addEventListener("change", event => {
      ensureBot();
      portfolio.bot.stopOnCandleClose = event.target.checked;
      persist();
      el("strategyStatus").textContent = portfolio.bot.stopOnCandleClose ? "A tervezett stop csak lezárt stratégia-gyertya alapján jelezne zárást." : "A tervezett stop minden élő árfrissítésnél jelezne zárást.";
    });
    document.querySelectorAll("[data-interval]").forEach(button => button.addEventListener("click", () => {
      selectedInterval = Number(button.dataset.interval);
      updateTimeframes();
      loadCandles();
    }));
    window.addEventListener("resize", handleChartViewportResize);
    initializeChartWindow();
    function registerProgressiveWebApp() {
      if (!("serviceWorker" in navigator)) return;
      window.addEventListener("load", () => {
        navigator.serviceWorker.register("./sw.js", { scope:"./" }).catch(() => {
          // A PWA gyorsítótár hiánya nem akadályozhatja a webes robot működését.
        });
      }, { once:true });
    }
    async function startApplication() {
      setMySqlConnectionIndicator("checking");
      const sharedStorageAvailable = await loadSharedPortfolio();
      await refreshWorkerRuntime();
      if (browserMarketData) activateBrowserMarketData();
      updateTimeframes();
      render();
      if (sharedStorageAvailable) setSharedStateNotice("Közös MySQL állapot betöltve.");
      await loadPrice();
      await Promise.all([loadCandles(), loadStrategy()]);
      scheduleRefresh();
      setInterval(refreshSharedPortfolio, SHARED_STATE_REFRESH_MS);
      setInterval(loadCandles, 15000);
      setInterval(loadStrategy, 30000);
      setInterval(refreshWorkerRuntime, 1000);
    }
    registerProgressiveWebApp();
    (async () => {
      if (!window.BtcAuth) return;
      const authenticated = await window.BtcAuth.requireAuthentication();
      if (authenticated) await startApplication();
    })();
