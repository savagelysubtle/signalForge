---
name: Pipeline Confidence Overhaul
overview:
  Overhaul the SignalForge pipeline's confidence math, judge prompt, and debate
  architecture to restore actionable BUY/SHORT signals. The pipeline currently
  has 7 layers that each subtract confidence with no upward mechanism, turning
  most signals into WATCH. This plan fixes the math, moves quantitative rules
  from prompts to deterministic code, replaces the biased debate with balanced
  single-pass synthesis, and adds missing features (EV calculation, WATCH entry
  setups, regime-conditional thresholds, signal half-life, ATR-based sizing).
todos:
  - id: phase1-confidence-math
    content:
      'Phase 1: Fix calibration blend (60/40), add confidence floor, cap ML
      penalty at 20%'
    status: completed
  - id: phase2-deterministic-rules
    content:
      'Phase 2: R:R < 2:1 override to WATCH, EV calculation, move ADX/momentum
      rules to code'
    status: completed
  - id: phase3-single-pass
    content:
      'Phase 3: Skip debate, rewrite judge prompt v16 for balanced synthesis,
      raise temp to 0.55, WATCH-with-setup'
    status: completed
  - id: phase4-regime-features
    content:
      'Phase 4: Regime-conditional thresholds, signal half-life per strategy,
      ATR-based sizing'
    status: completed
  - id: phase5-dedup
    content: 'Phase 5: Deduplicate ADX/RSI/volume penalties across layers'
    status: completed
  - id: quality-check
    content:
      Run ruff format + ruff check + ty check, update frontend types, verify
      schema-sync
    status: completed
isProject: false
---

# Pipeline Confidence Overhaul

## Root Cause Summary

The pipeline has 7 independent confidence-reduction layers and zero upward
mechanisms. A GPT-assigned 72% BUY gets ground to 35% WATCH through: calibration
blend (40% GPT / 60% TA), ML confidence blend (0.65x multiplier when uncertain),
risk penalties, reflection suppressions, and conservative prompt rules. The 2:1
R:R target is not enforced in code, WATCH signals are instructed to have null
entry setups, and the debate gives the bear an unfair advantage.

---

## Phase 1: Confidence Math (Quick Wins)

**Goal:** Fix the three biggest confidence-killers. This alone should recover
~50% of lost signals.

### 1a. Flip Calibration Blend to 60/40 GPT-Favoring

**File:**
[src/backend/services/confidence_calibration.py](src/backend/services/confidence_calibration.py)

- **Line 338:** Change `blended = 0.4 * rec.confidence + 0.6 * calibrated` to
  `blended = 0.6 * rec.confidence + 0.4 * calibrated`
- Update docstring (line 7-9) and comment (line 337) to reflect 60/40
- **Why:** The TA score realistically maxes at ~0.55-0.65. At 60% weight, it
  drags everything down. At 40% weight, it still grounds GPT in reality but
  doesn't dominate.

### 1b. Add Confidence Floor When Tracks Agree

**File:**
[src/backend/services/confidence_calibration.py](src/backend/services/confidence_calibration.py)

- After the blend calculation (line 339), add a confidence floor:
  - If `agreement_score >= 0.8` (3/3 tracks agree) AND blended < 0.55: floor at
    0.55
  - If `agreement_score >= 0.5` (2/3 agree) AND blended < 0.45: floor at 0.45
- Log when floor is applied so we can track frequency

### 1c. Cap ML Blend Penalty at 20% Max Reduction

**File:**
[src/backend/services/ml_confidence_blend.py](src/backend/services/ml_confidence_blend.py)

- **Line 49:** Change `mult = base_mult * amb_mult` to
  `mult = max(0.80, base_mult * amb_mult)`
- This means the ML blend can never reduce confidence by more than 20%
- For blocked recs (line 42), change cap to `max(0.20, p * 0.65 + 0.08)` (raise
  floor from 0.12 to 0.20)

---

## Phase 2: Deterministic Enforcement (Code Rules)

**Goal:** Move quantitative decision rules from the prompt (where GPT interprets
them inconsistently) into deterministic Python code.

### 2a. R:R < 2:1 Overrides to WATCH

**File:**
[src/backend/pipeline/stages/risk_validator.py](src/backend/pipeline/stages/risk_validator.py)

- After existing R:R violation check (line 127-130), add:
  - If `rec.action in ("BUY", "SHORT")` and `rec.risk_reward_ratio is not None`
    and `rec.risk_reward_ratio < rp.min_risk_reward` (default 2.0): override
    `rec.action = "WATCH"`, add warning
  - If `rec.action in ("BUY", "SHORT")` and entry/stop/TP are null: override
    `rec.action = "WATCH"`, add warning
