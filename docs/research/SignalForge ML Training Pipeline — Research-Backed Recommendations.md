# SignalForge ML Training Pipeline — Research-Backed Recommendations

## Executive Summary

SignalForge's training pipeline is architecturally sound — CPCV, SHAP pruning, progressive regularization, and a 6-layer judge all reflect best practices. The earnings_play model's 26.7% overfit gap with 11K samples is not a failure of the pipeline's design: it is a symptom of three converging problems that no amount of LightGBM regularization alone can fully solve. These are (1) insufficient information density in the data as structured, (2) label noise that obscures the true signal boundary, and (3) feature construction that generates redundant rather than orthogonal signal. Each of the 10 areas below addresses one or more of these root causes with specific, actionable techniques supported by recent research.

***

## 1. Reducing Overfitting with Small Financial Datasets

The conventional anti-overfitting toolkit — L1/L2, DART, SHAP pruning, CPCV — is already in place. The research points to several complementary levers that operate at a different level.

### Composite Objective Functions for Optimization
Standard hyperparameter search optimizing for validation accuracy alone tends to select configurations that capture in-sample patterns. A 2025 paper from arXiv introduced the **GT-Score** — a composite objective that embeds performance, statistical significance, consistency, and downside risk into the search criterion itself. In walk-forward validation experiments across 50 stocks and 14,000+ optimization trials, GT-Score achieved a 98% higher generalization ratio versus optimizing on Sharpe or accuracy alone (0.365 vs. 0.185). The lesson for SignalForge: replace `composite = mean_accuracy − 2 × overfit_gap` with a richer objective that also penalizes variance across CV folds and rewards consistent cross-strategy performance.[^1]

### CatBoost as a Regularization-First Baseline
LightGBM's leaf-wise growth is explicitly noted to be "prone to overfitting, particularly for smaller datasets". CatBoost's **ordered boosting** uses permutation-driven gradient estimates that prevent prediction shift — effectively an algorithmic bias-reduction that operates independently of L1/L2. For the earnings_play scenario with 11K rows and 50+ features, a CatBoost baseline is worth training: its oblivious (symmetric) trees are structurally more regularized and frequently match or outperform LightGBM on small tabular sets. At minimum, a CatBoost / LightGBM ensemble with disjoint feature subsets is a low-cost diversity injection.[^2][^3][^4][^5]

### Reduce Feature Dimensionality Before Training
With ~50 features and 11K samples, the feature-to-sample ratio is aggressive. A recent significance-based approach — `shap-select` — runs linear regression on SHAP values against the validation target and filters features by statistical significance. This is more principled than pruning by raw SHAP magnitude (what SignalForge currently does) because it identifies features that contribute unique predictive signal rather than correlated proxy signals. A practical target: reduce to 20–25 features for strategies with fewer than 15K samples.[^6]

### Adaptive CPCV Variants
The 2024 KnowledgeBase Systems study that benchmarked multiple CV strategies confirmed CPCV's superiority but also proposed **Adaptive-CPCV** — a variant that modifies split sizes based on prevailing market conditions within each fold. This is especially relevant for regime-sensitive strategies (earnings plays, mean reversion) where a standard fixed-split CPCV treats 2018 patterns as equivalent to 2024 patterns.[^7]

***

## 2. Better Label Engineering

The direction label (UP/DOWN/FLAT based on forward return thresholds) is the weakest link in the pipeline. Research consistently identifies this as the primary source of training noise in financial ML.[^8]

### Triple Barrier Method
The **Triple Barrier Method** (Lopez de Prado, *Advances in Financial Machine Learning*) replaces fixed-horizon returns with path-dependent labels: a trade is labeled based on which barrier is hit first — upper (profit target), lower (stop loss), or vertical (time exit). This mirrors actual trade management and produces labels that encode risk-adjusted outcomes rather than raw price direction. A 2025 arXiv paper applied optimized triple-barrier labels to Korean stocks and found that balanced label proportions with a 29-day window and 9% barriers significantly improved downstream classifier performance. For SignalForge, barrier widths should be set as a multiple of ATR (already computed), making them naturally volatility-adaptive per strategy.[^9][^10]

### Meta-Labeling
**Meta-labeling** reframes the problem entirely: instead of predicting direction from scratch, a primary strategy generates trade signals (which may have a small edge), and the ML model predicts only whether each individual signal will be profitable. The signal generator can be a simple rule-based system (e.g., EMA crossover) with known positive expectancy. The meta-model then acts as a high-precision filter, converting a strategy with 52% win rate into one that executes only the 70%+ confidence subset. Meta-labeling is architecturally compatible with SignalForge's existing per-strategy structure and dramatically simplifies the prediction problem from multi-class direction to binary profitable/not.[^11][^12][^13][^14]

