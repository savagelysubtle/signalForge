"""Canonical feature registry -- single source of truth for ML features.

Both the training pipeline (``engineering.py``) and the backend inference
mapper (``feature_mapper.py``) import from this module.  Any mismatch
between training and inference feature names becomes a detectable error
rather than a silent NaN collapse.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeatureType(Enum):
    """Data type of a feature."""

    NUMERIC = "numeric"
    CATEGORICAL = "categorical"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """Specification for a single ML feature.

    Args:
        name: Canonical feature name used in training and inference.
        ftype: Whether the feature is numeric or categorical.
        min_val: Lower bound for valid values (None = unbounded).
        max_val: Upper bound for valid values (None = unbounded).
        inference_available: True if the feature can be computed from a
            single live TechnicalSnapshot + FMP data + regime context.
        description: Short human-readable description.
    """

    name: str
    ftype: FeatureType = FeatureType.NUMERIC
    min_val: float | None = None
    max_val: float | None = None
    inference_available: bool = True
    description: str = ""


# ---------------------------------------------------------------------------
# Core TA features (from TechnicalSnapshot)
# ---------------------------------------------------------------------------

_TA_FEATURES: list[FeatureSpec] = [
    FeatureSpec("rsi_14", min_val=0, max_val=100, description="14-period RSI"),
    FeatureSpec(
        "rsi_zone",
        ftype=FeatureType.CATEGORICAL,
        min_val=-1,
        max_val=1,
        description="RSI zone: -1 oversold, 0 neutral, 1 overbought",
    ),
    FeatureSpec("macd_histogram", description="MACD histogram value"),
    FeatureSpec("macd_slope", description="MACD line minus signal line delta"),
    FeatureSpec("adx", min_val=0, max_val=100, description="ADX trend strength"),
    FeatureSpec("atr_pct", min_val=0, description="ATR as % of price"),
    FeatureSpec("volume_ratio", min_val=0, description="Volume / 20-day MA volume"),
    FeatureSpec("volume_trend", min_val=0, description="5-day MA vol / 20-day MA vol"),
    FeatureSpec("momentum_score", min_val=-1, max_val=1, description="Composite momentum"),
    FeatureSpec("price_vs_ema_9", description="(Price - EMA9) / EMA9 as %"),
    FeatureSpec("price_vs_ema_21", description="(Price - EMA21) / EMA21 as %"),
    FeatureSpec("price_vs_ema_50", description="(Price - EMA50) / EMA50 as %"),
    FeatureSpec("price_vs_ema_200", description="(Price - EMA200) / EMA200 as %"),
    FeatureSpec("ema_stack_score", min_val=-1, max_val=1, description="EMA alignment score"),
    FeatureSpec("ema_spread_pct", description="Spread between fastest and slowest EMA"),
    FeatureSpec("high_low_range", min_val=0, description="(High-Low)/Close as %"),
    FeatureSpec("gap_pct", description="Open gap as % of prior close"),
    FeatureSpec("price_change_1d", description="1-day price change %"),
    FeatureSpec("bollinger_width", min_val=0, description="BB width as % of SMA20"),
    FeatureSpec("distance_from_20d_high", max_val=0, description="Close vs 20d high as %"),
    FeatureSpec("distance_from_20d_low", min_val=0, description="Close vs 20d low as %"),
    FeatureSpec("williams_r", min_val=-100, max_val=0, description="Williams %R 14-period"),
    FeatureSpec("bb_position", min_val=0, max_val=1, description="Position within Bollinger Bands"),
    FeatureSpec(
        "bb_width_percentile",
        min_val=0,
        max_val=1,
        description="BB width percentile rank vs 100d",
    ),
    FeatureSpec(
        "squeeze_duration",
        min_val=0,
        description="Consecutive bars with BB width below 20d avg",
    ),
    FeatureSpec(
        "range_compression_20d",
        min_val=0,
        max_val=1,
        description="5d range / 20d range ratio",
    ),
    FeatureSpec("volume_surge", min_val=0, max_val=1, description="1.0 if volume_ratio > 1.5"),
    FeatureSpec(
        "ema_50_200_cross_direction",
        min_val=-1,
        max_val=1,
        description="+1 golden cross, -1 death cross",
    ),
    FeatureSpec(
        "ema_50_200_cross_recency",
        min_val=0,
        max_val=60,
        description="Bars since last EMA 50/200 crossover",
    ),
    FeatureSpec(
        "rsi_divergence",
        min_val=-1,
        max_val=1,
        description="+1 bullish divergence, -1 bearish",
    ),
    FeatureSpec(
        "oversold_duration",
        min_val=0,
        description="Consecutive bars with RSI < 35",
    ),
]

# ---------------------------------------------------------------------------
# FMP fundamental features
# ---------------------------------------------------------------------------

_FUNDAMENTAL_FEATURES: list[FeatureSpec] = [
    FeatureSpec("pe_ratio", description="Price to earnings ratio"),
    FeatureSpec("pb_ratio", description="Price to book ratio"),
    FeatureSpec("ev_ebitda", description="Enterprise value / EBITDA"),
    FeatureSpec("debt_equity", min_val=0, description="Debt to equity ratio"),
    FeatureSpec("roe", description="Return on equity"),
    FeatureSpec("roa", description="Return on assets"),
    FeatureSpec("net_margin", description="Net profit margin"),
    FeatureSpec("revenue_growth", description="Revenue growth rate"),
    FeatureSpec("piotroski_score", min_val=0, max_val=9, description="Piotroski F-score"),
    FeatureSpec("altman_z", description="Altman Z-score"),
    FeatureSpec("analyst_target_upside", description="Analyst target upside %"),
    FeatureSpec("insider_buy_ratio", min_val=0, max_val=1, description="Insider buy ratio"),
    FeatureSpec("current_ratio", min_val=0, description="Current ratio"),
    FeatureSpec("dividend_yield", min_val=0, description="Dividend yield"),
    FeatureSpec("composite_score", description="Composite fundamental score"),
]

# ---------------------------------------------------------------------------
# Context features
# ---------------------------------------------------------------------------

_CONTEXT_FEATURES: list[FeatureSpec] = [
    FeatureSpec(
        "strategy_type", ftype=FeatureType.CATEGORICAL, description="Strategy template type"
    ),
    FeatureSpec("market_regime", ftype=FeatureType.CATEGORICAL, description="Market regime label"),
    FeatureSpec("sector", ftype=FeatureType.CATEGORICAL, description="Stock sector"),
    FeatureSpec("day_of_week", min_val=0, max_val=6, description="Day of week (0=Mon)"),
    FeatureSpec("month", min_val=1, max_val=12, description="Month (1-12)"),
    FeatureSpec("vix_level", min_val=0, description="VIX volatility index"),
    FeatureSpec(
        "market_breadth_proxy",
        min_val=0,
        max_val=1,
        description="% of universe above 200 EMA",
    ),
]

# ---------------------------------------------------------------------------
# Signal features
# ---------------------------------------------------------------------------

_SIGNAL_FEATURES: list[FeatureSpec] = [
    FeatureSpec("primary_signal", min_val=-1, max_val=1, description="Primary signal direction"),
    FeatureSpec("signal_strength", min_val=0, max_val=1, description="Signal strength score"),
]

# ---------------------------------------------------------------------------
# Multi-timeframe features (inference-available from secondary snapshots)
# ---------------------------------------------------------------------------

_MULTI_TF_FEATURES: list[FeatureSpec] = []
for _tf in ("1H", "4H", "D"):
    _MULTI_TF_FEATURES.extend(
        [
            FeatureSpec(f"tf_{_tf}_rsi_14", min_val=0, max_val=100),
            FeatureSpec(f"tf_{_tf}_price_vs_ema_200"),
            FeatureSpec(f"tf_{_tf}_ema_stack_score", min_val=-1, max_val=1),
            FeatureSpec(f"tf_{_tf}_momentum_score", min_val=-1, max_val=1),
        ]
    )

# ---------------------------------------------------------------------------
# LLM features (shadow model only)
# ---------------------------------------------------------------------------

_LLM_FEATURES: list[FeatureSpec] = [
    FeatureSpec("llm_action_encoded", min_val=-1, max_val=1),
    FeatureSpec("llm_confidence", min_val=0, max_val=1),
    FeatureSpec("llm_rr_ratio", min_val=0),
    FeatureSpec("llm_sl_distance_pct", min_val=0),
    FeatureSpec("llm_tp_distance_pct", min_val=0),
    FeatureSpec("llm_key_factor_count", min_val=0),
    FeatureSpec("llm_warning_count", min_val=0),
]

# ---------------------------------------------------------------------------
# Training-only features (NOT available at inference)
# ---------------------------------------------------------------------------

_TRAINING_ONLY_FEATURES: list[FeatureSpec] = [
    FeatureSpec("ffd_close", inference_available=False, description="FFD close price"),
    FeatureSpec("ffd_return_1d", inference_available=False, description="FFD 1-day return"),
    FeatureSpec("hmm_regime", inference_available=False, ftype=FeatureType.CATEGORICAL),
    FeatureSpec("hmm_regime_prob_bear", inference_available=False, min_val=0, max_val=1),
    FeatureSpec("hmm_regime_prob_neutral", inference_available=False, min_val=0, max_val=1),
    FeatureSpec("hmm_regime_prob_bull", inference_available=False, min_val=0, max_val=1),
    FeatureSpec("price_change_5d", inference_available=False),
    FeatureSpec("price_change_20d", inference_available=False),
    FeatureSpec("volatility_20d", inference_available=False, min_val=0),
    FeatureSpec("sector_relative_strength", inference_available=False),
]

# Weekly TF features are training-only (not reliably in live snapshots)
for _tf_w in ("W",):
    _TRAINING_ONLY_FEATURES.extend(
        [
            FeatureSpec(f"tf_{_tf_w}_rsi_14", inference_available=False, min_val=0, max_val=100),
            FeatureSpec(f"tf_{_tf_w}_price_vs_ema_200", inference_available=False),
            FeatureSpec(
                f"tf_{_tf_w}_ema_stack_score", inference_available=False, min_val=-1, max_val=1
            ),
            FeatureSpec(
                f"tf_{_tf_w}_momentum_score", inference_available=False, min_val=-1, max_val=1
            ),
        ]
    )

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

ALL_FEATURES: tuple[FeatureSpec, ...] = tuple(
    _TA_FEATURES
    + _FUNDAMENTAL_FEATURES
    + _CONTEXT_FEATURES
    + _SIGNAL_FEATURES
    + _MULTI_TF_FEATURES
    + _LLM_FEATURES
    + _TRAINING_ONLY_FEATURES
)

FEATURE_REGISTRY: dict[str, FeatureSpec] = {f.name: f for f in ALL_FEATURES}

INFERENCE_FEATURES: frozenset[str] = frozenset(
    f.name for f in ALL_FEATURES if f.inference_available
)

TRAINING_ONLY_NAMES: frozenset[str] = frozenset(
    f.name for f in ALL_FEATURES if not f.inference_available
)

CATEGORICAL_FEATURE_NAMES: frozenset[str] = frozenset(
    f.name for f in ALL_FEATURES if f.ftype == FeatureType.CATEGORICAL
)

BOUNDED_FEATURES: dict[str, tuple[float | None, float | None]] = {
    f.name: (f.min_val, f.max_val)
    for f in ALL_FEATURES
    if f.min_val is not None or f.max_val is not None
}

# TSFresh prefix -- not individually registered because names are dynamic
TRAINING_ONLY_PREFIXES: tuple[str, ...] = ("tsf_",)


def is_training_only(name: str) -> bool:
    """Check if a feature name is training-only (unavailable at inference)."""
    if name in TRAINING_ONLY_NAMES:
        return True
    return any(name.startswith(p) for p in TRAINING_ONLY_PREFIXES)


def validate_feature_coverage(
    feature_names: list[str],
    available_features: dict[str, object],
) -> list[str]:
    """Check which model features are missing from the available feature dict.

    Args:
        feature_names: Feature names the model expects.
        available_features: Features actually provided at inference.

    Returns:
        List of missing feature names (empty = full coverage).
    """
    return [name for name in feature_names if name not in available_features]
