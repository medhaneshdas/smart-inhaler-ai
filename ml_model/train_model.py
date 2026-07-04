import os
from datetime import datetime
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine

from sklearn.ensemble import RandomForestClassifier, GradientBoostingRegressor
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.metrics import (
    classification_report, confusion_matrix,
    mean_squared_error, r2_score
)
import joblib

load_dotenv()

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:123456789@localhost:5432/smart_inhaler"
)
engine = create_engine(DATABASE_URL)

# Choose feature set:
#   "simple" -> matches your current Streamlit usage (4 features)
#   "full"   -> richer features (requires Streamlit to load scaler/columns)
FEATURE_SET = os.getenv("FEATURE_SET", "simple").lower()  # "simple" or "full"

RANDOM_STATE = 42
N_ESTIMATORS = 200

# -------------------------------------------------------------------
# Data loading
# -------------------------------------------------------------------
def load_data_from_db() -> pd.DataFrame:
    query = """
    SELECT 
        u.id,
        u.patient_id,
        u.timestamp,
        u.doses_left,
        u.flow_rate,
        u.pressure,
        u.quality,
        u.motion,
        u.gas,
        u.temperature,
        p.age,
        p.asthma_severity
    FROM inhaler_usage u
    JOIN patients p ON u.patient_id = p.id
    ORDER BY u.timestamp
    """
    df = pd.read_sql(query, engine)
    print(f"Loaded {len(df)} records from database")
    return df

def generate_synthetic_data(n_samples: int = 1000) -> pd.DataFrame:
    print("Generating synthetic training data...")
    rng = np.random.default_rng(42)

    df = pd.DataFrame({
        "id": np.arange(n_samples),
        "patient_id": rng.integers(1, 50, n_samples),
        "timestamp": pd.date_range("2024-01-01", periods=n_samples, freq="6h"),
        "doses_left": rng.integers(0, 200, n_samples),
        "flow_rate": rng.uniform(20, 80, n_samples),
        "pressure": rng.uniform(980, 1040, n_samples),
        "motion": rng.uniform(0, 1, n_samples),
        "gas": rng.uniform(80, 200, n_samples),
        "temperature": rng.uniform(20, 32, n_samples),
        "age": rng.integers(18, 80, n_samples),
        "asthma_severity": rng.choice(["Mild", "Moderate", "Severe"], n_samples),
    })

    score = (
        (df["flow_rate"] > 40).astype(float) * 0.3 +
        (df["motion"] < 0.3).astype(float) * 0.3 +
        (df["gas"] < 150).astype(float) * 0.2 +
        ((df["pressure"] > 990) & (df["pressure"] < 1030)).astype(float) * 0.2
    )
    df["quality"] = pd.cut(
        score, bins=[0, 0.3, 0.6, 0.8, 1.0],
        labels=["Missed", "Poor", "Fair", "Good"], include_lowest=True
    )
    return df

# -------------------------------------------------------------------
# Feature engineering
# -------------------------------------------------------------------
def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # Ensure timestamp is datetime
    if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    # Basic temporal features
    df["hour_of_day"] = df["timestamp"].dt.hour
    df["day_of_week"] = df["timestamp"].dt.dayofweek
    df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
    df["is_night"] = df["hour_of_day"].isin(list(range(0, 6)) + [22, 23]).astype(int)

    # Sort and compute time since last use (hours)
    df = df.sort_values(["patient_id", "timestamp"])
    df["time_since_last_use"] = (
        df.groupby("patient_id")["timestamp"].diff().dt.total_seconds() / 3600.0
    )
    df["time_since_last_use"] = df["time_since_last_use"].fillna(24.0).clip(lower=0.0, upper=168.0)

    # Derived features
    df["doses_percent_remaining"] = (df["doses_left"] / 200.0 * 100).clip(0, 100)
    df["low_dose_warning"] = (df["doses_left"] < 20).astype(int)
    df["motion_stable"] = (df["motion"] < 0.2).astype(int)
    df["gas_normal"] = (df["gas"] < 150).astype(int)
    df["pressure_normal"] = ((df["pressure"] > 980) & (df["pressure"] < 1050)).astype(int)

    # Targets
    quality_map = {"Good": 1, "Fair": 1, "Poor": 0, "Missed": 0}
    df["correct_usage"] = df["quality"].map(quality_map).astype("Int64")

    # Synthetic risk score (0..1) for demo
    df["risk_score"] = (
        (df["time_since_last_use"] > 24).astype(int) * 0.3 +
        (df["quality"].eq("Poor")).astype(int) * 0.2 +
        (df["quality"].eq("Missed")).astype(int) * 0.3 +
        (df["doses_left"] < 10).astype(int) * 0.2
    ).clip(0, 1)

    # Severity encoding
    severity_map = {"Mild": 1, "Moderate": 2, "Severe": 3}
    df["severity_encoded"] = df["asthma_severity"].map(severity_map)

    return df