### Denoised Labels via Self-Supervised Pretraining
A 2021 paper on denoised financial labels showed that labels generated by a **denoising autoencoder** — trained as a self-supervised pretext task on the raw OHLCV series before classification — consistently outperformed raw fixed-horizon labels for both small and large datasets. The intuition is that the autoencoder must first learn to distinguish signal from noise in the price series; its reconstructed series produces cleaner threshold crossings. A 2024 paper extended this using conditional diffusion models for denoising, showing that classifiers trained on diffusion-denoised time series improved directional prediction and reduced noise-driven transaction costs.[^15][^16]

### Eliminate the FLAT Class
Research on 3-class direction prediction is unambiguous: FLAT is the class with least discriminative signal and most boundary contamination. The scientific literature on financial ML predominantly uses binary classification (profitable/not, or UP/DOWN with a minimum return filter). Consider collapsing to binary: trade or no-trade, with the primary direction determined by the strategy's inherent side bias. This halves the classification complexity and resolves the boundary noise problem that FLAT creates at the edges of the thresholds.[^17]

***

## 3. Feature Engineering Improvements

Hand-crafted technical indicators are highly correlated with each other (RSI, MACD, and momentum scores all encode overlapping information). The ML literature has matured considerably in this area.

### Fractional Differentiation for Stationarity with Memory Preservation
The most impactful single feature improvement from Lopez de Prado's work: **fractional differentiation** achieves stationarity in the price series while preserving long-range memory that integer differencing destroys. Raw price levels are non-stationary (making them unsuitable for ML) but contain predictive memory. A fixed-window fractional differencing (FFD) with the minimum `d*` that achieves stationarity preserves this memory and typically outperforms both raw prices and log returns as an ML input. Apply this to the core price series before deriving indicators.[^18][^19][^20]

### Alternative Bar Sampling: Dollar/Volume Bars
OHLCV bars sampled at fixed clock intervals have undesirable statistical properties — heteroskedastic returns, non-IID observations, and artificially high autocorrelation during inactive hours. **Dollar bars** (one bar per fixed dollar volume traded) and **volume bars** produce returns that are empirically closer to Gaussian and more IID, which is exactly what LightGBM needs to generalize. For intraday strategies (ORB, VWAP scalp, EMA Stack), resampling from dollar bars to build features reduces noise at the data structure level rather than requiring more regularization downstream.[^21][^22][^23]

### TSFresh: Automated Statistical Feature Extraction
**TSFresh** extracts 700+ statistical, frequency-domain, and structural features from raw time series, then applies significance tests (Benjamini-Hochberg correction) to filter to the predictive subset. A 2025 paper combining TSFresh with the Temporal Fusion Transformer achieved superior results on multivariate forecasting tasks over manually engineered features. For SignalForge, TSFresh is most useful for the intraday strategies where pattern complexity is higher — running it on the raw OHLCV price windows surrounding each signal event would surface non-obvious statistical features (e.g., permutation entropy, approximate entropy, spectral features) that hand-crafted indicators miss.[^24][^25][^26]

### Deep Feature Synthesis with Featuretools
**Featuretools DFS** constructs features by stacking aggregation and transformation primitives over relational/temporal data. For the fundamental features specifically — where relationships between P/E, ROE, Piotroski score, and sector context are likely non-linear and interaction-dependent — DFS automatically creates cross-entity features (e.g., sector-relative P/E ratio percentile) that encode context without manual construction. This is directly applicable to the fundamental layer and the multi-timeframe relationships.[^27][^28]

### Interaction Features via SHAP
SHAP interaction values identify which feature pairs drive the most joint predictive power. Running SHAP interaction analysis on a trained model and adding the top 5–10 interaction terms as explicit features (e.g., `ema_stack_score × vix_regime`) often recovers signal that a single tree split cannot capture, at no cost to interpretability.[^29]

***

## 4. Algorithm Alternatives and Ensemble Stacking

### TabPFN v2: The Strongest Small-Data Baseline
**TabPFN v2** — a transformer-based tabular foundation model — is trained via in-context learning on 100M+ synthetic classification tasks. On the authoritative TabArena benchmark (300+ datasets), TabPFN v2 consistently outperforms gradient-boosted trees, CatBoost, and deep tabular models for datasets with **up to 10,000 samples and 500 features**, in a single forward pass with no hyperparameter tuning. TabPFN-2.5 (November 2025) extended this further, topping the TabArena-Lite benchmark. The 11K-row earnings_play dataset is squarely in TabPFN's sweet spot — it is worth running as a zero-tuning baseline before anything else. TabPFN has also been demonstrated for time-series forecasting tasks out-of-the-box.[^30][^31][^32][^33]

### FinStack-Net: Hierarchical Stacking
A recent ACM paper introduced **FinStack-Net** — a hierarchical ensemble combining LightGBM, CatBoost, and a neural network with residual connections — specifically for financial tabular prediction. The key finding is that stacking models from *different algorithm families* (tree-based + neural) consistently outperforms stacking within a single family (7 LightGBM seeds). CatBoost's ordered boosting and LightGBM's leaf-wise growth capture different patterns; a logistic regression meta-learner stacked on top produces more calibrated and generalizable scores than either alone.[^34][^3][^35]

