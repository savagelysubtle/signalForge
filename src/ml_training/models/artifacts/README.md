# Model Artifacts

Trained model files (.joblib) are stored here. These are gitignored.

## Artifact format

Each artifact is a `.joblib` file containing:
- `classifier`: Trained LightGBM direction classifier
- `regressor`: Trained LightGBM return regressor
- `calibrator`: Probability calibration model (Platt or Venn-Abers)
- `feature_names`: Ordered list of feature names
- `metadata`: Training config, metrics, version info

## Versioning

Files follow the pattern: `model_v{VERSION}_{YYYYMMDD}.joblib`

The active model for deployment is copied to `src/backend/ml/artifacts/model_active.joblib`.