- This enforces the 2:1 R:R rule the user specified as the app's core goal

### 2b. Add Expected Value Calculation

**File:** [src/backend/pipeline/schemas.py](src/backend/pipeline/schemas.py) +
[src/backend/pipeline/orchestrator.py](src/backend/pipeline/orchestrator.py)

- Add `expected_value: float | None = None` field to `Recommendation` model
- In orchestrator, after calibration completes, compute:
  `EV = confidence * R:R - (1 - confidence)` for BUY/SHORT recs
- Stamp `rec.expected_value = EV`
- If EV > 0.3, add to key_factors: "Positive expected value: {EV:.2f}"
- If EV < 0, add warning: "Negative expected value: {EV:.2f}"

### 2c. Move ADX/Momentum Rules to Code

**File:**
[src/backend/pipeline/stages/risk_validator.py](src/backend/pipeline/stages/risk_validator.py)

- Add two new deterministic checks:
  - If ADX < 20 AND strategy_type in trend-following set AND action is
    BUY/SHORT: override to WATCH with warning "No trend detected (ADX {adx})"
  - If momentum_score between -0.2 and 0.2 AND action is BUY/SHORT: add warning
    (not override) "Momentum near zero ({momentum:.2f})"
- These rules are currently in the GPT prompt (lines 236-237) and will be
  removed from there in Phase 3

---

## Phase 3: Single-Pass Synthesis (Architecture)

**Goal:** Replace the 3-call debate (bull + bear + judge) with a single balanced
synthesis call. This eliminates information destruction, saves 2 API calls, and
removes the bear's unfair advantage.

### 3a. Skip Debate Phase

**File:**
[src/backend/pipeline/stages/gpt.py](src/backend/pipeline/stages/gpt.py)

- In `run_debate()` (line 225): change
  `run_debate_track = config.enable_debate or force_ml_debate` to
  `run_debate_track = False`
- Keep `_run_debate_phase()` code intact but unreachable (can re-enable later if
  needed)
- The judge already handles the no-debate case gracefully (lines 1087-1091 of
  gpt_debate.py)
- Raise judge temperature from 0.4 to 0.55 (line 125)

### 3b. Rewrite Judge System Prompt (v15 to v16)

**File:**
[src/backend/pipeline/prompts/gpt_debate.py](src/backend/pipeline/prompts/gpt_debate.py)

- Bump `JUDGE_PROMPT_VERSION` from "v15" to "v16"
- Rewrite `JUDGE_SYSTEM_PROMPT` with these key changes:

**Remove these WATCH-biasing rules:**

- ~~"If confidence is below 0.5, recommend NO_TRADE or WATCH"~~ (now in code)
- ~~"2/3 agree but numerical TA contradicts -> WATCH"~~ (now in code)
- ~~"ADX < 20 and strategy requires trending market -> NO_TRADE"~~ (now in code)
- ~~"Momentum score near zero -> WATCH"~~ (now in code)
- ~~"0.40-0.55: Low conviction -- HOLD or WATCH unless exceptional catalyst"~~
  (too restrictive)

**Change decision framework:**

- BUY: "Bull case outweighs bear case with R:R >= 2.0" (remove "significantly")
- WATCH: Redefine as "Setup is developing but needs a specific trigger. You MUST
  provide: entry_trigger (the price or event that activates this trade),
  invalidation_conditions (what kills the setup), and what specific catalyst to
  monitor."
- Remove the word "significantly" from BUY requirement

**Reframe as balanced synthesis (not debate judge):**

- Change opening from "You are a senior trading analyst receiving..." to "You
  are a senior trading analyst synthesizing three independent research
  reports..."
- Remove "Disagreement between analysts should LOWER your confidence" (this is
  now handled by calibration code)
- Replace with "Assess all evidence on its merits. Track disagreements should
  inform your analysis, not automatically reduce confidence."

**Revise confidence calibration bands:**

- 0.75+: Strong alignment across tracks and numerical data (was 0.85+)
- 0.60-0.75: Good conviction with minor caveats (was 0.70-0.85)
- 0.45-0.60: Moderate conviction, most tracks agree (was 0.55-0.70)
- 0.30-0.45: Low conviction (was 0.40-0.55)
- Under 0.30: Very weak signal (was under 0.40)

**Add WATCH-with-setup requirement:**

- When action is WATCH, require non-null `entry_trigger` (the price/event
  trigger)
- Require at least one `invalidation_conditions` entry
- Set `entry_price` to the trigger level (not null)
- Add `entry_valid_window` for how long to monitor

### 3c. Update Judge User Prompt Builder

