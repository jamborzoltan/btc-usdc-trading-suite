-- A korábbi btc_usdc_robot_state és btc_usdc_robot_runtime payload-táblákat
-- ez a séma nem törli. Az API-k átálláskor csak migrációs forrásként olvassák.

CREATE TABLE IF NOT EXISTS btc_usdc_bot_settings (
  state_key VARCHAR(64) NOT NULL,
  bot_version SMALLINT UNSIGNED NOT NULL DEFAULT 7,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  strategy_type VARCHAR(32) NOT NULL DEFAULT 'trend',
  strategy_interval SMALLINT UNSIGNED NOT NULL DEFAULT 60,
  leverage SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  margin_percent DECIMAL(8,4) NOT NULL DEFAULT 20,
  stop_loss_percent DECIMAL(8,4) NOT NULL DEFAULT 2,
  trailing_stop_percent DECIMAL(8,4) NOT NULL DEFAULT 1.5,
  partial_take_profit_percent DECIMAL(8,4) NOT NULL DEFAULT 0,
  partial_close_percent DECIMAL(8,4) NOT NULL DEFAULT 50,
  profit_fade_percent DECIMAL(8,4) NOT NULL DEFAULT 1,
  profit_fade_close_percent DECIMAL(8,4) NOT NULL DEFAULT 100,
  stop_on_candle_close TINYINT(1) NOT NULL DEFAULT 1,
  revision BIGINT UNSIGNED NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS btc_usdc_robot_status (
  state_key VARCHAR(64) NOT NULL,
  runtime_version SMALLINT UNSIGNED NOT NULL DEFAULT 2,
  mode VARCHAR(32) NOT NULL,
  execution_state VARCHAR(32) NOT NULL,
  status VARCHAR(32) NOT NULL,
  heartbeat_at DATETIME NULL,
  poll_seconds DECIMAL(8,3) NOT NULL,
  price DECIMAL(30,12) NULL,
  change_24h DECIMAL(20,8) NULL,
  message TEXT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key),
  KEY idx_robot_status_heartbeat (heartbeat_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS btc_usdc_strategy_snapshot (
  state_key VARCHAR(64) NOT NULL,
  strategy_type VARCHAR(32) NOT NULL,
  strategy_label VARCHAR(64) NOT NULL,
  candle_interval SMALLINT UNSIGNED NOT NULL,
  price DECIMAL(30,12) NOT NULL,
  candle_time BIGINT UNSIGNED NOT NULL,
  trade_signal VARCHAR(16) NOT NULL,
  reason TEXT NOT NULL,
  market_context VARCHAR(32) NOT NULL,
  fast_ema DECIMAL(30,12) NULL,
  slow_ema DECIMAL(30,12) NULL,
  momentum_percent DECIMAL(20,8) NULL,
  middle_band DECIMAL(30,12) NULL,
  lower_band DECIMAL(30,12) NULL,
  upper_band DECIMAL(30,12) NULL,
  signal_key VARCHAR(255) NOT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS btc_usdc_binance_account (
  state_key VARCHAR(64) NOT NULL,
  connected TINYINT(1) NOT NULL DEFAULT 0,
  source VARCHAR(32) NOT NULL,
  balance_asset VARCHAR(16) NOT NULL,
  quote_asset VARCHAR(16) NOT NULL,
  credit_mode TINYINT(1) NOT NULL DEFAULT 0,
  symbol VARCHAR(32) NOT NULL,
  wallet_balance DECIMAL(30,12) NOT NULL,
  available_balance DECIMAL(30,12) NOT NULL,
  cross_wallet_balance DECIMAL(30,12) NOT NULL,
  unrealized_pnl DECIMAL(30,12) NOT NULL,
  margin_balance DECIMAL(30,12) NOT NULL,
  max_withdraw_amount DECIMAL(30,12) NOT NULL,
  margin_available TINYINT(1) NOT NULL DEFAULT 1,
  can_trade TINYINT(1) NOT NULL DEFAULT 0,
  position_mode VARCHAR(16) NOT NULL,
  multi_assets_margin TINYINT(1) NOT NULL DEFAULT 0,
  fetched_at DATETIME NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS btc_usdc_open_positions (
  state_key VARCHAR(64) NOT NULL,
  symbol VARCHAR(32) NOT NULL,
  position_side VARCHAR(16) NOT NULL,
  side VARCHAR(8) NOT NULL,
  quantity DECIMAL(30,12) NOT NULL,
  signed_quantity DECIMAL(30,12) NOT NULL,
  entry_price DECIMAL(30,12) NOT NULL,
  break_even_price DECIMAL(30,12) NOT NULL,
  mark_price DECIMAL(30,12) NOT NULL,
  liquidation_price DECIMAL(30,12) NOT NULL,
  unrealized_pnl DECIMAL(30,12) NOT NULL,
  notional DECIMAL(30,12) NOT NULL,
  initial_margin DECIMAL(30,12) NOT NULL,
  isolated_margin DECIMAL(30,12) NOT NULL,
  leverage SMALLINT UNSIGNED NOT NULL,
  margin_type VARCHAR(16) NOT NULL,
  margin_asset VARCHAR(16) NOT NULL,
  pnl_asset VARCHAR(16) NOT NULL,
  exchange_update_time BIGINT UNSIGNED NOT NULL DEFAULT 0,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key, symbol, position_side)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS btc_usdc_auth_users (
  state_key VARCHAR(64) NOT NULL,
  username VARCHAR(64) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  password_changed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS btc_usdc_passkeys (
  state_key VARCHAR(64) NOT NULL,
  credential_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  credential_id TEXT CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  user_handle VARCHAR(128) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  public_key TEXT NOT NULL,
  sign_count BIGINT UNSIGNED NOT NULL DEFAULT 0,
  label VARCHAR(64) NOT NULL,
  transports VARCHAR(512) NOT NULL DEFAULT '[]',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (state_key, credential_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS btc_usdc_auth_attempts (
  state_key VARCHAR(64) NOT NULL,
  client_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  failures INT UNSIGNED NOT NULL DEFAULT 0,
  first_attempt_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  locked_until TIMESTAMP NULL DEFAULT NULL,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (state_key, client_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