### CatBoost + LightGBM + XGBoost Weighted Ensemble
A practical stacking architecture for SignalForge: CatBoost (weight 0.4), XGBoost (0.3), LightGBM (0.3) as base models, with a calibrated logistic regression meta-learner. A 2025 fraud detection paper using exactly this configuration achieved AUC of 0.93 — outperforming every individual component. Critically, each base model should be trained on slightly different feature subsets to reduce correlation between their errors.[^3]

***

## 5. Market Regime-Aware Training

Treating `market_regime` as a categorical feature is the weakest possible way to use regime information. The model learns to average over regime transitions during training, which is precisely when its predictions are most likely to fail.

### Hidden Markov Models for Regime Detection
**Hidden Markov Models (HMMs)** are the established tool for unsupervised regime detection in financial markets. A 2025 multi-model ensemble-HMM framework demonstrated that combining HMM regime detection with tree-based ensembles significantly outperforms either alone for identifying bull, bear, and neutral market states. For SignalForge: fit a 3-state Gaussian HMM on the joint (VIX returns, S&P breadth, momentum) features. Then, instead of using `market_regime` as a model feature, **train separate sub-models per regime** and route live predictions through the appropriate sub-model based on HMM state at inference time.[^36][^37][^38]

### Gaussian Mixture Models for Regime Discovery
Two Sigma's published approach uses **Gaussian Mixture Models (GMM)** for data-driven regime discovery without pre-specifying regime boundaries. The GMM identifies regimes by clustering the joint distribution of factor returns — often revealing 4-5 distinct market states rather than the 4-bucket VIX encoding currently used. State Street Global Advisors uses a similar approach with 23 performance/uncertainty features to identify four distinct market regimes over 30 years. The key advantage: GMM regime labels are *continuous probability vectors* across states, not hard categorical assignments — this allows softer regime conditioning.[^39][^40]

### Regime-Switching Volatility for Strategy Gating
The simplest regime-aware improvement: a **risk manager filter** that gates predictions through the HMM state. During high-volatility regimes, force all models to return `FLAT` (no signal) or reduce their prediction confidence by a volatility-scaling factor. This is how QSTrader's HMM risk manager works in production — it doesn't require retraining, just a suppression layer on top of the existing scores.[^38]

### Adaptive Sample Weighting with Regime-Aware Meta-Learning
A November 2025 ACM paper proposed **Adaptive Sample Weighting** that adjusts training sample weights based on the regime context of each historical observation. Samples from market conditions that match the current regime are upweighted; samples from regime-dissimilar periods are downweighted. This is implemented as a meta-learning layer on the training procedure, not a separate model, and is directly applicable to LightGBM via the `sample_weight` parameter.[^41]

***

## 6. Calibration and Uncertainty Quantification

The earnings_play model's ECE of 0.02 with overall accuracy of 40.5% is a calibration paradox: the probabilities are statistically well-aligned with empirical frequencies, but those frequencies cluster near 0.33 (random chance for 3-class). Calibration without accuracy is not useful — the focus should shift to *discriminative calibration*: ensuring that high-probability predictions are meaningfully more accurate than low-probability ones.

### Isotonic Regression over Platt Scaling
Platt scaling assumes a sigmoid transformation and is known to underfit when the probability distribution is multi-modal or non-sigmoid shaped. **Isotonic regression calibration** is nonparametric, enforces monotonicity without a functional form assumption, and achieves zero in-sample ECE while the piecewise-constant constraint prevents overfitting. For financial classification, where calibration curves are frequently non-sigmoidal, isotonic calibration consistently outperforms Platt scaling.[^42][^43]

### Venn-ABERS Predictors
**Venn-ABERS predictors** produce two probabilities per prediction — `p0` (lower bound) and `p1` (upper bound) — rather than a single point estimate. The interval width captures *epistemic uncertainty*: narrow intervals indicate the model is reliably calibrated for that prediction; wide intervals signal that the calibration is unreliable. This is directly useful for trading: only execute signals where the Venn-ABERS interval is narrow (high-confidence calibration). A 2025 NeurIPS paper unified Venn-ABERS with conformal prediction into a single framework with finite-sample marginal calibration guarantees.[^44][^45][^46]

### Conformal Prediction with Exchangeability Correction
The current split conformal prediction approach assumes exchangeability. For financial data, this is violated because recent test samples are distribution-shifted relative to the calibration set. **Mondrian conformal prediction** conditions coverage on feature groups (e.g., per-regime), providing conditional rather than marginal coverage guarantees. For SignalForge's multi-strategy architecture, Mondrian conformal sets — one per strategy × regime combination — would produce tighter, more trustworthy prediction sets than the current global split conformal approach.[^47]

***

## 7. Online Learning and Incremental Updates

