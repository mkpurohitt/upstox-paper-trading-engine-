-- Executed once on first container start (timescaledb-ha image ships both extensions).
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
ALTER DATABASE algo SET timezone TO 'UTC';