**File:**
[src/backend/pipeline/prompts/gpt_debate.py](src/backend/pipeline/prompts/gpt_debate.py)

- In `build_judge_prompt()` (line 1087-1091): Replace "No debate was conducted.
  Perform your own internal bull analysis from the track data above." with
  "Analyze all evidence with balanced perspective. In your bull_case, present
  the strongest bullish arguments. In your bear_case, present the strongest
  risks and concerns."
- Same for bear case section (line 1109-1112)
- Remove the line (979-981) "Disagreement between them should LOWER your
  confidence, not be glossed over."

---

## Phase 4: Regime-Conditional Thresholds + Missing Features

### 4a. Regime-Conditional Signal Strength

**File:**
[src/backend/services/confidence_calibration.py](src/backend/services/confidence_calibration.py)

- Modify `_classify_signal_strength()` to accept `regime_context` parameter
- In bullish regimes: lower STRONG threshold from 0.70 to 0.65, MODERATE from
  0.50 to 0.45
- In bearish regimes: raise STRONG threshold to 0.75, MODERATE to 0.55
- In ranging/neutral: keep current thresholds

### 4b. Signal Half-Life Per Strategy

**Files:** [src/backend/pipeline/schemas.py](src/backend/pipeline/schemas.py) +
[templates/strategies.json](templates/strategies.json)

- Add `signal_half_life_hours: int = 48` to `StrategyConfig` (or a computed
  field)
- Add per-strategy values to templates:
  - Intraday/scalp: 2-4 hours
  - Swing: 48 hours (2 trading days)
  - Position/value: 120 hours (5 trading days)
  - Crypto: 24 hours (always-on market)
- Stamp `entry_valid_window` with the half-life value if GPT leaves it empty

### 4c. ATR-Based Position Sizing

**File:**
[src/backend/pipeline/stages/risk_validator.py](src/backend/pipeline/stages/risk_validator.py)

- After existing position sizing logic, add ATR-based sizing:
  - `dollar_risk = portfolio_value * (rp.max_portfolio_risk_pct / 100) / max_concurrent_positions`
  - `shares = dollar_risk / (ATR * atr_multiplier)` where atr_multiplier depends
    on strategy type
  - `position_pct = min(shares * entry_price / portfolio_value * 100, rp.max_position_pct)`
- Uses ATR already extracted from charts (the `_parse_atr_from_charts()`
  function exists at line 68)
- Falls back to current percentage-based sizing when ATR unavailable

---

## Phase 5: Penalty Deduplication

### 5a. Assign Penalty Ownership

Each data point should be penalized by exactly ONE layer:

| Data Point                         | Owner                                             | Remove From                                      |
| ---------------------------------- | ------------------------------------------------- | ------------------------------------------------ |
| ADX < 20                           | `risk_validator.py` (new, deterministic override) | Judge prompt rule, `risk_post_filter.py` penalty |
| RSI overbought/oversold            | `confidence_calibration.py`                       | `risk_post_filter.py` penalty                    |
| Low volume                         | `confidence_calibration.py`                       | `risk_post_filter.py` penalty                    |
| Sentiment score                    | `risk_post_filter.py` (keeps, feeds risk_score)   | No change                                        |
| Fundamentals (Altman Z, Piotroski) | `risk_validator.py` (keeps)                       | No change                                        |

**File:**
[src/backend/pipeline/stages/risk_post_filter.py](src/backend/pipeline/stages/risk_post_filter.py)

- Remove ADX < 20 penalty (now in risk_validator as deterministic override)
- Remove RSI overbought/oversold penalty (owned by calibration)
- Remove low volume penalty (owned by calibration)
- Keep sentiment and fundamental penalties (unique to this layer)

---

## Phase Summary

| Phase                    | Files Modified                                                            | Effort | Impact |
| ------------------------ | ------------------------------------------------------------------------- | ------ | ------ |
| 1: Confidence Math       | confidence_calibration.py, ml_confidence_blend.py                         | Small  | Huge   |
| 2: Deterministic Rules   | risk_validator.py, schemas.py, orchestrator.py                            | Medium | Huge   |
| 3: Single-Pass Synthesis | gpt.py, gpt_debate.py                                                     | Medium | Large  |
| 4: Missing Features      | schemas.py, strategies.json, confidence_calibration.py, risk_validator.py | Medium | Medium |
| 5: Deduplication         | risk_post_filter.py                                                       | Small  | Medium |

Prompt versions bumped: Judge v15 to v16, Synthesis prompt hash regenerated.

Frontend types file (`src/frontend/src/types/index.ts`) needs
`expected_value: number | null` added to `Recommendation` interface.
