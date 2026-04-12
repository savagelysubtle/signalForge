-- Migration 027: Add confidence_label to recommendations
-- GPT now outputs a categorical confidence label (ConfidenceLabel enum)
-- instead of a raw float. The label is stored alongside the numeric
-- confidence for auditability and future recalibration.

ALTER TABLE recommendations
    ADD COLUMN IF NOT EXISTS confidence_label TEXT DEFAULT NULL;

COMMENT ON COLUMN recommendations.confidence_label IS
    'Categorical confidence label from GPT (e.g. c8_high). Maps to numeric confidence via CONFIDENCE_LABEL_MAP.';