Full retraining from scratch discards the learning curve cost every time the system updates. For a 13-strategy pipeline, this creates a latency window where deployed models are stale relative to market conditions.

### River: The Scikit-Learn of Online ML
The **River library** provides online implementations of decision trees, random forests, gradient boosted trees, drift detectors, and ensemble methods — all updating per-sample without full retraining. River is the result of merging `creme` and `scikit-multiflow` and is the most production-ready Python library for streaming ML. Its `HoeffdingTreeClassifier` and `AMFClassifier` (Adaptive Mondrian Forests) are appropriate for the directional prediction tasks in SignalForge.[^48][^49]

### Warm-Starting LightGBM with Incremental Data
LightGBM supports `init_model` continuation: a new model can be initialized from existing tree structure and continue boosting on new data without discarding prior learning. Combined with a rolling window that keeps the past 6 months and weights recent data exponentially (via the `sample_weight` parameter), this produces incremental retraining with minimal compute. **Time-dependent weighted least squares** — where sample weights decay exponentially with age — has been shown to improve out-of-sample accuracy for 11 of 12 stock return predictors relative to uniform weighting.[^50]

### ADWIN-Triggered Full Retraining
Rather than retrain on a fixed schedule, ADWIN (ADaptive WINdowing) detects statistically significant distribution shifts and triggers retraining only when needed. The current pipeline already monitors ADWIN as part of the drift judge — the enhancement is to wire the drift detector output to a retraining trigger rather than just a CONDITIONAL_PASS verdict. This means full retrain occurs when the market genuinely shifts regimes, not on a monthly calendar.[^51]

***

## 8. Sample Efficiency Techniques

### GAN-Based Time Series Augmentation
Transformer-based GANs (**TTS-GAN**) trained on historical price windows can generate high-fidelity synthetic OHLCV segments that preserve the statistical properties (autocorrelation, fat tails, volatility clustering) of real financial data. A 2026 arXiv paper demonstrated that augmenting an LSTM training dataset with TTS-GAN synthetic data reduced MSE across 40 datasets and multiple forecasting horizons. For earnings_play with only 11K rows, augmentation to 25–30K rows is feasible. The key constraint: synthetic data must be generated from a window *prior* to the training cutoff to avoid leakage, and quality should be verified via statistical tests (KS test on return distributions, autocorrelation structure).[^52][^53]

### TimeGAN and QuantGAN Comparison
A 2024 study comparing TimeGAN, QuantGAN, and diffusion model-based generation found that **QuantGAN** and **DDPM-based approaches** more convincingly replicate the nuanced log-return behavior of real stocks than TimeGAN. For SignalForge, the Parquet-stored historical data is already structured for GAN training — implement QuantGAN on the strategy-specific price windows (not broad market data) to ensure the synthetic distribution matches each strategy's trading universe.[^54]

### TabPFN as a Transfer-Learning Feature Encoder
TabPFN's in-context learning creates internal representations of tabular patterns that transfer well across domains. A practical use: train TabPFN on all 13 strategies' datasets *jointly*, then use its penultimate-layer embeddings as input features to a lightweight LightGBM classifier per strategy. This leverages cross-strategy pattern transfer — the earnings_play model benefits from patterns learned in 12 other strategies — without violating temporal integrity.[^31][^30]

### Few-Shot Meta-Learning: X-Trend
The **X-Trend** framework uses few-shot learning and cross-attention over a context set of historical financial regimes to make trend predictions with minimal data. Across the turbulent 2018–2023 period, X-Trend achieved an 18.9% Sharpe ratio improvement over standard neural forecasters and a 10-fold improvement over conventional momentum strategies, while also enabling zero-shot predictions on unseen assets. The framework is available as an academic implementation and is directly applicable to SignalForge's regime-sparse strategies.[^55]

***

## 9. Target Variable Design

### Is UP/DOWN/FLAT the Right Framing?

The research literature offers a clear verdict: **3-class direction classification is the hardest possible framing** for financial prediction, not the most informative. A ScienceDirect study that explored many hyperparameter configurations found out-of-sample accuracy consistently converging to ~50% with 3-class direction prediction, regardless of model complexity. The recommendation from the quant finance community is to reframe the target:[^17]

| Target Design | Difficulty | Signal Quality | Production Utility |
|---|---|---|---|
| 3-class direction (UP/DOWN/FLAT) | Very High | Low (noisy boundaries) | Medium (hard to calibrate) |
| Binary profitable/not (current `profitable` label) | Medium | High (binary, cleaner) | High |
| Triple Barrier (binary: profit target hit before stop) | Medium | High (path-dependent) | Very High |
| Meta-label (filter on primary strategy signal) | Low | Highest (conditional on edge) | Very High |
| Return magnitude regression | Medium | High | High (position sizing) |

The binary `profitable` label already exists in the pipeline. Making it the *primary* target (replacing the 3-class direction classifier as the main model) is the single highest-ROI change in this document. The direction of the trade is determined by the strategy's rule; the ML model only decides whether to take it.

