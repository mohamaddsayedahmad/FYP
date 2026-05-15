-- Migration 002: Add iterations column to accounts
-- Supports per-account PBKDF2 iteration count for future hash upgrades.
-- Default 200000 matches the iteration count used by the original database.py.
ALTER TABLE accounts ADD COLUMN iterations INTEGER NOT NULL DEFAULT 200000;
