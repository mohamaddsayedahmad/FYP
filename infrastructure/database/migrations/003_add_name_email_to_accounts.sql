-- Migration 003: Add name and email columns to accounts
-- Supports richer teacher profiles (Option B).
-- Both columns are nullable so existing rows are unaffected.
ALTER TABLE accounts ADD COLUMN name TEXT;
ALTER TABLE accounts ADD COLUMN email TEXT;