def select_features(df: pd.DataFrame, set_name: str):
    """
    Returns: X, y_class, y_reg, feature_columns
    """
    if set_name == "simple":
        feature_columns = ["flow_rate", "pressure", "motion", "gas"]
    else:  # "full"
        feature_columns = [
            "flow_rate", "pressure", "motion", "gas",
            "temperature",
            "doses_left", "doses_percent_remaining",
            "time_since_last_use", "hour_of_day", "day_of_week",
            "is_weekend", "is_night", "low_dose_warning",
            "motion_stable", "gas_normal", "pressure_normal",
            "age", "severity_encoded",
        ]

    needed = feature_columns + ["correct_usage", "risk_score"]
    df = df[needed].copy()

    # Handle missing
    for col in feature_columns:
        if df[col].dtype.kind in "fiu":  # numeric
            df[col] = df[col].astype(float)
        df[col] = df[col].fillna(df[col].median())

    df["correct_usage"] = df["correct_usage"].fillna(0).astype(int)
    df["risk_score"] = df["risk_score"].fillna(0.0).astype(float)

    X = df[feature_columns]
    y_class = df["correct_usage"]
    y_reg = df["risk_score"]

    print(f"Features used ({set_name}): {feature_columns}")
    print(f"X shape: {X.shape}")
    print("Class distribution:\n", y_class.value_counts(dropna=False).to_string())

    return X, y_class, y_reg, feature_columns

# -------------------------------------------------------------------
# Training
# -------------------------------------------------------------------
def train_classifier(X, y):
    # Stratify only if both classes exist
    stratify = y if y.nunique() > 1 else None

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE, stratify=stratify
    )

    clf = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=None,
        max_features="sqrt",
        min_samples_split=6,
        min_samples_leaf=3,
        class_weight="balanced",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    train_acc = clf.score(X_train, y_train)
    test_acc = clf.score(X_test, y_test)

    print("\n=== Classification (Correct Usage) ===")
    print(f"Train Acc: {train_acc:.4f} | Test Acc: {test_acc:.4f}")

    if y_train.nunique() > 1:
        n_splits = min(5, len(y_train.unique()) * 2, len(y_train))
        n_splits = max(2, n_splits)
        skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
        cv = cross_val_score(clf, X_train, y_train, cv=skf, n_jobs=-1)
        print(f"CV: mean={cv.mean():.4f}, std={cv.std():.4f}, k={n_splits}")

    y_pred = clf.predict(X_test)
    print("\nClassification Report:")
    try:
        from sklearn.metrics import classification_report, confusion_matrix
        print(classification_report(y_test, y_pred, target_names=["Incorrect", "Correct"]))
        print("Confusion matrix:\n", confusion_matrix(y_test, y_pred))
    except Exception:
        pass

    # Feature importance
    imp = pd.DataFrame({"feature": X.columns, "importance": clf.feature_importances_})
    print("\nTop features:\n", imp.sort_values("importance", ascending=False).head(10).to_string(index=False))

    return clf

def train_regressor(X, y):
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=RANDOM_STATE
    )

    gbr = GradientBoostingRegressor(
        n_estimators=200,
        learning_rate=0.05,
        max_depth=3,
        subsample=0.9,
        random_state=RANDOM_STATE,
    )
    gbr.fit(X_train, y_train)

    train_pred = gbr.predict(X_train)
    test_pred = gbr.predict(X_test)

    print("\n=== Risk Score Regressor ===")
    print(f"Train MSE: {mean_squared_error(y_train, train_pred):.4f} | R²: {r2_score(y_train, train_pred):.4f}")
    print(f"Test  MSE: {mean_squared_error(y_test,  test_pred):.4f} | R²: {r2_score(y_test,  test_pred):.4f}")

    return gbr

# -------------------------------------------------------------------
# Save artifacts
# -------------------------------------------------------------------
def save_artifacts(clf, reg, feature_columns):
    os.makedirs("ml_model", exist_ok=True)
    joblib.dump(clf, "ml_model/model.pkl")
    joblib.dump(reg, "ml_model/risk_model.pkl")
    joblib.dump(feature_columns, "ml_model/feature_columns.pkl")
    print("\n✅ Saved:")
    print(" - ml_model/model.pkl")
    print(" - ml_model/risk_model.pkl")
    print(" - ml_model/feature_columns.pkl")

# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Smart Inhaler ML Model Training")
    print("=" * 60)

    try:
        df = load_data_from_db()
        if len(df) < 100:
            print(f"⚠️ Only {len(df)} records found; augmenting with synthetic data.")
            df_syn = generate_synthetic_data(1000)
            df = pd.concat([df, df_syn], ignore_index=True)
    except Exception as e:
        print(f"⚠️ DB error: {e}\nUsing synthetic data.")
        df = generate_synthetic_data(1200)

    df = engineer_features(df)
    X, y_cls, y_reg, cols = select_features(df, FEATURE_SET)

    clf = train_classifier(X, y_cls)
    reg = train_regressor(X, y_reg)

    save_artifacts(clf, reg, cols)

    print("\n" + "=" * 60)
    print("Training completed successfully! ✅")
    print("=" * 60)
    print("\nNext steps:")
    print("1) Start FastAPI:  uvicorn main:app --host 0.0.0.0 --port 8000")
    print("2) Streamlit:      streamlit run app.py")
    print("3) Ensure Streamlit loads feature_columns.pkl and uses the SAME columns/order.")

if __name__ == "__main__":
    main()
