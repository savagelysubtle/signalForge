-- Add ATR to chart_indicators for all existing strategies.
-- ATR is now a default indicator (6th) used by Claude for chart analysis
-- and by GPT for ATR-based stop loss placement.
--
-- chart_indicators is stored as a JSON text array (e.g. '["RSI","MACD",...]').
-- This migration appends "ATR" to strategies that don't already include it.

UPDATE strategies
SET chart_indicators = CASE
    WHEN chart_indicators IS NULL THEN '["RSI","MACD","Volume","EMA_50","EMA_200","ATR"]'
    WHEN chart_indicators NOT LIKE '%"ATR"%' THEN
        REPLACE(chart_indicators, ']', ',"ATR"]')
    ELSE chart_indicators
END
WHERE chart_indicators IS NULL
   OR chart_indicators NOT LIKE '%"ATR"%';
