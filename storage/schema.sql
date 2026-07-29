-- StockLLM storage schema
-- Every run and every agent call gets logged so we can review reasoning later
-- and eventually backtest / check calibration.

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    final_recommendation TEXT,
    final_confidence INTEGER,
    total_cost_usd REAL,
    status TEXT DEFAULT 'pending'  -- pending | complete | failed
);

CREATE TABLE IF NOT EXISTS research_bundles (
    run_id INTEGER NOT NULL,
    bundle_json TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

CREATE TABLE IF NOT EXISTS agent_outputs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    agent_name TEXT NOT NULL,   -- bull | bear | skeptic | judge
    model_used TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER DEFAULT 0,
    cost_usd REAL,
    raw_output_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);

-- Filled in later by a separate backtest/outcome-check script -- not used in v1 CLI.
CREATE TABLE IF NOT EXISTS outcomes (
    run_id INTEGER NOT NULL,
    price_at_run REAL,
    price_after_7d REAL,
    price_after_30d REAL,
    checked_at TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
