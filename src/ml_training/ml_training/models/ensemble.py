"""Stacked ensemble combining LightGBM, CatBoost, and XGBoost for robust predictions.

Uses a 2-level stacking architecture:
- Level 0: LightGBM, CatBoost, XGBoost base models (with feature diversity)
- Level 1: Logistic regression meta-learner on out-of-fold predictions

Follows the same CPCV walk-forward training pattern as PredictionModel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from sklearn.preprocessing import LabelEncoder

from ml_training.models.predictor import (
    BINARY_CLASSIFIER_PARAMS,
    CATEGORICAL_FEATURES,
    CLASSIFIER_PARAMS,
    DIRECTION_CLASSES,
    REGRESSOR_PARAMS,
    CPCVConfig,
    FoldResult,
    TrainingResult,
    _identify_feature_columns,
    _prepare_features,
    _purged_split,
    compute_sample_weights,
)

try:
    import catboost as cb

    CATBOOST_AVAILABLE = True
except ImportError:
    CATBOOST_AVAILABLE = False

try:
    import xgboost as xgb

    XGBOOST_AVAILABLE = True
except ImportError:
    XGBOOST_AVAILABLE = False

logger = logging.getLogger(__name__)

CATBOOST_CLASSIFIER_PARAMS: dict[str, Any] = {
    "iterations": 300,
    "depth": 5,
    "learning_rate": 0.05,
    "l2_leaf_reg": 5.0,
    "random_seed": 42,
    "verbose": 0,
    "auto_class_weights": "Balanced",
    "task_type": "CPU",
}

CATBOOST_BINARY_PARAMS: dict[str, Any] = {
    "iterations": 300,
    "depth": 5,
    "learning_rate": 0.05,
    "l2_leaf_reg": 5.0,
    "random_seed": 42,
    "verbose": 0,
    "auto_class_weights": "Balanced",
    "task_type": "CPU",
    "loss_function": "Logloss",
}

XGBOOST_CLASSIFIER_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 5,
    "learning_rate": 0.05,
    "reg_lambda": 5.0,
    "subsample": 0.8,
    "colsample_bytree": 0.6,
    "seed": 42,
    "verbosity": 0,
}

XGBOOST_BINARY_PARAMS: dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 5,
    "learning_rate": 0.05,
    "reg_lambda": 5.0,
    "subsample": 0.8,
    "colsample_bytree": 0.6,
    "seed": 42,
    "verbosity": 0,
    "objective": "binary:logistic",
    "eval_metric": "logloss",
}


@dataclass
class _BaseModelSpec:
    """Specification for a base model in the ensemble."""

    name: str
    model: Any
    feature_subset: np.ndarray


class _EnsembleAdapter:
    """Adapter that provides sklearn-like interface for the stacked ensemble.

    Aggregates predictions from base models via the meta-learner.
    """

    def __init__(
        self,
        base_models: list[_BaseModelSpec],
        meta_learner: LogisticRegression,
        feature_names: list[str],
        binary_mode: bool,
    ) -> None:
        """Initialize the ensemble adapter.

        Args:
            base_models: List of base model specifications with feature subsets.
            meta_learner: Trained logistic regression meta-learner.
            feature_names: Original feature column names.
            binary_mode: Whether operating in binary classification mode.
        """
        self._base_models = base_models
        self._meta_learner = meta_learner
        self._feature_names = feature_names
        self._binary_mode = binary_mode
        self._n_classes = 2 if binary_mode else 3

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Predict class labels.

        Args:
            X: Feature DataFrame.

        Returns:
            Class predictions.
        """
        probs = self.predict_proba(X)
        return np.argmax(probs, axis=1)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Predict class probabilities using the meta-learner.

        Args:
            X: Feature DataFrame.

        Returns:
            Probability matrix of shape (n_samples, n_classes).
        """
        meta_features = self._generate_meta_features(X)
        return self._meta_learner.predict_proba(meta_features)

    def _generate_meta_features(self, X: pd.DataFrame) -> np.ndarray:
        """Generate meta-features from base model predictions.

        Args:
            X: Feature DataFrame.

        Returns:
            Stacked prediction matrix.
        """
        meta_features_list = []
        for spec in self._base_models:
            X_subset = X.iloc[:, spec.feature_subset]
            if self._binary_mode:
                probs = spec.model.predict_proba(X_subset)
                if probs.shape[1] == 2:
                    meta_features_list.append(probs[:, 1:2])
                else:
                    meta_features_list.append(probs[:, 0:1])
            else:
                probs = spec.model.predict_proba(X_subset)
                meta_features_list.append(probs)

        return np.hstack(meta_features_list)

    @property
    def feature_importances_(self) -> np.ndarray:
        """Aggregate feature importances from base models.

        Returns:
            Mean feature importances across base models.
        """
        importances = []
        for spec in self._base_models:
            if hasattr(spec.model, "feature_importances_"):
                full_importance = np.zeros(len(self._feature_names))
                full_importance[spec.feature_subset] = spec.model.feature_importances_
                importances.append(full_importance)

        if not importances:
            return np.zeros(len(self._feature_names))

        return np.mean(importances, axis=0)


class StackedEnsembleModel:
    """Stacked ensemble model with LightGBM, CatBoost, and XGBoost base learners.

    Trains a 2-level stacking architecture:
    - Level 0: Three base models with random 80% feature subsets
    - Level 1: Logistic regression meta-learner on OOF predictions

    Uses CPCV walk-forward training with purge and embargo for time-series safety.
    """

    def __init__(
        self,
        target_col: str = "direction_10d",
        return_col: str = "return_10d",
        cpcv_config: CPCVConfig | None = None,
        classifier_params: dict[str, Any] | None = None,
        binary_mode: bool = False,
    ) -> None:
        """Initialize the stacked ensemble model.

        Args:
            target_col: Name of the target direction column.
            return_col: Name of the target return column.
            cpcv_config: CPCV configuration. Uses defaults if None.
            classifier_params: LightGBM classifier parameters (base model).
            binary_mode: If True, use binary classification (UP/DOWN only).
        """
        if not CATBOOST_AVAILABLE:
            logger.warning("CatBoost not available. Ensemble will use only LightGBM + XGBoost.")
        if not XGBOOST_AVAILABLE:
            logger.warning("XGBoost not available. Ensemble will use only LightGBM + CatBoost.")
        if not CATBOOST_AVAILABLE and not XGBOOST_AVAILABLE:
            logger.error(
                "Neither CatBoost nor XGBoost available. Consider installing: "
                "uv add catboost xgboost"
            )

        self._target_col = target_col
        self._return_col = return_col
        self._cpcv = cpcv_config or CPCVConfig()
        self._binary_mode = binary_mode

        if binary_mode:
            self._lgb_params = classifier_params or BINARY_CLASSIFIER_PARAMS.copy()
            self._cb_params = CATBOOST_BINARY_PARAMS.copy()
            self._xgb_params = XGBOOST_BINARY_PARAMS.copy()
        else:
            self._lgb_params = classifier_params or CLASSIFIER_PARAMS.copy()
            self._cb_params = CATBOOST_CLASSIFIER_PARAMS.copy()
            self._xgb_params = XGBOOST_CLASSIFIER_PARAMS.copy()

        self._result: TrainingResult | None = None

    def train(self, df: pd.DataFrame, n_rounds: int = 500) -> TrainingResult:
        """Train the stacked ensemble using CPCV walk-forward optimization.

        Args:
            df: Full training dataset with features and labels.
            n_rounds: Number of boosting rounds for base models.

        Returns:
            TrainingResult with ensemble adapter, metrics, and fold details.
        """
        if not CATBOOST_AVAILABLE and not XGBOOST_AVAILABLE:
            logger.error("Cannot train ensemble without CatBoost or XGBoost. Aborting.")
            return TrainingResult()

        df = df.dropna(subset=[self._target_col]).sort_values("date").reset_index(drop=True)

        feature_cols = _identify_feature_columns(df)
        X, _encoders = _prepare_features(df, feature_cols)

        if self._binary_mode:
            label_encoder = LabelEncoder()
            label_encoder.fit([0, 1])
            y_cls = df[self._target_col].astype(int).values
        else:
            label_encoder = LabelEncoder()
            label_encoder.fit(DIRECTION_CLASSES)
            y_cls = label_encoder.transform(df[self._target_col].values)

        return_col = self._return_col if self._return_col in df.columns else None
        y_reg = df[return_col].fillna(0).values if return_col else np.zeros(len(df))

        sample_weights = compute_sample_weights(len(X), self._cpcv.forward_horizon)

        n_samples = len(X)
        effective_splits = self._cpcv.n_splits
        effective_purge = max(self._cpcv.purge_window, self._cpcv.forward_horizon)
        effective_embargo = max(self._cpcv.embargo_window, self._cpcv.forward_horizon // 2)

        if n_samples < 100_000:
            effective_splits = min(self._cpcv.n_splits, 3)
            effective_purge = min(effective_purge, max(20, n_samples // 500))
            logger.info(
                "Small dataset (%d rows): n_splits=%d, purge=%d, embargo=%d",
                n_samples,
                effective_splits,
                effective_purge,
                effective_embargo,
            )

        tscv = TimeSeriesSplit(n_splits=effective_splits)

        n_features = X.shape[1]
        n_subset = max(int(n_features * 0.8), 1)
        rng = np.random.default_rng(42)

        lgb_features = rng.choice(n_features, size=n_subset, replace=False)
        cb_features = rng.choice(n_features, size=n_subset, replace=False)
        xgb_features = rng.choice(n_features, size=n_subset, replace=False)

        oof_preds_lgb = np.zeros((n_samples, 2 if self._binary_mode else 3))
        oof_preds_cb = np.zeros((n_samples, 2 if self._binary_mode else 3))
        oof_preds_xgb = np.zeros((n_samples, 2 if self._binary_mode else 3))
        oof_mask = np.zeros(n_samples, dtype=bool)

        fold_results: list[FoldResult] = []
        all_test_preds: list[np.ndarray] = []
        all_test_true: list[np.ndarray] = []

        categorical_indices_lgb = [i for i, c in enumerate(X.columns) if c in CATEGORICAL_FEATURES]
        categorical_indices_cb = [
            lgb_features.tolist().index(i)
            for i in range(len(X.columns))
            if i in lgb_features and X.columns[i] in CATEGORICAL_FEATURES
        ]

        logger.info(
            "Starting CPCV with %d splits, training 3 base models per fold...",
            effective_splits,
        )

        for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(X)):
            train_idx_clean = _purged_split(
                n_samples,
                train_idx,
                test_idx,
                effective_purge,
                effective_embargo,
            )

            if len(train_idx_clean) < self._cpcv.min_train_size:
                logger.warning(
                    "Fold %d: insufficient training samples (%d < %d), skipping",
                    fold_idx,
                    len(train_idx_clean),
                    self._cpcv.min_train_size,
                )
                continue

            X_train = X.iloc[train_idx_clean]
            X_test = X.iloc[test_idx]
            y_train = y_cls[train_idx_clean]
            y_test = y_cls[test_idx]
            w_train = sample_weights[train_idx_clean]

            lgb_clf = lgb.LGBMClassifier(**self._lgb_params, n_estimators=n_rounds)
            lgb_clf.fit(
                X_train.iloc[:, lgb_features],
                y_train,
                sample_weight=w_train,
                categorical_feature=categorical_indices_lgb,
                eval_set=[(X_test.iloc[:, lgb_features], y_test)],
                callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
            )

            if CATBOOST_AVAILABLE:
                if self._binary_mode:
                    cb_clf = cb.CatBoostClassifier(**self._cb_params, iterations=n_rounds)
                else:
                    cb_clf = cb.CatBoostClassifier(
                        **self._cb_params,
                        iterations=n_rounds,
                        classes_count=3,
                        loss_function="MultiClass",
                    )
                cb_clf.fit(
                    X_train.iloc[:, cb_features],
                    y_train,
                    sample_weight=w_train,
                    cat_features=categorical_indices_cb,
                    eval_set=(X_test.iloc[:, cb_features], y_test),
                    early_stopping_rounds=50,
                )
            else:
                cb_clf = None

            if XGBOOST_AVAILABLE:
                if self._binary_mode:
                    xgb_clf = xgb.XGBClassifier(**self._xgb_params, n_estimators=n_rounds)
                else:
                    xgb_clf = xgb.XGBClassifier(
                        **self._xgb_params,
                        n_estimators=n_rounds,
                        num_class=3,
                        objective="multi:softprob",
                    )
                xgb_clf.fit(
                    X_train.iloc[:, xgb_features],
                    y_train,
                    sample_weight=w_train,
                    eval_set=[(X_test.iloc[:, xgb_features], y_test)],
                    verbose=False,
                )
            else:
                xgb_clf = None

            lgb_probs = lgb_clf.predict_proba(X_test.iloc[:, lgb_features])
            cb_probs = cb_clf.predict_proba(X_test.iloc[:, cb_features]) if cb_clf else lgb_probs
            xgb_probs = (
                xgb_clf.predict_proba(X_test.iloc[:, xgb_features]) if xgb_clf else lgb_probs
            )

            oof_preds_lgb[test_idx] = lgb_probs
            oof_preds_cb[test_idx] = cb_probs
            oof_preds_xgb[test_idx] = xgb_probs
            oof_mask[test_idx] = True

            ensemble_probs = np.mean([lgb_probs, cb_probs, xgb_probs], axis=0)
            ensemble_preds = np.argmax(ensemble_probs, axis=1)

            test_acc = float(np.mean(ensemble_preds == y_test))

            train_lgb_probs = lgb_clf.predict_proba(X_train.iloc[:, lgb_features])
            train_cb_probs = (
                cb_clf.predict_proba(X_train.iloc[:, cb_features]) if cb_clf else train_lgb_probs
            )
            train_xgb_probs = (
                xgb_clf.predict_proba(X_train.iloc[:, xgb_features]) if xgb_clf else train_lgb_probs
            )
            train_ensemble_probs = np.mean(
                [train_lgb_probs, train_cb_probs, train_xgb_probs], axis=0
            )
            train_preds = np.argmax(train_ensemble_probs, axis=1)
            train_acc = float(np.mean(train_preds == y_train))

            fold_result = FoldResult(
                fold_idx=fold_idx,
                train_size=len(train_idx_clean),
                test_size=len(test_idx),
                train_accuracy=train_acc,
                test_accuracy=test_acc,
                test_predictions=ensemble_preds,
                test_probabilities=ensemble_probs,
                train_indices=train_idx_clean,
                test_indices=test_idx,
                test_true=y_test,
                feature_importances=lgb_clf.feature_importances_,
                best_iteration=getattr(lgb_clf, "best_iteration_", n_rounds),
            )
            fold_results.append(fold_result)
            all_test_preds.append(ensemble_preds)
            all_test_true.append(y_test)

            logger.info(
                "Fold %d: train_acc=%.3f, test_acc=%.3f, train=%d, test=%d",
                fold_idx,
                train_acc,
                test_acc,
                len(train_idx_clean),
                len(test_idx),
            )

        if not fold_results:
            logger.error("No valid CPCV folds completed")
            return TrainingResult()

        logger.info("Training level-1 meta-learner on OOF predictions...")
        meta_features = np.hstack([oof_preds_lgb, oof_preds_cb, oof_preds_xgb])
        meta_X = meta_features[oof_mask]
        meta_y = y_cls[oof_mask]

        meta_learner = LogisticRegression(
            max_iter=1000,
            random_state=42,
            solver="lbfgs",
            multi_class="multinomial" if not self._binary_mode else "auto",
        )
        meta_learner.fit(meta_X, meta_y)

        logger.info("Training final base models on 90%% of data...")
        split_n = int(len(X) * 0.9)
        X_fit, X_val = X.iloc[:split_n], X.iloc[split_n:]
        y_fit, y_val = y_cls[:split_n], y_cls[split_n:]
        w_fit = sample_weights[:split_n]

        final_lgb = lgb.LGBMClassifier(**self._lgb_params, n_estimators=n_rounds)
        final_lgb.fit(
            X_fit.iloc[:, lgb_features],
            y_fit,
            sample_weight=w_fit,
            categorical_feature=categorical_indices_lgb,
            eval_set=[(X_val.iloc[:, lgb_features], y_val)],
            callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
        )

        if CATBOOST_AVAILABLE:
            if self._binary_mode:
                final_cb = cb.CatBoostClassifier(**self._cb_params, iterations=n_rounds)
            else:
                final_cb = cb.CatBoostClassifier(
                    **self._cb_params,
                    iterations=n_rounds,
                    classes_count=3,
                    loss_function="MultiClass",
                )
            final_cb.fit(
                X_fit.iloc[:, cb_features],
                y_fit,
                sample_weight=w_fit,
                cat_features=categorical_indices_cb,
                eval_set=(X_val.iloc[:, cb_features], y_val),
                early_stopping_rounds=50,
            )
        else:
            final_cb = None

        if XGBOOST_AVAILABLE:
            if self._binary_mode:
                final_xgb = xgb.XGBClassifier(**self._xgb_params, n_estimators=n_rounds)
            else:
                final_xgb = xgb.XGBClassifier(
                    **self._xgb_params,
                    n_estimators=n_rounds,
                    num_class=3,
                    objective="multi:softprob",
                )
            final_xgb.fit(
                X_fit.iloc[:, xgb_features],
                y_fit,
                sample_weight=w_fit,
                eval_set=[(X_val.iloc[:, xgb_features], y_val)],
                verbose=False,
            )
        else:
            final_xgb = None

        base_models = [
            _BaseModelSpec(name="LightGBM", model=final_lgb, feature_subset=lgb_features),
        ]
        if final_cb:
            base_models.append(
                _BaseModelSpec(name="CatBoost", model=final_cb, feature_subset=cb_features)
            )
        if final_xgb:
            base_models.append(
                _BaseModelSpec(name="XGBoost", model=final_xgb, feature_subset=xgb_features)
            )

        ensemble_adapter = _EnsembleAdapter(
            base_models=base_models,
            meta_learner=meta_learner,
            feature_names=list(X.columns),
            binary_mode=self._binary_mode,
        )

        logger.info("Training final regressor...")
        reg_params = {**REGRESSOR_PARAMS, "seed": 0}
        final_reg = lgb.LGBMRegressor(**reg_params, n_estimators=n_rounds)
        final_reg.fit(
            X_fit,
            y_reg[:split_n],
            sample_weight=w_fit,
            categorical_feature=categorical_indices_lgb,
            eval_set=[(X_val, y_reg[split_n:])],
            callbacks=[lgb.log_evaluation(0), lgb.early_stopping(50, verbose=False)],
        )

        all_preds_concat = np.concatenate(all_test_preds)
        all_true_concat = np.concatenate(all_test_true)
        overall_acc = float(np.mean(all_preds_concat == all_true_concat))

        fold_accs = [f.test_accuracy for f in fold_results]
        train_accs = [f.train_accuracy for f in fold_results]
        overfit_gap = float(np.mean(train_accs) - np.mean(fold_accs))

        brier_scores = []
        for fr in fold_results:
            for i, true_label in enumerate(fr.test_true):
                prob = fr.test_probabilities[i, true_label]
                brier_scores.append((1 - prob) ** 2)

        accuracy_by_strategy: dict[str, float] = {}
        if "strategy_type" in df.columns:
            strat_col = df["strategy_type"].values
            for fr in fold_results:
                strat_counts: dict[str, list[float]] = {}
                for strat in np.unique(strat_col[fr.test_indices]):
                    mask = strat_col[fr.test_indices] == strat
                    if mask.sum() > 0:
                        acc = float(np.mean(fr.test_predictions[mask] == fr.test_true[mask]))
                        strat_counts.setdefault(strat, []).append(acc)
                for strat, accs in strat_counts.items():
                    if strat in accuracy_by_strategy:
                        accuracy_by_strategy[strat] = (
                            accuracy_by_strategy[strat] + float(np.mean(accs))
                        ) / 2
                    else:
                        accuracy_by_strategy[strat] = float(np.mean(accs))

        result = TrainingResult(
            classifier=ensemble_adapter,
            classifiers=[ensemble_adapter],
            regressor=final_reg,
            label_encoder=label_encoder,
            feature_names=list(X.columns),
            fold_results=fold_results,
            overall_accuracy=overall_acc,
            accuracy_std=float(np.std(fold_accs)),
            mean_brier_score=float(np.mean(brier_scores)) if brier_scores else 1.0,
            accuracy_by_strategy=accuracy_by_strategy,
            overfit_gap=overfit_gap,
        )

        self._result = result
        logger.info(
            "Ensemble training complete: accuracy=%.3f±%.3f, overfit_gap=%.3f, brier=%.3f, "
            "base_models=%d, meta_learner=LogisticRegression",
            overall_acc,
            result.accuracy_std,
            overfit_gap,
            result.mean_brier_score,
            len(base_models),
        )
        return result

    def predict(
        self,
        X: pd.DataFrame,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate predictions from the trained ensemble.

        Args:
            X: Feature DataFrame (same columns as training).

        Returns:
            Tuple of (direction predictions, probabilities, return predictions).

        Raises:
            RuntimeError: If model has not been trained.
        """
        if self._result is None or self._result.classifier is None:
            raise RuntimeError("Model not trained. Call train() first.")

        dir_probs = self._result.classifier.predict_proba(X)
        dir_preds = np.argmax(dir_probs, axis=1)

        ret_preds = (
            self._result.regressor.predict(X) if self._result.regressor else np.zeros(len(X))
        )

        return dir_preds, dir_probs, ret_preds

    @property
    def result(self) -> TrainingResult | None:
        """Get the training result."""
        return self._result