### Trend-Scanning Labels
Lopez de Prado's **trend-scanning** approach adapts the forward-return window dynamically: instead of fixing the forward horizon at 10 bars, it scans multiple horizons and uses the t-statistic of the linear trend as the label. This produces labels that are more statistically robust than single-horizon returns and naturally handles strategies with variable holding periods — which describes most of SignalForge's strategies.[^56]

### MFE/MAE Ratio as Continuous Target
Rather than binary profitability, `MFE / (MAE + epsilon)` is a continuous quality score for each trade — high values mean the trade moved in the right direction decisively before the adverse move, low values indicate choppiness. Using this as a regression target (and thresholding at inference time) is more granular than binary labels and allows position sizing based on predicted quality.[^12]

***

## 10. State of the Art in Quantitative ML (2024–2026)

### Key Papers and Findings

**Backtest Overfitting in the ML Era (2024, Knowledge-Based Systems):** Systematic benchmark of CV techniques in controlled synthetic and real S&P 500 environments. Confirms CPCV's superiority and introduces Adaptive-CPCV as the 2024 standard. Identifies that overfitting gap correlates strongly with the number of hyperparameter configurations tried — a strong argument for Optuna with a tighter budget rather than exhaustive grid search.[^7]

**TabPFN Nature Paper (2025):** Foundation model for small tabular data, outperforming GBDT in a single forward pass on datasets up to 10K samples. The defining result: "TabPFN v2 consistently outperforms existing methods on small- to medium-scale datasets" with no tuning, representing a paradigm shift for the exact problem SignalForge faces with earnings_play.[^30][^31]

**X-Trend Few-Shot Trading (2023, arXiv):** Cross-attentive few-shot learning for financial time-series trend following, demonstrating Sharpe ratio improvements via context-set regime transfer. The zero-shot performance on novel assets validates meta-learning for regime-sparse strategies.[^55]

**GT-Score Anti-Overfitting Objective (2025, arXiv):** Empirically demonstrates that embedding anti-overfitting criteria into the optimization objective reduces overfitting by 98% in walk-forward tests vs. conventional Sharpe/accuracy objectives. Directly applicable to Optuna search configuration.[^1]

**DELPHYNE Pre-Trained Financial Time Series Model (2025, arXiv):** A foundation model pre-trained on mixed financial time series (unlike general-purpose models), demonstrating that financial-domain pre-training improves both zero-shot and fine-tuned performance on downstream forecasting tasks. Available for fine-tuning on specific strategy time series.[^57]

**Generalized Venn-ABERS Calibration (2025, NeurIPS/ICML):** Extension of Venn-ABERS to multi-class and general loss functions with finite-sample marginal calibration guarantees. The current Platt scaling in SignalForge is the weakest point of the calibration stack.[^46][^44]

**Synthetic Data for Finance (CFA Institute Report, 2025):** Comprehensive review of GAN/diffusion synthetic data in investment management, noting that synthetic data augmentation is the primary industry-accepted solution to the financial ML overfitting problem caused by data scarcity.[^58][^59]

### Quant Community Consensus (2024–2025)

The r/algotrading and r/quant practitioner community consensus as of 2024–2025 is consistent: "The hardest challenge is avoiding overfitting, still. An understanding of your asset's market microstructure is your friend. The higher the number of degrees of freedom, the higher the risk of overfitting". The recommended stack for small-sample financial classification combines: dollar/volume bars → triple barrier labels → fractional differentiation → binary meta-labeling → CatBoost or TabPFN base model → Venn-ABERS calibration → HMM regime gating.[^60][^61]

***

## Priority Implementation Roadmap

Ranked by expected impact-to-effort ratio:

| Priority | Change | Effort | Expected Impact |
|---|---|---|---|
| 1 | Collapse to binary target (profitable/not or triple barrier) | Low | Very High — directly addresses label noise |
| 2 | TabPFN v2 as zero-tuning benchmark for all small strategies | Very Low | High — may outperform tuned LGBM immediately |
| 3 | Replace Platt scaling with Venn-ABERS or isotonic regression | Low | High — better discriminative calibration |
| 4 | Train HMM regime model; gate predictions through regime sub-models | Medium | High — separates regime-conditional patterns |
| 5 | Fractional differentiation of price features | Low | Medium-High — stationarity with memory |
| 6 | Triple Barrier labeling for swing strategies | Medium | Medium-High — path-dependent, volatility-adaptive |
| 7 | CatBoost + LightGBM stacked ensemble | Low | Medium — cross-algorithm diversity |
| 8 | TSFresh feature extraction on price windows | Medium | Medium — novel statistical features |
| 9 | GT-Score composite objective in Optuna | Low | Medium — reduces optimization-induced overfitting |
| 10 | TTS-GAN/QuantGAN augmentation for <15K strategies | High | Medium — increases effective dataset size |
| 11 | ADWIN-triggered retraining pipeline | Medium | Medium — keeps models market-current |
| 12 | Meta-labeling architecture (strategy signal → binary filter) | High | Very High (long term) — cleanest problem framing |

---

## References

1. [1 Introduction - arXiv](https://arxiv.org/html/2602.00080v1) - In walk-forward validation, GT-Score improves the generalization ratio (validation return divided by...

2. [[PDF] Advanced loan default prediction models using Machine Learning ...](https://jhss.scholasticahq.com/article/144823-advanced-loan-default-prediction-models-using-machine-learning-boosting-algorithms/attachment/303626.pdf) - The main advantage of XGBoost is its capability to regulate model complexity and prevent overfitting...

3. [A robust and interpretable ensemble machine learning model for ...](https://www.nature.com/articles/s41598-024-82062-x) - This study aims to improve fraud detection accuracy using machine learning techniques. Our approach ...

4. [CatBoost: Complete Guide to Categorical Boosting with Target ...](https://mbrenndoerfer.com/writing/catboost-categorical-boosting-complete-guide-target-encoding-symmetric-trees-python-implementation) - CatBoost addresses overfitting issues through its "oblivious trees" (symmetric trees) and regulariza...

5. [CatBoost for big data: an interdisciplinary review - PMC - NIH](https://pmc.ncbi.nlm.nih.gov/articles/PMC7610170/) - CatBoost's use of Ordered TS and Ordered Boosting make it a good choice for datasets with categorica...

6. [Lightweight Feature Selection Using SHAP Values and Regression](https://arxiv.org/html/2410.06815v1) - This paper presents a novel feature selection framework, shap-select. The framework conducts a linea...

7. [Backtest overfitting in the machine learning era: A comparison of out ...](https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110) - Our study evaluates various cross-validation techniques in mitigating backtest overfitting within a ...

8. [[PDF] Financial Time Series Data Processing for Machine Learning - arXiv](https://arxiv.org/pdf/1907.03010.pdf) - It also speaks about the data split method specific to time series, avoid- ing unwanted overfitting ...

9. [Stock Price Prediction Using Triple Barrier Labeling and Raw ... - arXiv](https://arxiv.org/html/2504.02249v2) - To address this, triple barrier labeling has emerged as a robust alternative by incorporating stop-l...

10. [Labeling Stock Prices for ML with Triple Barrier Method](https://wire.insiderfinance.io/triple-barrier-method-4cb60cf4c2f0) - By defining three barriers — an upper barrier (profit-taking level), a lower barrier (stop-loss leve...

11. [The Hidden Flaw in Your Financial ML Pipeline — Label Concurrency](https://www.mql5.com/en/articles/19850) - In Part 2 of this series, we explored the triple-barrier labeling method for creating machine learni...

12. [Meta Labeling for Algorithmic Trading: How to Amplify a Real Edge](https://www.reddit.com/r/algotrading/comments/1lnm48w/meta_labeling_for_algorithmic_trading_how_to/) - A much better approach for using machine learning is to have an underlying strategy that has an exis...

13. [Meta-Labeling - Wikipedia](https://en.wikipedia.org/wiki/Meta-Labeling) - Meta-labeling, also known as corrective AI, is a machine learning (ML) technique utilized in quantit...

14. [Data Labelling - Mlfin.py](https://mlfinpy.readthedocs.io/en/latest/Labelling.html) - Meta-labeling will increase your F1-score by filtering out the false positives, where the majority o...

15. [Denoised Labels for Financial Time-Series Data via Self-Supervised ...](https://arxiv.org/abs/2112.10139) - We investigate the idea of applying computer vision techniques to financial time-series to reduce th...

16. [A Financial Time Series Denoiser Based on Diffusion Model - arXiv](https://arxiv.org/html/2409.02138v1) - This paper introduces a novel approach utilizing the diffusion model as a denoiser for financial tim...

17. [To what extent can machine learning beat the financial market?](https://www.sciencedirect.com/science/article/abs/pii/S105752192400406X) - In this paper, we applied 10 technical analysis indicators to predict stock price movement direction...

18. [Fractionally Differentiated - Mlfin.py](https://mlfinpy.readthedocs.io/en/latest/FractionalDifferentiated.html) - The method proposed by Marcos Lopez de Prado aims to make data stationary while preserving as much m...

19. [Fractional Differentiation - Hudson & Thames](https://hudsonthames.org/fractional-differentiation/) - ... Financial Machine Learning (AFML) by Dr. Marcos Lopez de Prado therein he discusses fractionally...

20. [[PDF] Unleashing Long-Term Dependencies with Fractionally Differenced ...](https://arxiv.org/pdf/2309.13409.pdf) - This satisfies findings from de Prado (2018) that all price series achieve stationarity at around d ...

21. [Machine Learning Trading Essentials (Part 1): Financial Data Structures](https://hudsonthames.org/machine-learning-trading-essentials-part-1-financial-data-structures/) - Time bars are based on a predefined time interval, such as one minute or one hour. · Tick bars are b...

22. [Financial Data Structures: Tick, Volume, and Dollar Bars](https://www.youtube.com/watch?v=vxIc34xhMKI) - Widely known and used time bars don't show good statistical properties compared to volume and dollar...

23. [[WITH CODE] Data: Tick, Dollar and Volume bars](https://www.quantbeckman.com/p/what-are-your-bars-hiding-from-you) - Conversely, tick, volume, or dollar bars oversample active periods, distorting measures of average m...

24. [Multivariate Time Series Forecasting through Automated Feature ...](https://www.mfacademia.org/index.php/jcssa/article/view/221) - A forecasting method is proposed by combining TSFresh-based feature engineering with the Temporal Fu...

25. [blue-yonder/tsfresh: Automatic extraction of relevant ... - GitHub](https://github.com/blue-yonder/tsfresh) - The package provides systematic time-series feature extraction by combining established algorithms f...

26. [Introduction — tsfresh 0.21.1.post0.dev1+g69e50a5 documentation](https://tsfresh.readthedocs.io/en/latest/text/introduction.html) - tsfresh is used for systematic feature engineering from time-series and other sequential data [1]. T...

27. [How to Perform Deep Feature Synthesis with Featuretools Using DFS](https://www.statology.org/how-to-perform-deep-feature-synthesis-with-featuretools-using-dfs/) - In this article, we'll look at how DFS works. We'll use Featuretools to perform feature engineering ...

28. [Deep Feature Synthesis — Featuretools 1.31.0 documentation](https://featuretools.alteryx.com/en/stable/getting_started/afe.html) - Deep Feature Synthesis (DFS) is an automated method for performing feature engineering on relational...

29. [A SHAP-Based Interpretability Analysis of XGBoost for Loan Risk ...](https://dl.acm.org/doi/full/10.1145/3772900.3772936) - Local SHAP explanations revealed why specific high-risk loans were misclassified, while interaction ...

30. [Accurate predictions on small data with a tabular foundation model](https://www.nature.com/articles/s41586-024-08328-6) - Although transformer-based models can be applied to tabular data, TabPFN addresses two key limitatio...

31. [A Closer Look at TabPFN v2: Strength, Limitation, and Extension](https://arxiv.org/html/2502.17361v1) - In this paper, we comprehensively evaluate TabPFN v2 on over 300 datasets, confirming its exceptiona...

32. [[PDF] TabPFN-2.5: Advancing the State of the Art in Tabular Foundation ...](https://storage.googleapis.com/prior-labs-tabpfn-public/reports/TabPFN_2_5_tech_report.pdf) - TabPFN-2.5 is now the leading method for the industry standard benchmark. TabArena (which contains d...

33. [The Tabular Foundation Model TabPFN Outperforms Specialized ...](https://arxiv.org/html/2501.02945v2) - In this paper, we demonstrate how the newly released regression variant of TabPFN, a general tabular...

34. [Enhancing credit card fraud detection with a stacking-based hybrid ...](https://pmc.ncbi.nlm.nih.gov/articles/PMC12453863/) - Our present research work suggests a composite stacking ensemble model that incorporates a variety o...

35. [FinStack-Net: Hierarchical Feature Crossing and Stacked Ensemble ...](https://dl.acm.org/doi/pdf/10.1145/3762249.3762318) - In this work, we presented FinStack-Net, a hierarchical ensemble framework combining LightGBM, CatBo...

36. [A multi-model ensemble-HMM voting framework for market regime ...](https://www.aimspress.com/article/id/69045d2fba35de34708adb5d) - In this paper, we present a framework for detecting market regime shifts using a combination of tree...

37. [Hidden Markov Model Market Regimes: How HMM Detects Market ...](https://www.quantifiedstrategies.com/hidden-markov-model-market-regimes-how-hmm-detects-market-regimes-in-trading-strategies/) - Another advantage is flexibility: an HMM can be combined with almost any trading rule or machine-lea...

38. [Market Regime Detection using Hidden Markov Models in QSTrader](https://www.quantstart.com/articles/market-regime-detection-using-hidden-markov-models-in-qstrader/) - In this article the Hidden Markov Model will be utilised within the QSTrader framework as a risk-man...

39. [[PDF] Decoding Market Regimes - State Street Global Advisors](https://www.ssga.com/library-content/assets/pdf/global/pc/2025/decoding-market-regimes-with-machine-learning.pdf) - Our machine-learning approach, using 23 performance and uncertainty datasets, identified four distin...

40. [A Machine Learning Approach to Regime Modeling - Two Sigma](https://www.twosigma.com/articles/a-machine-learning-approach-to-regime-modeling/) - The authors offer a data-driven approach to modeling market regimes by applying a Gaussian Mixture M...

41. [Adaptive Sample Weighting with Regime-Aware Meta-Learning ...](https://dl.acm.org/doi/full/10.1145/3768292.3770374) - Recent advancements in artificial intelligence (AI) and deep learning have offered powerful tools to...

42. [Calibrating Classification Probabilities the Right Way](https://towardsdatascience.com/calibrating-classification-probabilities-the-right-way-da935caee18d/) - Venn-ABERS predictors are part of the Conformal Prediction family and thus can operate on top of any...

43. [Isotonic Calibration - Emergent Mind](https://www.emergentmind.com/topics/isotonic-calibration) - Isotonic calibration is a nonparametric, shape-constrained method that maps model scores to calibrat...

44. [Generalized Venn and Venn-Abers Calibration with Applications in ...](https://arxiv.org/html/2502.05676v2) - We introduce a unified framework for Venn and Venn-Abers calibration that extends Vovk's approach be...

45. [Classifier calibration using Venn-ABERS - Kaggle](https://www.kaggle.com/code/carlmcbrideellis/classifier-calibration-using-venn-abers) - Here we shall calibrate a base estimator using the Venn-ABERS technique and also calculate the resul...

46. [Generalized Venn and Venn-Abers Calibration with Applications in ...](https://icml.cc/virtual/2025/poster/44237) - We introduce a unified framework for Venn and Venn-Abers calibration that extends Vovk's approach be...

47. [Conformal Prediction - A Practical Guide with MAPIE](https://algotrading101.com/learn/conformal-prediction-guide/) - Conformal Prediction can help address the uncertainty surrounding trading hypotheses on which your a...

48. [Analysis and Recommendations for Two Key Incremental Learning ...](https://www.hcltech.com/blogs/analysis-and-recommendations-for-two-key-incremental-learning-libraries) - This blog discusses incremental learning and the implementation scheme, with an empirical comparison...

49. [online-ml/river: Online machine learning in Python - GitHub](https://github.com/online-ml/river) - It aims to be the most user-friendly library for doing machine learning on streaming data. River is ...

50. [Forecasting stock returns: A time-dependent weighted least squares ...](https://www.sciencedirect.com/science/article/abs/pii/S1386418120300379) - This paper contributes to the literature by proposing a new time-dependent weighted least squares (T...

51. [[PDF] An Integrated Preprocessing and Drift Detection Approach With ...](https://puretest.port.ac.uk/files/105008640/An_Integrated_Preprocessing_and_Drift_Detection_Approach_With_Adaptive_Windowing_for_Fraud_Detection_in_Payment_Systems.pdf) - By implementing Early Drift Detection Method (EDDM) and ADaptive WINdowing (ADWIN), the drift can be...

52. [[PDF] Evaluating generative models for synthetic financial data - arXiv](https://arxiv.org/pdf/2512.21791.pdf) - For each model, we generate synthetic datasets aligned with historical market se- quences. We assess...

53. [Financial time series augmentation using transformer based GAN ...](https://arxiv.org/html/2602.17865v1) - Generative Model Training: A TTS-GAN is trained on real segments of the stock price time series to g...

54. [Generation of synthetic financial time series by diffusion models - arXiv](https://arxiv.org/html/2410.18897v1) - This approach employs wavelet transformation to convert multiple time series (into images), such as ...

55. [Few-Shot Learning Patterns in Financial Time-Series for Trend ...](https://arxiv.org/html/2310.10500v2) - We leverage few-shot learning, and change-point detection to develop an agent which is able to produ...

56. [MetaTrader 5 Machine Learning Blueprint (Part 2): Labeling ... - MQL5](https://www.mql5.com/en/articles/18864) - Meta-labeling optimizes conviction and position sizing. The method you choose fundamentally shapes w...

57. [DELPHYNE: A Pre-Trained Model for General and Financial Time ...](https://arxiv.org/html/2506.06288v1) - The strength of a pre-trained time-series model lies in its ability to quickly adapt to downstream t...

58. [[PDF] Synthetic Data in Investment Management](https://rpc.cfainstitute.org/sites/default/files/docs/research-reports/tait_syntheticdataininvestmentmanagement_online.pdf) - I explain how to evaluate synthetic data quality and present an example case study using synthetic d...

59. [Governing synthetic data in the financial sector | Finance and Society](https://www.cambridge.org/core/journals/finance-and-society/article/governing-synthetic-data-in-the-financial-sector/BFBAEAD4A6E8EE8D0C0BD328CC056274) - Synthetic datasets, artificially generated to mimic real-world data while maintaining anonymization,...

60. [Where are we with ML in 2024? : r/algotrading - Reddit](https://www.reddit.com/r/algotrading/comments/1bg6xx5/where_are_we_with_ml_in_2024/) - Feature engineering - Fractional differentiation, structural breaks and filters. Labeling - Triple b...

61. [How hard is it to get up to date on state of the art machine learning?](https://www.reddit.com/r/quant/comments/1fiwqqm/how_hard_is_it_to_get_up_to_date_on_state_of_the/) - ML learning is expensive to use especially for AI trading, it's why all the big firms pay so much on...

