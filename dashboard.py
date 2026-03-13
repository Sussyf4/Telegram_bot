#!/usr/bin/env python3
"""
dashboard.py — GENESIS V26: Bi-Directional Hedge Fund Engine

UPGRADES from V25:
 1. LIQUIDITY SWEEPS: Dist_to_Rolling_High/Low detect whale manipulation
 2. TIME-STOP: max_hold_hours force-closes zombie trades
 3. TIME-BASED BREAKEVEN: After N hours in profit, SL moves to entry
 4. LOSER'S AUTOPSY: Analyze why trades failed (day/hour/ADX)
 5. TRADE REPLAY: Candlestick chart with directional markers
 6. AI CONCEPT PLAYBOOK: Auto-generated trading manual from strategy JSON
 7. All V25 preserved: SHAP pruning, Anti-Cheat, Dual TF, Chop Filter, etc.

Usage: streamlit run dashboard.py
Requires: pip install streamlit ccxt pandas pandas_ta xgboost plotly joblib
                 scikit-learn optuna requests shap
"""
import streamlit as st
import pandas as pd
import pandas_ta as ta
import numpy as np
import xgboost as xgb
import plotly.graph_objects as go
import plotly.express as px
import joblib, ccxt, os, json, copy, glob, math, traceback, time, io
from datetime import datetime
from sklearn.metrics import (
    precision_score, recall_score, f1_score,
    classification_report, confusion_matrix,
)
import warnings
warnings.filterwarnings("ignore")

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

try:
    import requests as req_lib
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ================================================================
# HELPERS
# ================================================================
class SafeEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (np.floating, np.float32, np.float64)):
            return float(o)
        if isinstance(o, (np.integer, np.int32, np.int64)):
            return int(o)
        if isinstance(o, np.bool_):
            return bool(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        if isinstance(o, (pd.Timestamp, datetime)):
            return o.isoformat()
        if isinstance(o, pd.Series):
            return o.tolist()
        return super().default(o)

def sj(obj, **kw):
    return json.dumps(obj, cls=SafeEncoder, **kw)

def F(v):
    try:
        return float(v)
    except:
        return 0.0

def I(v):
    try:
        return int(v)
    except:
        return 0

PENALTY_SCORE = -999999.0
MIN_TRADES_HARD = 5

# ================================================================
# CONFIG
# ================================================================
st.set_page_config(
    page_title="GENESIS V26",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

MODEL_PATH = "genesis_v26.pkl"
STRAT_PATH = "strategies_v26.json"
SECRETS_PATH = "secrets.json"
SAVED_DIR = "saved_strategies_v26"
os.makedirs(SAVED_DIR, exist_ok=True)

CANDLE_PHYSICS = {"Body_Size", "Upper_Wick", "Lower_Wick", "Candle_Body"}

FEATURES_H1 = [
    "RSI_14", "RSI_Slope", "RSI_2", "RSI_Lag",
    "EMA_50", "EMA_200", "ATR_pct",
    "Relative_Volume", "Vol_Slope",
    "Price_Dist_EMA50", "Price_Dist_EMA200", "Dist_EMA200",
    "Return_1h", "Return_2h", "Return_3h",
    "Hour_of_Day",
    "ADX_14", "Bband_Width", "Bband_Position",
    "RSI_Cross_30", "RSI_Cross_70",
    "StochRSI_K", "StochRSI_D",
    "VWAP_Dist", "CCI_14", "CCI_Slope",
    "Williams_R", "Candle_Body",
    "Body_Size", "Upper_Wick", "Lower_Wick",
    "MACD_val", "MACD_signal", "MACD_hist",
    "BB_Upper", "BB_Lower",
    "CDL_Engulfing", "CDL_Hammer", "CDL_Star", "CDL_Marubozu",
    "Vol_Spike", "Dist_Support",
    # V26: Liquidity Sweep features
    "Dist_to_Rolling_High", "Dist_to_Rolling_Low",
]

FEATURES_H4 = [
    "H4_RSI_14", "H4_EMA_200", "H4_ADX_14", "H4_ATR_pct",
]

FEATURES_BASE = FEATURES_H1 + FEATURES_H4
FEATURES_V26 = FEATURES_BASE + ["Signal_Dir"]

THRESH_CANDS = [
    0.40, 0.45, 0.50, 0.52, 0.55, 0.58,
    0.60, 0.62, 0.65, 0.68, 0.70, 0.75, 0.80,
]
MIN_SIG = 30

DEFAULT_PRESET = {
    "name": "Default_V26",
    "tp_mult": 1.5, "sl_mult": 1.0,
    "rsi_entry": 45, "window": 12, "n_estimators": 800,
    "max_depth": 7, "learning_rate": 0.01, "threshold": 0.55,
    "adx_filter": 20, "use_candle_physics": True,
    "strategy_type": "bidir_ensemble", "bb_squeeze_thresh": 0.02,
    "min_votes": 2, "momentum_logic": "dip",
    "body_threshold": 0.3, "wick_threshold": 0.2,
    "use_trailing_stop": True, "trail_activation": 0.5,
    "trail_distance": 1.0,
    "trade_direction": "bidir",
    # V26 time-based risk
    "max_hold_hours": 24,
    "time_be_hours": 12,
    "score": 0, "win_rate": 0, "total_profit": 0, "signals": 0,
    "final_balance": 0, "profit_factor": 0,
    "created_at": "built-in", "asset_class": "crypto",
}

# ================================================================
# SESSION STATE
# ================================================================
for key, default in [
    ("miner_best_params", None),
    ("miner_best_balance", 0.0),
    ("miner_done", False),
    ("miner_trial_log", []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ================================================================
# SECRETS MANAGER
# ================================================================
def load_secrets():
    if os.path.exists(SECRETS_PATH):
        try:
            with open(SECRETS_PATH, "r") as f:
                return json.load(f)
        except:
            pass
    return {}

def save_secrets(secrets):
    with open(SECRETS_PATH, "w") as f:
        json.dump(secrets, f, indent=2)

# ================================================================
# SIMPLIFIED DATA LOADER
# ================================================================
def load_data(file):
    raw_bytes = file.read()
    file.seek(0)
    text = raw_bytes.decode("utf-8", errors="replace")
    sample = text[:2000]
    n_semi = sample.count(";")
    n_comma = sample.count(",")
    sep = ";" if n_semi > n_comma else ","
    if sep == ";":
        df = pd.read_csv(io.StringIO(text), sep=";", decimal=",", engine="python")
    else:
        df = pd.read_csv(io.StringIO(text), sep=",", engine="python")

    rename_map = {}
    for col in df.columns:
        col_clean = col.strip().lower()
        if col_clean in ("open time", "date", "datetime", "time", "timestamp"):
            rename_map[col] = "Datetime"
        elif col_clean == "open": rename_map[col] = "Open"
        elif col_clean == "high": rename_map[col] = "High"
        elif col_clean == "low": rename_map[col] = "Low"
        elif col_clean == "close": rename_map[col] = "Close"
        elif col_clean in ("volume", "vol"): rename_map[col] = "Volume"

    df = df.rename(columns=rename_map)
    df = df.loc[:, ~df.columns.duplicated(keep="first")]

    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
            )
        else:
            df[col] = np.nan

    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    else:
        df["Volume"] = pd.to_numeric(
            df["Volume"].astype(str).str.replace(",", ".").str.strip(), errors="coerce"
        ).fillna(0.0)

    if "Close" in df.columns:
        for col in ["Open", "High", "Low"]:
            mask = df[col].isna()
            if mask.any():
                df.loc[mask, col] = df.loc[mask, "Close"]

    df = df.dropna(subset=["Close"])
    df = df.reset_index(drop=True)
    return df, "utf-8"

# ================================================================
# DATE PARSER
# ================================================================
def parse_dates(df):
    df = df.copy()
    if "Datetime" not in df.columns:
        df["Datetime"] = pd.date_range(end=datetime.now(), periods=len(df), freq="1h")
        df = df.reset_index(drop=True)
        return df

    raw = df["Datetime"]
    numeric_vals = pd.to_numeric(raw, errors="coerce")
    non_null_numeric = numeric_vals.dropna()

    if len(non_null_numeric) > len(df) * 0.5:
        median_val = non_null_numeric.median()
        if median_val > 1e12:
            df["Datetime"] = pd.to_datetime(numeric_vals, unit="ms", errors="coerce")
        elif median_val > 1e9:
            df["Datetime"] = pd.to_datetime(numeric_vals, unit="s", errors="coerce")
        if df["Datetime"].notna().sum() > len(df) * 0.5:
            df = df.reset_index(drop=True)
            return df

    df["Datetime"] = pd.to_datetime(raw, errors="coerce")
    if df["Datetime"].notna().sum() < len(df) * 0.5:
        for fmt in [
            "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
            "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
            "%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%Y.%m.%d %H:%M",
        ]:
            try:
                parsed = pd.to_datetime(raw, format=fmt, errors="coerce")
                if parsed.notna().sum() > len(df) * 0.5:
                    df["Datetime"] = parsed
                    break
            except:
                continue

    if df["Datetime"].notna().sum() < len(df) * 0.5:
        df["Datetime"] = pd.date_range(end=datetime.now(), periods=len(df), freq="1h")

    df = df.reset_index(drop=True)
    return df

def date_range_fn(df):
    if "Datetime" in df.columns:
        v = df["Datetime"].dropna()
        if len(v) > 0:
            a, b = v.iloc[0], v.iloc[-1]
            if isinstance(a, pd.Timestamp):
                return a.strftime("%Y-%m-%d"), b.strftime("%Y-%m-%d")
            return str(a)[:10], str(b)[:10]
    return "Unknown", "Unknown"

def short_d(d):
    return str(d)[:10] if d and d != "Unknown" else "Unknown"

# ================================================================
# XGBoost Builder
# ================================================================
def build_xgb(n_est, max_d, lr, **extra):
    params = {
        "n_estimators": n_est, "max_depth": max_d, "learning_rate": lr,
        "scale_pos_weight": 1.0, "objective": "binary:logistic",
        "eval_metric": "logloss", "random_state": 42, "n_jobs": -1,
        "tree_method": "hist", "subsample": 0.7, "colsample_bytree": 0.7,
        "reg_alpha": 0.1, "reg_lambda": 1.0, "min_child_weight": 10, "gamma": 0.1,
    }
    params.update(extra)
    return xgb.XGBClassifier(**params)

# ================================================================
# PRESET MANAGER
# ================================================================
def load_strats():
    if os.path.exists(STRAT_PATH):
        try:
            with open(STRAT_PATH, "r") as f:
                d = json.load(f)
                if isinstance(d, list) and len(d) > 0:
                    return d
        except:
            pass
    return [copy.deepcopy(DEFAULT_PRESET)]

def save_strats(strats):
    with open(STRAT_PATH, "w") as f:
        json.dump(strats, f, cls=SafeEncoder, indent=2)

def get_preset(name):
    for s in load_strats():
        if s.get("name") == name:
            return s
    return copy.deepcopy(DEFAULT_PRESET)

def upsert_preset(preset):
    strats = load_strats()
    found = False
    for i, s in enumerate(strats):
        if s.get("name") == preset.get("name"):
            strats[i] = preset
            found = True
            break
    if not found:
        strats.append(preset)
    save_strats(strats)

def delete_preset(name):
    strats = [s for s in load_strats() if s.get("name") != name]
    if not strats:
        strats = [copy.deepcopy(DEFAULT_PRESET)]
    save_strats(strats)

def preset_names():
    return [s.get("name", "?") for s in load_strats()]

# ================================================================
# STRATEGY BANK
# ================================================================
def list_saved():
    return sorted(glob.glob(os.path.join(SAVED_DIR, "strat_*.json")), reverse=True)

def save_to_bank(data, bal, wr, asset_name="BTC"):
    wr_s = f"{wr:.0f}" if wr else "0"
    bal_s = f"{bal:.0f}" if bal else "0"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fn = f"strat_{asset_name}_BiDir_WR{wr_s}_Bal{bal_s}_{ts}.json"
    fp = os.path.join(SAVED_DIR, fn)
    sd = copy.deepcopy(data)
    sd["saved_at"] = datetime.now().isoformat()
    sd["final_balance_at_save"] = bal
    sd["asset_name"] = asset_name
    with open(fp, "w") as f:
        json.dump(sd, f, cls=SafeEncoder, indent=2)
    return fp

def load_from_bank(fp):
    try:
        with open(fp, "r") as f:
            return json.load(f)
    except:
        return None

# ================================================================
# MATH UTILS
# ================================================================
def kelly(wr, rr):
    if rr <= 0: return 0.0
    k = (wr * rr - (1 - wr)) / rr
    return min(max(k, 0) / 2, 0.25)

def expectancy(wr, tp, sl):
    return (wr * tp) - ((1 - wr) * sl)

def win_streak(yp, yt):
    outcomes = [1 if t == 1 else 0 for p, t in zip(yp, yt) if p == 1]
    if not outcomes: return 0.0, 0
    streaks, cur, mx = [], 0, 0
    for o in outcomes:
        if o == 1:
            cur += 1
            mx = max(mx, cur)
        else:
            if cur > 0: streaks.append(cur)
            cur = 0
    if cur > 0: streaks.append(cur)
    return round(np.mean(streaks) if streaks else 0, 1), mx

def v20_score(net_profit, profit_factor, total_trades):
    if total_trades < MIN_TRADES_HARD or net_profit <= 0 or profit_factor <= 0:
        return PENALTY_SCORE
    return net_profit * profit_factor * math.log(max(total_trades, 2))

# ================================================================
# H1 FEATURE ENGINEERING — V26 with Liquidity Sweeps
# ================================================================
def _calc_h1_features(df):
    df = df.copy()
    df = df.reset_index(drop=True)
    cm = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ("open", "o"): cm[c] = "Open"
        elif cl in ("high", "h"): cm[c] = "High"
        elif cl in ("low", "l"): cm[c] = "Low"
        elif cl in ("close", "c"): cm[c] = "Close"
        elif cl in ("volume", "vol", "v"): cm[c] = "Volume"
        elif cl in ("date", "datetime", "timestamp", "time", "date_time"):
            cm[c] = "Datetime"

    if cm:
        df = df.rename(columns=cm)

    df = df.loc[:, ~df.columns.duplicated(keep="first")]
    for nc in ["Open", "High", "Low", "Close", "Volume"]:
        if nc in df.columns:
            df[nc] = pd.to_numeric(df[nc], errors="coerce")

    if "Volume" not in df.columns:
        df["Volume"] = 0.0
    df["Volume"] = df["Volume"].fillna(0.0)
    has_volume = df["Volume"].sum() > 0

    rsi = ta.rsi(df["Close"], length=14)
    df["RSI_14"] = rsi if rsi is not None else np.nan
    df["RSI_Slope"] = (rsi - rsi.shift(3)) if rsi is not None else np.nan
    df["RSI_Lag"] = rsi.shift(1) if rsi is not None else np.nan
    r2 = ta.rsi(df["Close"], length=2)
    df["RSI_2"] = r2 if r2 is not None else np.nan

    e50 = ta.ema(df["Close"], length=50)
    df["EMA_50"] = e50 if e50 is not None else np.nan
    e200 = ta.ema(df["Close"], length=200)
    df["EMA_200"] = e200 if e200 is not None else np.nan

    atr = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    df["ATR_pct"] = (atr / df["Close"]) if atr is not None else np.nan
    df["ATR_raw"] = atr if atr is not None else np.nan

    vs = ta.sma(df["Volume"], length=20)
    if vs is not None and has_volume:
        df["Relative_Volume"] = df["Volume"] / vs.replace(0, np.nan)
        vn = df["Volume"] / vs.replace(0, np.nan)
        df["Vol_Slope"] = vn - vn.shift(3)
    else:
        df["Relative_Volume"] = 1.0
        df["Vol_Slope"] = 0.0

    df["Price_Dist_EMA50"] = (df["Close"] - df["EMA_50"]) / df["EMA_50"].replace(0, np.nan)
    df["Price_Dist_EMA200"] = (df["Close"] - df["EMA_200"]) / df["EMA_200"].replace(0, np.nan)
    df["Dist_EMA200"] = df["Price_Dist_EMA200"]
    df["Return_1h"] = df["Close"].pct_change(1)
    df["Return_2h"] = df["Close"].pct_change(2)
    df["Return_3h"] = df["Close"].pct_change(3)

    hd = False
    if "Datetime" in df.columns:
        try:
            dts = pd.to_datetime(df["Datetime"], errors="coerce")
            if dts.notna().sum() > len(df) * 0.5:
                df["Hour_of_Day"] = dts.dt.hour.astype(float)
                hd = True
        except:
            pass
    if not hd:
        df["Hour_of_Day"] = (np.arange(len(df)) % 24).astype(float)

    ar = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    if ar is not None and isinstance(ar, pd.DataFrame):
        ac = [c for c in ar.columns if "ADX" in c.upper()]
        df["ADX_14"] = ar[ac[0]].values if ac else ar.iloc[:, 0].values
    else:
        df["ADX_14"] = np.nan

    bb = ta.bbands(df["Close"], length=20, std=2.0)
    if bb is not None and isinstance(bb, pd.DataFrame):
        bl = [c for c in bb.columns if "BBL" in c.upper()]
        bu = [c for c in bb.columns if "BBU" in c.upper()]
        if bl and bu:
            bbl = bb[bl[0]].values
            bbu = bb[bu[0]].values
            bw = bbu - bbl
            df["Bband_Width"] = bw / df["Close"].values
            df["Bband_Position"] = np.where(bw > 0, (df["Close"].values - bbl) / bw, 0.5)
            df["BB_Upper"] = bbu
            df["BB_Lower"] = bbl
        else:
            for col in ["Bband_Width", "Bband_Position", "BB_Upper", "BB_Lower"]:
                df[col] = np.nan
    else:
        for col in ["Bband_Width", "Bband_Position", "BB_Upper", "BB_Lower"]:
            df[col] = np.nan

    if rsi is not None:
        rb = (rsi.shift(1) < 30) | (rsi.shift(2) < 30) | (rsi.shift(3) < 30)
        df["RSI_Cross_30"] = np.where(rb & (rsi >= 30), 1.0, 0.0)
        ra = (rsi.shift(1) > 70) | (rsi.shift(2) > 70) | (rsi.shift(3) > 70)
        df["RSI_Cross_70"] = np.where(ra & (rsi <= 70), 1.0, 0.0)
    else:
        df["RSI_Cross_30"] = np.nan
        df["RSI_Cross_70"] = np.nan

    try:
        sr = ta.stochrsi(df["Close"], length=14, rsi_length=14, k=3, d=3)
        if sr is not None and isinstance(sr, pd.DataFrame) and len(sr.columns) >= 2:
            df["StochRSI_K"] = sr.iloc[:, 0].values
            df["StochRSI_D"] = sr.iloc[:, 1].values
        else:
            raise ValueError
    except:
        if rsi is not None:
            rmn = rsi.rolling(14).min()
            rmx = rsi.rolling(14).max()
            rng = rmx - rmn
            sr_raw = np.where(rng > 0, (rsi - rmn) / rng, 0.5)
            sk = pd.Series(sr_raw, index=df.index).rolling(3).mean()
            df["StochRSI_K"] = sk.values
            df["StochRSI_D"] = sk.rolling(3).mean().values
        else:
            df["StochRSI_K"] = np.nan
            df["StochRSI_D"] = np.nan

    try:
        if has_volume:
            tp_c = (df["High"] + df["Low"] + df["Close"]) / 3
            vol = df["Volume"].replace(0, np.nan)
            vwap = (tp_c * vol).cumsum() / vol.cumsum()
            df["VWAP_Dist"] = (df["Close"] - vwap) / vwap.replace(0, np.nan)
        else:
            df["VWAP_Dist"] = 0.0
    except:
        df["VWAP_Dist"] = 0.0

    try:
        cci = ta.cci(df["High"], df["Low"], df["Close"], length=14)
        if cci is not None:
            df["CCI_14"] = cci.values
            df["CCI_Slope"] = (cci - cci.shift(3)).values
        else:
            raise ValueError
    except:
        try:
            t2 = (df["High"] + df["Low"] + df["Close"]) / 3
            s14 = t2.rolling(14).mean()
            m14 = t2.rolling(14).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
            cc = (t2 - s14) / (0.015 * m14.replace(0, np.nan))
            df["CCI_14"] = cc.values
            df["CCI_Slope"] = (cc - cc.shift(3)).values
        except:
            df["CCI_14"] = np.nan
            df["CCI_Slope"] = np.nan

    try:
        wr_val = ta.willr(df["High"], df["Low"], df["Close"], length=14)
        df["Williams_R"] = wr_val.values if wr_val is not None else np.nan
    except:
        try:
            hh = df["High"].rolling(14).max()
            ll = df["Low"].rolling(14).min()
            rng = hh - ll
            df["Williams_R"] = np.where(rng > 0, -100 * (hh - df["Close"]) / rng, -50.0)
        except:
            df["Williams_R"] = np.nan

    o = df["Open"].values.astype(float)
    h = df["High"].values.astype(float)
    l_a = df["Low"].values.astype(float)
    c = df["Close"].values.astype(float)
    osf = df["Open"].replace(0, np.nan)
    df["Candle_Body"] = (df["Close"] - df["Open"]) / osf
    ab = np.abs(c - o)
    uw = h - np.maximum(o, c)
    lw = np.minimum(o, c) - l_a
    cr = h - l_a
    crs = np.where(cr > 0, cr, 1e-10)
    df["Body_Size"] = ab / crs
    df["Upper_Wick"] = uw / crs
    df["Lower_Wick"] = lw / crs

    try:
        macd_df = ta.macd(df["Close"], fast=12, slow=26, signal=9)
        if macd_df is not None and isinstance(macd_df, pd.DataFrame):
            cols = macd_df.columns.tolist()
            m_c = [x for x in cols if "MACD_12" in x and "s" not in x.lower() and "h" not in x.lower()]
            s_c = [x for x in cols if "MACDs" in x or "signal" in x.lower()]
            h_c = [x for x in cols if "MACDh" in x or "hist" in x.lower()]
            df["MACD_val"] = macd_df[m_c[0]].values if m_c else macd_df.iloc[:, 0].values
            df["MACD_signal"] = macd_df[s_c[0]].values if s_c else macd_df.iloc[:, 1].values
            df["MACD_hist"] = macd_df[h_c[0]].values if h_c else macd_df.iloc[:, 2].values
        else:
            raise ValueError
    except:
        ema12 = df["Close"].ewm(span=12).mean()
        ema26 = df["Close"].ewm(span=26).mean()
        macd_line = ema12 - ema26
        sig_line = macd_line.ewm(span=9).mean()
        df["MACD_val"] = macd_line.values
        df["MACD_signal"] = sig_line.values
        df["MACD_hist"] = (macd_line - sig_line).values

    eng = np.zeros(len(df))
    for i in range(1, len(df)):
        pb = c[i - 1] - o[i - 1]
        cb = c[i] - o[i]
        if pb < 0 and cb > 0 and abs(cb) > abs(pb) and c[i] > o[i - 1] and o[i] < c[i - 1]:
            eng[i] = 1.0
    df["CDL_Engulfing"] = eng

    hammer = np.zeros(len(df))
    for i in range(len(df)):
        body = abs(c[i] - o[i])
        low_wick = min(o[i], c[i]) - l_a[i]
        up_wick = h[i] - max(o[i], c[i])
        rng_i = h[i] - l_a[i]
        if rng_i > 0 and body > 0:
            if low_wick >= 2 * body and up_wick <= body * 0.5:
                hammer[i] = 1.0
    df["CDL_Hammer"] = hammer

    star = np.zeros(len(df))
    for i in range(1, len(df)):
        body = abs(c[i] - o[i])
        rng_i = h[i] - l_a[i]
        if rng_i > 0 and body < 0.3 * rng_i:
            lw_i = min(o[i], c[i]) - l_a[i]
            uw_i = h[i] - max(o[i], c[i])
            if lw_i > 0 and uw_i > 0:
                star[i] = 1.0
    df["CDL_Star"] = star

    marubozu = np.zeros(len(df))
    for i in range(len(df)):
        body = abs(c[i] - o[i])
        rng_i = h[i] - l_a[i]
        if rng_i > 0 and body > 0.8 * rng_i:
            marubozu[i] = 1.0
    df["CDL_Marubozu"] = marubozu

    if has_volume and vs is not None:
        df["Vol_Spike"] = np.where(df["Volume"] > vs * 1.5, 1.0, 0.0)
    else:
        df["Vol_Spike"] = 0.0

    roll_min_20 = df["Low"].rolling(20).min()
    df["Dist_Support"] = (df["Close"] - roll_min_20) / df["Close"].replace(0, np.nan)

    # V26: LIQUIDITY SWEEP DETECTION
    rolling_high_50 = df["High"].rolling(50, min_periods=1).max()
    rolling_low_50 = df["Low"].rolling(50, min_periods=1).min()
    close_safe = df["Close"].replace(0, np.nan)
    df["Dist_to_Rolling_High"] = ((rolling_high_50 - df["Close"]) / close_safe).clip(lower=0.0)
    df["Dist_to_Rolling_Low"] = ((df["Close"] - rolling_low_50) / close_safe).clip(lower=0.0)

    df = df.reset_index(drop=True)
    return df

# ================================================================
# H4 MACRO FEATURES
# ================================================================
def _calc_h4_macro_features(df_h4):
    df = df_h4.copy().reset_index(drop=True)
    cm = {}
    for c in df.columns:
        cl = str(c).strip().lower()
        if cl in ("open", "o"): cm[c] = "Open"
        elif cl in ("high", "h"): cm[c] = "High"
        elif cl in ("low", "l"): cm[c] = "Low"
        elif cl in ("close", "c"): cm[c] = "Close"
        elif cl in ("volume", "vol", "v"): cm[c] = "Volume"
    if cm:
        df = df.rename(columns=cm)
    for nc in ["Open", "High", "Low", "Close"]:
        if nc in df.columns:
            df[nc] = pd.to_numeric(df[nc], errors="coerce")

    rsi_h4 = ta.rsi(df["Close"], length=14)
    df["H4_RSI_14"] = rsi_h4 if rsi_h4 is not None else np.nan
    e200_h4 = ta.ema(df["Close"], length=200)
    df["H4_EMA_200"] = e200_h4 if e200_h4 is not None else np.nan

    ar_h4 = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    if ar_h4 is not None and isinstance(ar_h4, pd.DataFrame):
        ac = [c for c in ar_h4.columns if "ADX" in c.upper()]
        df["H4_ADX_14"] = ar_h4[ac[0]].values if ac else ar_h4.iloc[:, 0].values
    else:
        df["H4_ADX_14"] = np.nan

    atr_h4 = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    df["H4_ATR_pct"] = (atr_h4 / df["Close"]) if atr_h4 is not None else np.nan

    h4_cols = ["Datetime"] + [c for c in df.columns if c.startswith("H4_")]
    available_cols = [c for c in h4_cols if c in df.columns]
    result = df[available_cols].copy().reset_index(drop=True)
    return result

# ================================================================
# DUAL-TIMEFRAME MERGE WITH ANTI-CHEAT
# ================================================================
def calc_features(df_h1, df_h4=None):
    df_h1 = df_h1.reset_index(drop=True)
    if "Datetime" in df_h1.columns:
        df_h1["Datetime"] = pd.to_datetime(df_h1["Datetime"], errors="coerce")
        df_h1 = df_h1.sort_values("Datetime").reset_index(drop=True)
    df_h1_feat = _calc_h1_features(df_h1).reset_index(drop=True)

    if df_h4 is None or len(df_h4) == 0:
        for col in FEATURES_H4:
            df_h1_feat[col] = np.nan
        return df_h1_feat

    df_h4 = df_h4.reset_index(drop=True)
    if "Datetime" in df_h4.columns:
        df_h4["Datetime"] = pd.to_datetime(df_h4["Datetime"], errors="coerce")
        df_h4 = df_h4.sort_values("Datetime").reset_index(drop=True)
    df_h4_macro = _calc_h4_macro_features(df_h4).reset_index(drop=True)

    if "Datetime" not in df_h1_feat.columns or "Datetime" not in df_h4_macro.columns:
        for col in FEATURES_H4:
            df_h1_feat[col] = np.nan
        return df_h1_feat

    df_h1_feat["Datetime"] = pd.to_datetime(df_h1_feat["Datetime"], errors="coerce")
    df_h4_macro["Datetime"] = pd.to_datetime(df_h4_macro["Datetime"], errors="coerce")
    df_h1_feat = df_h1_feat.dropna(subset=["Datetime"]).sort_values("Datetime").reset_index(drop=True)
    df_h4_macro = df_h4_macro.dropna(subset=["Datetime"]).sort_values("Datetime").reset_index(drop=True)

    h4_feature_cols = [c for c in df_h4_macro.columns if c.startswith("H4_")]
    for col in h4_feature_cols:
        df_h4_macro[col] = df_h4_macro[col].shift(1)
    df_h4_macro = df_h4_macro.dropna(subset=h4_feature_cols, how="all").reset_index(drop=True)

    merged = pd.merge_asof(
        df_h1_feat, df_h4_macro, on="Datetime",
        direction="backward", suffixes=("", "_h4_dup"),
    )
    dup_cols = [c for c in merged.columns if c.endswith("_h4_dup")]
    if dup_cols:
        merged = merged.drop(columns=dup_cols)
    for col in FEATURES_H4:
        if col not in merged.columns:
            merged[col] = np.nan
    merged = merged.reset_index(drop=True)
    return merged

# ================================================================
# BI-DIRECTIONAL SIGNAL GENERATOR
# ================================================================
def compute_bidir_signals(df, adx_filter=20, bb_squeeze_thresh=0.02,
                          rsi_entry=45, momentum_logic="dip",
                          body_threshold=0.3, wick_threshold=0.2,
                          min_votes=2):
    n = len(df)
    signal_dir = np.zeros(n, dtype=np.float64)
    close = df["Close"].values.astype(float)
    ema200 = df["EMA_200"].values.astype(float) if "EMA_200" in df.columns else np.full(n, np.nan)
    adx = df["ADX_14"].values.astype(float) if "ADX_14" in df.columns else np.full(n, np.nan)
    bbw = df["Bband_Width"].values.astype(float) if "Bband_Width" in df.columns else np.full(n, np.nan)
    rsi_arr = df["RSI_14"].values.astype(float) if "RSI_14" in df.columns else np.full(n, np.nan)
    body_arr = df["Body_Size"].values.astype(float) if "Body_Size" in df.columns else np.full(n, np.nan)
    lower_wick = df["Lower_Wick"].values.astype(float) if "Lower_Wick" in df.columns else np.full(n, np.nan)
    upper_wick = df["Upper_Wick"].values.astype(float) if "Upper_Wick" in df.columns else np.full(n, np.nan)

    for i in range(n):
        adx_i = adx[i]
        bbw_i = bbw[i]
        if np.isnan(adx_i) or np.isnan(bbw_i):
            continue
        if (adx_i < adx_filter) or (bbw_i < bb_squeeze_thresh):
            continue

        ema_i = ema200[i]
        close_i = close[i]
        if np.isnan(ema_i) or np.isnan(close_i):
            continue

        is_bull = close_i > ema_i
        is_bear = close_i < ema_i
        if not is_bull and not is_bear:
            continue

        rsi_i = rsi_arr[i]
        body_i = body_arr[i]

        if is_bull:
            vote1 = 1
            vote2 = 0
            if not np.isnan(rsi_i):
                if momentum_logic == "dip":
                    vote2 = 1 if rsi_i < rsi_entry else 0
                else:
                    vote2 = 1 if rsi_i > rsi_entry else 0
            vote3 = 0
            lw_i = lower_wick[i]
            if not np.isnan(body_i) and not np.isnan(lw_i):
                if body_i > body_threshold and lw_i > wick_threshold:
                    vote3 = 1
            total = vote1 + vote2 + vote3
            signal_dir[i] = 1.0 if total >= min_votes else 0.0
        else:
            vote1 = 1
            vote2 = 0
            if not np.isnan(rsi_i):
                if momentum_logic == "dip":
                    vote2 = 1 if rsi_i > rsi_entry else 0
                else:
                    vote2 = 1 if rsi_i < rsi_entry else 0
            vote3 = 0
            uw_i = upper_wick[i]
            if not np.isnan(body_i) and not np.isnan(uw_i):
                if body_i > body_threshold and uw_i > wick_threshold:
                    vote3 = 1
            total = vote1 + vote2 + vote3
            signal_dir[i] = -1.0 if total >= min_votes else 0.0

    return pd.Series(signal_dir, index=df.index, name="Signal_Dir")

# ================================================================
# V26: BI-DIRECTIONAL TARGET with TIME-STOP
# ================================================================
def make_target_bidir(df, signal_dir, tp_m=1.5, sl_m=1.0, window=12,
                      use_trailing=False, trail_activation=0.5,
                      trail_distance=1.0, max_hold_hours=24):
    cl = df["Close"].values.astype(float)
    hi = df["High"].values.astype(float)
    lo = df["Low"].values.astype(float)
    op = df["Open"].values.astype(float) if "Open" in df.columns else cl.copy()
    atr = df["ATR_raw"].values.astype(float) if "ATR_raw" in df.columns else np.full(len(df), np.nan)
    sig = signal_dir.values.astype(float) if isinstance(signal_dir, pd.Series) else signal_dir.astype(float)
    n = len(cl)
    tgt = np.full(n, np.nan)
    effective_window = min(window, max_hold_hours) if max_hold_hours > 0 else window

    for i in range(n):
        direction = sig[i]
        if direction == 0.0 or np.isnan(direction):
            continue
        if i + 1 >= n or np.isnan(atr[i]) or atr[i] <= 0:
            continue

        entry = cl[i]
        end = min(i + 1 + effective_window, n)
        res = 0.0

        if direction == 1.0:
            tp_level = entry + tp_m * atr[i]
            sl_level = entry - sl_m * atr[i]
            current_sl = sl_level
            for j in range(i + 1, end):
                bars_held = j - i
                if use_trailing:
                    unrealized = hi[j] - entry
                    if unrealized >= trail_activation * atr[i]:
                        new_sl = hi[j] - trail_distance * atr[i]
                        current_sl = max(current_sl, new_sl)
                hit_sl = lo[j] <= current_sl
                hit_tp = hi[j] >= tp_level
                if hit_sl and hit_tp:
                    res = 1.0 if current_sl >= entry else (
                        1.0 if (tp_level - op[j]) < (op[j] - current_sl) else 0.0)
                    break
                elif hit_sl:
                    res = 1.0 if current_sl >= entry else 0.0
                    break
                elif hit_tp:
                    res = 1.0
                    break
                if bars_held >= max_hold_hours:
                    res = 0.0
                    break
        elif direction == -1.0:
            tp_level = entry - tp_m * atr[i]
            sl_level = entry + sl_m * atr[i]
            current_sl = sl_level
            for j in range(i + 1, end):
                bars_held = j - i
                if use_trailing:
                    unrealized_drop = entry - lo[j]
                    if unrealized_drop >= trail_activation * atr[i]:
                        new_sl = lo[j] + trail_distance * atr[i]
                        current_sl = min(current_sl, new_sl)
                hit_sl = hi[j] >= current_sl
                hit_tp = lo[j] <= tp_level
                if hit_sl and hit_tp:
                    res = 1.0 if current_sl <= entry else (
                        1.0 if (op[j] - tp_level) < (current_sl - op[j]) else 0.0)
                    break
                elif hit_sl:
                    res = 1.0 if current_sl <= entry else 0.0
                    break
                elif hit_tp:
                    res = 1.0
                    break
                if bars_held >= max_hold_hours:
                    res = 0.0
                    break

        tgt[i] = res
    return pd.Series(tgt, index=df.index, name="Target")

# ================================================================
# V26: SIMULATOR with TIME-BASED BREAKEVEN
# ================================================================
def simulate_bidir(ypd, yt, y_prob, atr_v, tp_m, sl_m, cap, fee,
                   use_trailing=False, trail_activation=0.5,
                   trail_distance=1.0, time_be_hours=12,
                   close_prices=None, high_prices=None,
                   low_prices=None, signal_dirs=None):
    bal = cap
    eq = [bal]
    gp = 0.0
    gl = 0.0
    pnls = []
    sizes_used = []
    be_saves = 0

    for i in range(len(ypd)):
        if ypd[i] != 1:
            eq.append(bal)
            continue
        ap = F(atr_v[i]) if i < len(atr_v) else 0.0
        if ap <= 0 or np.isnan(ap):
            eq.append(bal)
            continue

        prob_i = F(y_prob[i]) if i < len(y_prob) else 0.5
        if prob_i >= 0.85:
            size_mult = 1.5
        elif prob_i >= 0.70:
            size_mult = 1.0
        else:
            size_mult = 0.5
        sizes_used.append(size_mult)
        fc = bal * (fee / 100.0)

        actual_outcome = yt[i]
        if (actual_outcome == 0 and time_be_hours > 0 and
                close_prices is not None and high_prices is not None and
                low_prices is not None and signal_dirs is not None and
                i < len(close_prices)):
            entry_price = close_prices[i]
            direction = signal_dirs[i] if i < len(signal_dirs) else 1.0
            was_profitable = False
            check_end = min(i + 1 + time_be_hours, len(close_prices))
            for j in range(i + 1, check_end):
                if direction == 1.0:
                    if high_prices[j] > entry_price:
                        was_profitable = True
                        break
                elif direction == -1.0:
                    if low_prices[j] < entry_price:
                        was_profitable = True
                        break
            if was_profitable:
                actual_outcome = -1
                be_saves += 1

        if actual_outcome == 1:
            pnl = (bal * ap * tp_m) * size_mult
            gp += pnl
        elif actual_outcome == -1:
            pnl = 0.0
        else:
            pnl = -((bal * ap * sl_m) * size_mult)
            gl += abs(pnl)

        net = pnl - fc
        pnls.append(net)
        bal += net
        bal = max(bal, 0)
        eq.append(bal)

    ea = np.array(eq)
    ea = np.where(ea < 0, 0, ea)
    pk = np.maximum.accumulate(ea)
    dd = (pk - ea) / np.where(pk > 0, pk, 1)
    mdd = F(np.max(dd)) * 100 if len(dd) > 0 else 0.0
    pf = gp / gl if gl > 0 else (999.0 if gp > 0 else 0.0)
    bt = max(pnls) if pnls else 0.0
    wt = min(pnls) if pnls else 0.0

    avg_size = np.mean(sizes_used) if sizes_used else 1.0
    sniper_count = sum(1 for s in sizes_used if s == 1.5)
    standard_count = sum(1 for s in sizes_used if s == 1.0)
    cautious_count = sum(1 for s in sizes_used if s == 0.5)

    return (
        eq, round(bal, 2), round(mdd, 2), round(pf, 2),
        round(gp, 2), round(gl, 2), round(bt, 2), round(wt, 2),
        round(avg_size, 2), sniper_count, standard_count, cautious_count,
        be_saves,
    )

# ================================================================
# THRESHOLD OPTIMIZER
# ================================================================
def opt_threshold(yt, yp, pr, cands=None, ms=30):
    if cands is None: cands = THRESH_CANDS
    res = []
    for th in cands:
        preds = (yp >= th).astype(int)
        ns = I(preds.sum())
        if ns < ms:
            res.append({"Threshold": th, "Signals": ns, "Win Rate": 0.0,
                        "Total Profit": 0.0, "Score": -999.0, "Status": "SKIP"})
            continue
        w = I(((preds == 1) & (yt == 1)).sum())
        wr = w / ns if ns > 0 else 0.0
        tr = np.where(preds[:-1] == 1, pr[1:], 0)
        t2 = tr[tr != 0]
        tp2 = F(np.sum(t2))
        sc = tp2 * 10000 * (1 + wr ** 2)
        res.append({"Threshold": th, "Signals": ns, "Win Rate": round(wr * 100, 1),
                    "Total Profit": round(tp2 * 100, 3), "Score": round(sc, 2), "Status": "OK"})
    rdf = pd.DataFrame(res)
    valid = rdf[rdf["Status"] == "OK"]
    best = F(valid.loc[valid["Score"].idxmax(), "Threshold"]) if len(valid) > 0 else max(cands)
    return best, rdf

# ================================================================
# MONTHLY BREAKDOWN
# ================================================================
def monthly_bd(tdf, yp, yt):
    rows = []
    if "Datetime" not in tdf.columns:
        return pd.DataFrame({"Note": ["No datetime"]})
    dts = pd.to_datetime(tdf["Datetime"], errors="coerce")
    ma = dts.dt.to_period("M").astype(str).values
    bm = yp == 1
    wm = (yp == 1) & (yt == 1)
    for m in sorted(set(x for x in ma if x != "NaT")):
        mm = ma == m
        s = I((mm & bm).sum())
        w = I((mm & wm).sum())
        wr = (w / s * 100) if s > 0 else 0.0
        rows.append({"Month": m, "Candles": I(mm.sum()), "Signals": s,
                     "Wins": w, "Losses": s - w, "WR%": round(wr, 1)})
    return pd.DataFrame(rows)

# ================================================================
# SHAP FEATURE PRUNING
# ================================================================
def shap_prune_features(model, X_train, feature_names, prune_pct=0.25):
    if not HAS_SHAP:
        return feature_names, [], {}
    try:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_train)
        if isinstance(shap_values, list):
            shap_values = shap_values[1]
        mean_abs_shap = np.abs(shap_values).mean(axis=0)
        shap_importance = {fname: float(sval) for fname, sval in zip(feature_names, mean_abs_shap)}
        sorted_features = sorted(shap_importance.items(), key=lambda x: x[1], reverse=True)
        n_keep = max(int(len(sorted_features) * (1 - prune_pct)), 5)
        kept = [f[0] for f in sorted_features[:n_keep]]
        pruned = [f[0] for f in sorted_features[n_keep:]]
        return kept, pruned, shap_importance
    except:
        return feature_names, [], {}

# ================================================================
# ANTI-CHEAT MONITOR
# ================================================================
def anti_cheat_monitor(train_wr, test_wr, container=None):
    target = container if container is not None else st
    alerts = []
    if train_wr > 90 and test_wr < 55:
        target.error(f"🚨 Severe Overfitting. Train={train_wr:.1f}% Test={test_wr:.1f}%")
        alerts.append("OVERFIT")
    if test_wr > 85:
        target.error(f"🚨 Possible Leakage. Test={test_wr:.1f}%")
        alerts.append("LEAKAGE")
    if train_wr > 80 and test_wr < 45:
        target.warning(f"⚠️ Large gap. Train={train_wr:.1f}% Test={test_wr:.1f}%")
        alerts.append("GAP_WARNING")
    if not alerts:
        if test_wr > 50:
            target.success(f"✅ No issues. Train={train_wr:.1f}% Test={test_wr:.1f}%")
        else:
            target.info(f"ℹ️ Underperforming. Train={train_wr:.1f}% Test={test_wr:.1f}%")
    return alerts

# ================================================================
# V26 SINGLE TRIAL
# ================================================================
def run_trial_v26(df_f, fc, params, start_cap, fee_pct):
    try:
        tp_m = F(params.get("tp_mult", 1.5))
        sl_m = F(params.get("sl_mult", 1.0))
        rsi_e = I(params.get("rsi_entry", 45))
        win = I(params.get("window", 12))
        n_est = I(params.get("n_estimators", 800))
        max_d = I(params.get("max_depth", 7))
        lr = F(params.get("learning_rate", 0.01))
        thresh = F(params.get("threshold", 0.55))
        use_cp = params.get("use_candle_physics", True)
        adx_f = I(params.get("adx_filter", 20))
        bb_sq = F(params.get("bb_squeeze_thresh", 0.02))
        min_votes = I(params.get("min_votes", 2))
        momentum_logic = params.get("momentum_logic", "dip")
        body_thresh = F(params.get("body_threshold", 0.3))
        wick_thresh = F(params.get("wick_threshold", 0.2))
        use_trailing = params.get("use_trailing_stop", False)
        trail_act = F(params.get("trail_activation", 0.5))
        trail_dist = F(params.get("trail_distance", 1.0))
        max_hold = I(params.get("max_hold_hours", 24))
        time_be = I(params.get("time_be_hours", 12))

        if use_cp:
            active_fc = [f for f in fc if f in df_f.columns]
        else:
            active_fc = [f for f in fc if f not in CANDLE_PHYSICS and f in df_f.columns]
        if "Signal_Dir" not in active_fc:
            active_fc.append("Signal_Dir")

        df = df_f.copy().reset_index(drop=True)
        signal_dir = compute_bidir_signals(df, adx_f, bb_sq, rsi_e, momentum_logic,
                                           body_thresh, wick_thresh, min_votes)
        df["Signal_Dir"] = signal_dir
        df["Target"] = make_target_bidir(df, signal_dir, tp_m, sl_m, win,
                                         use_trailing, trail_act, trail_dist, max_hold)
        df_active = df[df["Signal_Dir"] != 0].copy().reset_index(drop=True)
        dc = df_active.dropna(subset=active_fc + ["Target"]).reset_index(drop=True)
        dc["Target"] = dc["Target"].astype(int)

        if len(dc) < 500:
            return {"score": PENALTY_SCORE, "win_rate": 0, "signals": 0,
                    "total_profit": 0, "final_balance": start_cap, "profit_factor": 0,
                    "long_signals": 0, "short_signals": 0, "be_saves": 0}

        sp = int(len(dc) * 0.80)
        trn = dc.iloc[:sp].copy().reset_index(drop=True)
        tst = dc.iloc[sp:].copy().reset_index(drop=True)

        if len(trn) < 100 or len(tst) < 30:
            return {"score": PENALTY_SCORE, "win_rate": 0, "signals": 0,
                    "total_profit": 0, "final_balance": start_cap, "profit_factor": 0,
                    "long_signals": 0, "short_signals": 0, "be_saves": 0}

        Xtr = trn[active_fc].values.astype(np.float64)
        ytr = trn["Target"].values.astype(int)
        Xte = tst[active_fc].values.astype(np.float64)
        yte = tst["Target"].values.astype(int)

        if len(np.unique(ytr)) < 2 or len(np.unique(yte)) < 2:
            return {"score": PENALTY_SCORE, "win_rate": 0, "signals": 0,
                    "total_profit": 0, "final_balance": start_cap, "profit_factor": 0,
                    "long_signals": 0, "short_signals": 0, "be_saves": 0}

        draft_model = build_xgb(n_est, max_d, lr)
        draft_model.fit(Xtr, ytr, eval_set=[(Xte, yte)], verbose=False)
        kept_features, _, _ = shap_prune_features(draft_model, Xtr, active_fc, 0.25)
        kept_indices = [i for i, f in enumerate(active_fc) if f in kept_features]
        if len(kept_indices) < 5:
            kept_indices = list(range(len(active_fc)))

        Xtr_p = Xtr[:, kept_indices]
        Xte_p = Xte[:, kept_indices]
        mdl = build_xgb(n_est, max_d, lr)
        mdl.fit(Xtr_p, ytr, eval_set=[(Xte_p, yte)], verbose=False)

        yp = mdl.predict_proba(Xte_p)[:, 1]
        ypd = (yp >= thresh).astype(int)
        total_trades = I(ypd.sum())
        if total_trades < MIN_TRADES_HARD:
            return {"score": PENALTY_SCORE, "win_rate": 0, "signals": total_trades,
                    "total_profit": 0, "final_balance": start_cap, "profit_factor": 0,
                    "long_signals": 0, "short_signals": 0, "be_saves": 0}

        w = I(((ypd == 1) & (yte == 1)).sum())
        wr = w / total_trades if total_trades > 0 else 0.0
        test_dirs = tst["Signal_Dir"].values
        long_sigs = I(((ypd == 1) & (test_dirs == 1)).sum())
        short_sigs = I(((ypd == 1) & (test_dirs == -1)).sum())
        atr_test = tst["ATR_pct"].values

        (eq, final_bal, mdd, pf, gp, gl, bt_best, bt_worst,
         avg_sz, sniper_n, std_n, cautious_n, be_saves) = simulate_bidir(
            ypd, yte, yp, atr_test, tp_m, sl_m, start_cap, fee_pct,
            use_trailing, trail_act, trail_dist, time_be,
            tst["Close"].values if "Close" in tst.columns else None,
            tst["High"].values if "High" in tst.columns else None,
            tst["Low"].values if "Low" in tst.columns else None,
            test_dirs,
        )

        net_profit = final_bal - start_cap
        score = v20_score(net_profit, pf, total_trades)
        return {
            "score": round(score, 4), "win_rate": round(wr * 100, 1),
            "signals": total_trades, "total_profit": round(net_profit, 2),
            "final_balance": round(final_bal, 2), "profit_factor": round(pf, 2),
            "long_signals": long_sigs, "short_signals": short_sigs,
            "avg_size": avg_sz, "be_saves": be_saves,
        }
    except Exception:
        return {"score": PENALTY_SCORE, "win_rate": 0, "signals": 0,
                "total_profit": 0, "final_balance": start_cap, "profit_factor": 0,
                "long_signals": 0, "short_signals": 0, "be_saves": 0}

# ================================================================
# V26 FULL BACKTEST
# ================================================================
def full_backtest(df_feat, fc, p, start_cap, fee_pct):
    tp_m = F(p.get("tp_mult", 1.5))
    sl_m = F(p.get("sl_mult", 1.0))
    rsi_e = I(p.get("rsi_entry", 45))
    win_sz = I(p.get("window", 12))
    n_est = I(p.get("n_estimators", 800))
    max_d = I(p.get("max_depth", 7))
    lr_v = F(p.get("learning_rate", 0.01))
    thresh_v = F(p.get("threshold", 0.55))
    use_cp = p.get("use_candle_physics", True)
    adx_f = I(p.get("adx_filter", 20))
    bb_sq = F(p.get("bb_squeeze_thresh", 0.02))
    min_votes = I(p.get("min_votes", 2))
    momentum_logic = p.get("momentum_logic", "dip")
    body_thresh = F(p.get("body_threshold", 0.3))
    wick_thresh = F(p.get("wick_threshold", 0.2))
    use_trailing = p.get("use_trailing_stop", False)
    trail_act = F(p.get("trail_activation", 0.5))
    trail_dist = F(p.get("trail_distance", 1.0))
    max_hold = I(p.get("max_hold_hours", 24))
    time_be = I(p.get("time_be_hours", 12))

    be_wr = sl_m / (tp_m + sl_m) * 100
    rr = tp_m / sl_m if sl_m > 0 else 1.0

    if use_cp:
        active_fc = [f for f in fc if f in df_feat.columns]
    else:
        active_fc = [f for f in fc if f not in CANDLE_PHYSICS and f in df_feat.columns]
    if "Signal_Dir" not in active_fc:
        active_fc.append("Signal_Dir")

    df = df_feat.copy().reset_index(drop=True)
    avg_atr = F(df["ATR_raw"].mean()) if "ATR_raw" in df.columns else 0.0

    st.info("🧬 Computing bi-directional signals with Chop Filter...")
    signal_dir = compute_bidir_signals(df, adx_f, bb_sq, rsi_e, momentum_logic,
                                       body_thresh, wick_thresh, min_votes)
    df["Signal_Dir"] = signal_dir
    n_long = I((signal_dir == 1).sum())
    n_short = I((signal_dir == -1).sum())
    n_chop = I((signal_dir == 0).sum())
    st.info(f"📊 Signals: 🟢 {n_long} Long | 🔴 {n_short} Short | 🟣 {n_chop} Chop (filtered)")

    df["Target"] = make_target_bidir(df, signal_dir, tp_m, sl_m, win_sz,
                                     use_trailing, trail_act, trail_dist, max_hold)

    df_active = df[df["Signal_Dir"] != 0].copy().reset_index(drop=True)
    dc = df_active.dropna(subset=active_fc + ["Target"]).reset_index(drop=True)
    dc["Target"] = dc["Target"].astype(int)

    if "Datetime" in df.columns:
        vm = df["Signal_Dir"] != 0
        valid_mask = df.loc[vm, active_fc + ["Target"]].notna().all(axis=1)
        dv = df.loc[vm].loc[valid_mask, "Datetime"].values
        if len(dv) == len(dc):
            dc["Datetime"] = dv

    if len(dc) < 400:
        return None, "Not enough rows after feature engineering + chop filter"
    if I((dc["Target"] == 1).sum()) == 0:
        return None, "No positive targets found"

    sp = int(len(dc) * 0.80)
    trn_raw = dc.iloc[:sp].copy().reset_index(drop=True)
    tst_raw = dc.iloc[sp:].copy().reset_index(drop=True)
    train_df = trn_raw.copy()
    test_df = tst_raw.copy()
    tr_rm = 0
    te_rm = 0

    if len(train_df) < 100:
        return None, f"Only {len(train_df)} train rows after chop filter"
    if len(test_df) < 30:
        return None, f"Only {len(test_df)} test rows after chop filter"

    Xtr = train_df[active_fc].values.astype(np.float64)
    ytr = train_df["Target"].values.astype(int)
    Xte = test_df[active_fc].values.astype(np.float64)
    yte = test_df["Target"].values.astype(int)

    if len(np.unique(ytr)) < 2:
        return None, "Only one class in training data"

    st.info("🔮 Phase 1: Training draft model for SHAP analysis...")
    draft_model = build_xgb(n_est, max_d, lr_v)
    draft_model.fit(Xtr, ytr, eval_set=[(Xtr, ytr), (Xte, yte)], verbose=False)
    draft_train_pred = (draft_model.predict_proba(Xtr)[:, 1] >= thresh_v).astype(int)
    draft_train_wins = I(((draft_train_pred == 1) & (ytr == 1)).sum())
    draft_train_trades = I(draft_train_pred.sum())
    train_wr = (draft_train_wins / draft_train_trades * 100) if draft_train_trades > 0 else 0.0

    kept_features, pruned_features, shap_importance = shap_prune_features(draft_model, Xtr, active_fc, 0.25)
    if pruned_features:
        st.warning(f"✂️ SHAP Pruned {len(pruned_features)} features: {pruned_features}")
    else:
        st.info("ℹ️ No features pruned")

    kept_indices = [i for i, f in enumerate(active_fc) if f in kept_features]
    if len(kept_indices) < 5:
        kept_indices = list(range(len(active_fc)))
        kept_features = active_fc
        st.warning("⚠️ Too few features after pruning. Using all.")

    Xtr_p = Xtr[:, kept_indices]
    Xte_p = Xte[:, kept_indices]

    st.info(f"🚀 Phase 2: Training final model on {len(kept_features)}/{len(active_fc)} features...")
    model = build_xgb(n_est, max_d, lr_v)
    model.fit(Xtr_p, ytr, eval_set=[(Xtr_p, ytr), (Xte_p, yte)], verbose=False)

    y_prob = model.predict_proba(Xte_p)[:, 1]
    t_ret = test_df["Close"].pct_change().fillna(0).values
    best_th, thresh_df = opt_threshold(yte, y_prob, t_ret, ms=MIN_SIG)

    y_pred = (y_prob >= thresh_v).astype(int)
    trades = I(y_pred.sum())
    wins = I(((y_pred == 1) & (yte == 1)).sum())
    prec = F(precision_score(yte, y_pred, zero_division=0)) if trades > 0 else 0.0
    rec = F(recall_score(yte, y_pred, zero_division=0)) if trades > 0 else 0.0
    f1v = F(f1_score(yte, y_pred, zero_division=0)) if trades > 0 else 0.0
    test_wr = (wins / trades * 100) if trades > 0 else 0.0

    test_dirs = test_df["Signal_Dir"].values
    long_trades = I(((y_pred == 1) & (test_dirs == 1)).sum())
    short_trades = I(((y_pred == 1) & (test_dirs == -1)).sum())
    long_wins = I(((y_pred == 1) & (yte == 1) & (test_dirs == 1)).sum())
    short_wins = I(((y_pred == 1) & (yte == 1) & (test_dirs == -1)).sum())

    dir_mult = np.where(test_dirs == -1, -1.0, 1.0)
    s_ret = np.where(y_pred[:-1] == 1, t_ret[1:] * dir_mult[:-1], 0)
    s_ret = np.insert(s_ret, 0, 0)
    cum_s = (1 + pd.Series(s_ret)).cumprod()
    cum_b = (1 + pd.Series(t_ret)).cumprod()
    cs_f = F(cum_s.iloc[-1])
    cb_f = F(cum_b.iloc[-1])

    tpm = trades / (len(test_df) / (24 * 30)) if len(test_df) > 0 else 0
    avg_str, max_str = win_streak(y_pred, yte)
    kf = kelly(prec, rr)
    kpct = kf * 100
    exp = expectancy(prec, tp_m, sl_m)
    exp_d = exp * avg_atr
    atr_test = test_df["ATR_pct"].values

    (eq, final_bal, mdd, pf, gp, gl, bt_best, bt_worst,
     avg_sz, sniper_n, std_n, cautious_n, be_saves) = simulate_bidir(
        y_pred, yte, y_prob, atr_test, tp_m, sl_m, start_cap, fee_pct,
        use_trailing, trail_act, trail_dist, time_be,
        test_df["Close"].values if "Close" in test_df.columns else None,
        test_df["High"].values if "High" in test_df.columns else None,
        test_df["Low"].values if "Low" in test_df.columns else None,
        test_dirs,
    )

    importance = model.feature_importances_
    imp_n = [F(x) for x in importance]
    imp_sum = sum(imp_n)

    joblib.dump({
        "model": model, "feature_columns": kept_features,
        "all_original_features": active_fc, "pruned_features": pruned_features,
        "shap_importance": shap_importance,
        "atr_tp_mult": F(tp_m), "atr_sl_mult": F(sl_m),
        "window": I(win_sz), "best_threshold": F(thresh_v),
        "adx_filter": F(adx_f), "bb_squeeze_thresh": F(bb_sq),
        "strategy_type": "bidir_ensemble", "rsi_entry": rsi_e,
        "min_votes": min_votes, "momentum_logic": momentum_logic,
        "body_threshold": body_thresh, "wick_threshold": wick_thresh,
        "use_trailing_stop": use_trailing,
        "trail_activation": trail_act, "trail_distance": trail_dist,
        "trade_direction": "bidir",
        "max_hold_hours": max_hold, "time_be_hours": time_be,
        "trained_at": datetime.now().isoformat(),
        "version": "genesis_v26",
        "preset_name": p.get("name", "?"),
        "kelly_fraction": F(kf), "expectancy": F(exp),
        "final_balance": final_bal, "max_drawdown": mdd,
        "profit_factor": pf, "use_candle_physics": use_cp,
        "train_wr": train_wr, "test_wr": test_wr,
    }, MODEL_PATH)

    trs, tre = date_range_fn(train_df)
    tes, tee = date_range_fn(test_df)
    report = classification_report(yte, y_pred, target_names=["LOSS", "WIN"], zero_division=0)
    cm = confusion_matrix(yte, y_pred)
    mdf = monthly_bd(test_df, y_pred, yte)

    return {
        "model": model, "y_pred": y_pred, "y_prob": y_prob, "y_test": yte,
        "trades": trades, "wins": wins, "prec": prec, "rec": rec, "f1": f1v,
        "cum_s": cum_s, "cum_b": cum_b, "cs_f": cs_f, "cb_f": cb_f,
        "tpm": tpm, "avg_str": avg_str, "max_str": max_str,
        "kf": kf, "kpct": kpct, "exp": exp, "exp_d": exp_d,
        "eq": eq, "final_bal": final_bal, "mdd": mdd, "pf": pf,
        "gp": gp, "gl": gl, "bt_best": bt_best, "bt_worst": bt_worst,
        "imp_n": imp_n, "imp_sum": imp_sum,
        "be_wr": be_wr, "rr": rr, "tp_m": tp_m, "sl_m": sl_m,
        "train_df": train_df, "test_df": test_df,
        "tr_rm": tr_rm, "te_rm": te_rm,
        "trs": short_d(trs), "tre": short_d(tre),
        "tes": short_d(tes), "tee": short_d(tee),
        "thresh_v": thresh_v, "best_th": best_th, "thresh_df": thresh_df,
        "report": report, "cm": cm, "mdf": mdf, "avg_atr": avg_atr,
        "t_ret": t_ret, "rsi_e": rsi_e, "win_sz": win_sz,
        "active_fc": kept_features, "all_original_fc": active_fc,
        "pruned_features": pruned_features, "shap_importance": shap_importance,
        "strategy_type": "bidir_ensemble",
        "min_votes": min_votes, "use_trailing": use_trailing,
        "train_wr": train_wr, "test_wr": test_wr,
        "trade_direction": "bidir",
        "long_trades": long_trades, "short_trades": short_trades,
        "long_wins": long_wins, "short_wins": short_wins,
        "avg_size": avg_sz, "sniper_n": sniper_n,
        "standard_n": std_n, "cautious_n": cautious_n,
        "bb_squeeze_thresh": bb_sq, "n_chop_filtered": n_chop,
        "be_saves": be_saves,
        "max_hold_hours": max_hold, "time_be_hours": time_be,
    }, None

# ================================================================
# V26: LOSER'S AUTOPSY
# ================================================================
def _render_losers_autopsy(r):
    with st.expander("💀 Loser's Autopsy (Why trades failed)"):
        test_df = r["test_df"]
        y_pred = r["y_pred"]
        y_test = r["y_test"]
        loser_mask = (y_pred == 1) & (y_test == 0)
        n_losers = int(loser_mask.sum())
        if n_losers == 0:
            st.success("🎉 No losing trades found! Perfect run.")
            return
        st.warning(f"Found **{n_losers}** losing trades to analyze.")
        loser_df = test_df.loc[loser_mask].copy().reset_index(drop=True)

        # METRIC 1: Worst Day of Week
        st.markdown("#### 📅 Loss Distribution by Day of Week")
        if "Datetime" in loser_df.columns:
            try:
                dts = pd.to_datetime(loser_df["Datetime"], errors="coerce")
                valid_dts = dts.dropna()
                if len(valid_dts) > 0:
                    dow = valid_dts.dt.day_name()
                    dow_counts = dow.value_counts()
                    all_trade_mask = y_pred == 1
                    all_trade_df = test_df.loc[all_trade_mask].copy()
                    if "Datetime" in all_trade_df.columns:
                        all_dts = pd.to_datetime(all_trade_df["Datetime"], errors="coerce")
                        all_dow = all_dts.dropna().dt.day_name()
                        all_dow_counts = all_dow.value_counts()
                        loss_rate_by_day = {}
                        for day in dow_counts.index:
                            total_on_day = all_dow_counts.get(day, 0)
                            losses_on_day = dow_counts.get(day, 0)
                            rate = (losses_on_day / total_on_day * 100) if total_on_day > 0 else 0
                            loss_rate_by_day[day] = round(rate, 1)
                        day_df = pd.DataFrame([
                            {"Day": day, "Losses": int(dow_counts.get(day, 0)),
                             "Total Trades": int(all_dow_counts.get(day, 0)),
                             "Loss Rate %": loss_rate_by_day.get(day, 0)}
                            for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                            if day in dow_counts.index or day in all_dow_counts.index
                        ]).sort_values("Loss Rate %", ascending=False)
                        if len(day_df) > 0:
                            worst_day = day_df.iloc[0]["Day"]
                            worst_rate = day_df.iloc[0]["Loss Rate %"]
                            st.metric("☠️ Worst Day", worst_day, delta=f"{worst_rate:.0f}% loss rate", delta_color="inverse")
                            st.dataframe(day_df, use_container_width=True, hide_index=True)
                            fig_day = px.bar(day_df, x="Day", y="Loss Rate %", color="Loss Rate %",
                                             color_continuous_scale=["green", "yellow", "red"],
                                             title="Loss Rate by Day of Week")
                            st.plotly_chart(fig_day, use_container_width=True)
            except Exception as e:
                st.info(f"Day analysis unavailable: {e}")
        else:
            st.info("No Datetime column for day-of-week analysis.")

        st.markdown("---")

        # METRIC 2: Worst Hour
        st.markdown("#### ⏰ Loss Distribution by Hour")
        if "Hour_of_Day" in loser_df.columns:
            hours = loser_df["Hour_of_Day"].dropna().astype(int)
            if len(hours) > 0:
                hour_counts = hours.value_counts().sort_index()
                all_trade_hours = test_df.loc[y_pred == 1, "Hour_of_Day"].dropna().astype(int)
                all_hour_counts = all_trade_hours.value_counts()
                hour_rate = {}
                for hr in range(24):
                    total_hr = all_hour_counts.get(hr, 0)
                    loss_hr = hour_counts.get(hr, 0)
                    rate = (loss_hr / total_hr * 100) if total_hr > 0 else 0
                    hour_rate[hr] = round(rate, 1)
                hour_df = pd.DataFrame([
                    {"Hour (UTC)": hr, "Losses": int(hour_counts.get(hr, 0)),
                     "Total": int(all_hour_counts.get(hr, 0)),
                     "Loss Rate %": hour_rate[hr]}
                    for hr in sorted(hour_rate.keys()) if all_hour_counts.get(hr, 0) > 0
                ]).sort_values("Loss Rate %", ascending=False)
                if len(hour_df) > 0:
                    worst_hour = int(hour_df.iloc[0]["Hour (UTC)"])
                    worst_h_rate = hour_df.iloc[0]["Loss Rate %"]
                    st.metric("☠️ Worst Hour (UTC)", f"{worst_hour}:00",
                              delta=f"{worst_h_rate:.0f}% loss rate", delta_color="inverse")
                    fig_hour = px.bar(hour_df, x="Hour (UTC)", y="Loss Rate %", color="Loss Rate %",
                                      color_continuous_scale=["green", "yellow", "red"],
                                      title="Loss Rate by Hour (UTC)")
                    st.plotly_chart(fig_hour, use_container_width=True)

        st.markdown("---")

        # METRIC 3: Average ADX on Loss
        st.markdown("#### 📊 Trend Strength When Trades Failed")
        adx_col = "H4_ADX_14" if "H4_ADX_14" in loser_df.columns else (
            "ADX_14" if "ADX_14" in loser_df.columns else None)
        if adx_col:
            loser_adx = loser_df[adx_col].dropna()
            winner_mask = (y_pred == 1) & (y_test == 1)
            winner_df = test_df.loc[winner_mask]
            winner_adx = winner_df[adx_col].dropna() if adx_col in winner_df.columns else pd.Series()
            col_a, col_b = st.columns(2)
            avg_loss_adx = float(loser_adx.mean()) if len(loser_adx) > 0 else 0
            avg_win_adx = float(winner_adx.mean()) if len(winner_adx) > 0 else 0
            col_a.metric(f"📉 Avg {adx_col} on LOSS", f"{avg_loss_adx:.1f}")
            col_b.metric(f"📈 Avg {adx_col} on WIN", f"{avg_win_adx:.1f}")
            if avg_loss_adx < avg_win_adx:
                st.info(f"💡 Losses occur in WEAKER trends (ADX {avg_loss_adx:.0f} vs {avg_win_adx:.0f}). "
                        f"Consider raising your ADX filter above {avg_loss_adx:.0f}.")
            else:
                st.info("💡 Losses occur in similar or stronger trends. Issue may be timing.")
            if len(loser_adx) > 3 and len(winner_adx) > 3:
                fig_adx = go.Figure()
                fig_adx.add_trace(go.Histogram(x=loser_adx.values, name="Losing ADX", marker_color="red", opacity=0.6, nbinsx=20))
                fig_adx.add_trace(go.Histogram(x=winner_adx.values, name="Winning ADX", marker_color="green", opacity=0.6, nbinsx=20))
                fig_adx.update_layout(title=f"{adx_col} Distribution: Winners vs Losers", barmode="overlay", height=300)
                st.plotly_chart(fig_adx, use_container_width=True)

        # Confidence analysis on losers
        st.markdown("---")
        st.markdown("#### 🎯 AI Confidence on Losing Trades")
        y_prob_r = r.get("y_prob", None)
        if y_prob_r is not None:
            loser_probs = y_prob_r[loser_mask]
            winner_probs = y_prob_r[(y_pred == 1) & (y_test == 1)]
            if len(loser_probs) > 0:
                col_c, col_d = st.columns(2)
                col_c.metric("Avg Confidence (Losses)", f"{np.mean(loser_probs)*100:.1f}%")
                col_d.metric("Avg Confidence (Wins)",
                             f"{np.mean(winner_probs)*100:.1f}%" if len(winner_probs) > 0 else "N/A")

# ================================================================
# V26: TRADE REPLAY CANDLESTICK
# ================================================================
def _render_trade_replay_candlestick(r):
    st.markdown("### 🕯️ Trade Replay (Candlestick)")
    test_df = r["test_df"]
    y_pred = r["y_pred"]
    y_test = r["y_test"]
    n_bars = min(300, len(test_df))
    tail_df = test_df.iloc[-n_bars:].copy().reset_index(drop=True)
    tail_pred = y_pred[-n_bars:]
    tail_test = y_test[-n_bars:]
    tail_dirs = tail_df["Signal_Dir"].values if "Signal_Dir" in tail_df.columns else np.ones(n_bars)

    if "Datetime" in tail_df.columns:
        try:
            x_axis = pd.to_datetime(tail_df["Datetime"], errors="coerce").values
        except:
            x_axis = np.arange(n_bars)
    else:
        x_axis = np.arange(n_bars)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x_axis, open=tail_df["Open"].values, high=tail_df["High"].values,
        low=tail_df["Low"].values, close=tail_df["Close"].values,
        name="Price", increasing_line_color="#00b894", decreasing_line_color="#d63031",
        increasing_fillcolor="#00b894", decreasing_fillcolor="#d63031", opacity=0.7,
    ))

    bm = tail_pred == 1
    tc = tail_df["Close"].values
    if bm.any():
        lw_mask = bm & (tail_test == 1) & (tail_dirs == 1)
        if lw_mask.any():
            fig.add_trace(go.Scatter(x=x_axis[lw_mask], y=tc[lw_mask] * 0.998, mode="markers",
                                     name="🟢 Long Win", marker=dict(color="#00b894", size=14, symbol="triangle-up",
                                                                      line=dict(width=1, color="white"))))
        ll_mask = bm & (tail_test == 0) & (tail_dirs == 1)
        if ll_mask.any():
            fig.add_trace(go.Scatter(x=x_axis[ll_mask], y=tc[ll_mask] * 0.998, mode="markers",
                                     name="❌ Long Loss", marker=dict(color="lightgreen", size=10, symbol="x",
                                                                       line=dict(width=2, color="darkgreen"))))
        sw_mask = bm & (tail_test == 1) & (tail_dirs == -1)
        if sw_mask.any():
            fig.add_trace(go.Scatter(x=x_axis[sw_mask], y=tc[sw_mask] * 1.002, mode="markers",
                                     name="🔻 Short Win", marker=dict(color="#d63031", size=14, symbol="triangle-down",
                                                                       line=dict(width=1, color="white"))))
        sl_mask = bm & (tail_test == 0) & (tail_dirs == -1)
        if sl_mask.any():
            fig.add_trace(go.Scatter(x=x_axis[sl_mask], y=tc[sl_mask] * 1.002, mode="markers",
                                     name="❌ Short Loss", marker=dict(color="lightsalmon", size=10, symbol="x",
                                                                        line=dict(width=2, color="darkred"))))

    fig.update_layout(title=f"V26 Trade Replay — Last {n_bars} Bars", xaxis_title="Time",
                      yaxis_title="Price", height=500, xaxis_rangeslider_visible=False,
                      template="plotly_dark",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    st.plotly_chart(fig, use_container_width=True)

# ================================================================
# DISPLAY RESULTS
# ================================================================
def show_results(r, p, start_cap, fc):
    be_wr = r["be_wr"]
    rr = r["rr"]
    roi = (r["final_bal"] - start_cap) / start_cap * 100 if start_cap > 0 else 0
    net_profit = r["final_bal"] - start_cap
    active_fc = r.get("active_fc", fc)
    min_v = r.get("min_votes", 2)
    long_t = r.get("long_trades", 0)
    short_t = r.get("short_trades", 0)
    long_w = r.get("long_wins", 0)
    short_w = r.get("short_wins", 0)
    avg_sz = r.get("avg_size", 1.0)
    sniper_n = r.get("sniper_n", 0)
    standard_n = r.get("standard_n", 0)
    cautious_n = r.get("cautious_n", 0)
    n_chop = r.get("n_chop_filtered", 0)
    be_saves = r.get("be_saves", 0)

    st.markdown("---")
    if r["final_bal"] >= start_cap:
        st.markdown(
            f"""<div style="background:linear-gradient(135deg,#00b894,#00cec9);
            padding:30px;border-radius:15px;text-align:center;">
            <h1 style="color:white;margin:0;">🚀 BI-DIR SUCCESS</h1>
            <h2 style="color:white;margin:0;">${start_cap:,.0f} → ${r['final_bal']:,.2f}
            (+${net_profit:,.2f}, {roi:+.1f}%)</h2>
            <p style="color:white;font-size:16px;">
            🟢 {long_t}L ({long_w}W) | 🔴 {short_t}S ({short_w}W) | 🟣 {n_chop} Chop |
            ⏱️ BE Saves: {be_saves} | Avg Size: {avg_sz:.2f}x</p>
            </div>""", unsafe_allow_html=True)
    else:
        st.markdown(
            f"""<div style="background:linear-gradient(135deg,#d63031,#e17055);
            padding:30px;border-radius:15px;text-align:center;">
            <h1 style="color:white;margin:0;">📉 BI-DIR LOSS</h1>
            <h2 style="color:white;margin:0;">${start_cap:,.0f} → ${r['final_bal']:,.2f} ({roi:+.1f}%)</h2>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 🛡️ Anti-Cheat Monitor")
    anti_cheat_monitor(r.get("train_wr", 0), r.get("test_wr", 0))

    st.markdown("### 🎯 AI Confidence Sizing Breakdown")
    sz1, sz2, sz3, sz4 = st.columns(4)
    sz1.metric("🟣 Sniper (1.5x)", f"{sniper_n}", help="prob ≥ 0.85")
    sz2.metric("🔵 Standard (1.0x)", f"{standard_n}", help="0.70 ≤ prob < 0.85")
    sz3.metric("🟢 Cautious (0.5x)", f"{cautious_n}", help="prob < 0.70")
    sz4.metric("⏱️ BE Saves", f"{be_saves}", help="Trades saved by time-based breakeven")

    st.markdown("### 🔄 Direction Breakdown")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("🟢 Long Trades", long_t)
    d2.metric("🟢 Long Wins", long_w)
    d3.metric("🔴 Short Trades", short_t)
    d4.metric("🔴 Short Wins", short_w)

    pruned = r.get("pruned_features", [])
    if pruned:
        with st.expander(f"✂️ SHAP Pruned ({len(pruned)} removed)"):
            st.write(pruned)

    shap_imp = r.get("shap_importance", {})
    if shap_imp:
        si_df = pd.DataFrame([
            {"Feature": k, "SHAP": v}
            for k, v in sorted(shap_imp.items(), key=lambda x: x[1], reverse=True)
        ])
        si_df["Status"] = si_df["Feature"].apply(lambda x: "🗑️" if x in pruned else "✅")
        st.dataframe(si_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    if r["exp"] > 0:
        st.success(f"✅ POSITIVE EXPECTANCY: {r['exp']:.4f} ATR (~${r['exp_d']:.2f})")
    elif r["trades"] > 0:
        st.error(f"❌ NEGATIVE EXPECTANCY: {r['exp']:.4f}")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("🎯 WR", f"{r['prec'] * 100:.1f}%")
    m2.metric("⚖️ BE", f"{be_wr:.0f}%")
    m3.metric("💰 R/R", f"{rr:.2f}:1")
    m4.metric("🔢 Sig", f"{r['trades']:,}")
    m5.metric("✅ Win", f"{r['wins']}/{r['trades']}")
    m6.metric("🗳️ Votes", f"≥{min_v}")

    v1, v2, v3, v4 = st.columns(4)
    v1.metric("🚪 Thresh", f"{r['thresh_v']:.0%}")
    v2.metric("🎲 Kelly", f"{r['kpct']:.1f}%")
    v3.metric("📉 PF", f"{r['pf']:.2f}")
    v4.metric("📉 MDD", f"{r['mdd']:.1f}%")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("🏁 Final", f"${r['final_bal']:,.2f}", delta=f"{roi:+.1f}%")
    p2.metric("💵 Net", f"${net_profit:,.2f}")
    p3.metric("📈 Gross+", f"${r['gp']:,.2f}")
    p4.metric("📉 Gross-", f"${r['gl']:,.2f}")

    # Equity curve
    st.markdown("### 📈 Equity Curve")
    eq_arr = np.array(r["eq"])
    fig_eq = go.Figure()
    fig_eq.add_trace(go.Scatter(y=eq_arr, mode="lines", name="Equity",
                                line=dict(color="#00b894", width=2.5)))
    fig_eq.add_hline(y=start_cap, line_dash="dash", line_color="gray",
                     annotation_text=f"Start: ${start_cap:,.0f}")
    fig_eq.update_layout(title="Equity", yaxis_title="$", height=400,
                         yaxis=dict(tickformat="$,.0f"))
    st.plotly_chart(fig_eq, use_container_width=True)

    # V26: Candlestick Trade Replay
    _render_trade_replay_candlestick(r)

    # Strategy vs B&H
    st.markdown("### 🆚 Strategy vs Buy & Hold")
    fig_bt = go.Figure()
    fig_bt.add_trace(go.Scatter(y=r["cum_b"].values, mode="lines", name="B&H",
                                line=dict(color="blue", width=1.5)))
    fig_bt.add_trace(go.Scatter(y=r["cum_s"].values, mode="lines", name="V26 BiDir",
                                line=dict(color="green", width=2.5)))
    fig_bt.update_layout(title="V26 BiDir vs B&H", yaxis_title="$1 Growth", height=400)
    st.plotly_chart(fig_bt, use_container_width=True)

    # V26: Loser's Autopsy
    _render_losers_autopsy(r)

    with st.expander("📝 Classification Report"):
        st.code(r["report"])
        st.dataframe(pd.DataFrame(r["cm"], index=["Act LOSS", "Act WIN"],
                                  columns=["Pred HOLD", "Pred TRADE"]),
                     use_container_width=True)

    with st.expander("🗓️ Monthly Breakdown"):
        st.dataframe(r["mdf"], use_container_width=True, hide_index=True)

    with st.expander("🔍 Feature Importance"):
        fi_df = pd.DataFrame({
            "Feature": active_fc, "Importance": r["imp_n"],
            "Share(%)": [x / r["imp_sum"] * 100 if r["imp_sum"] > 0 else 0 for x in r["imp_n"]]
        }).sort_values("Importance", ascending=True)
        fi_df["Type"] = fi_df["Feature"].apply(
            lambda x: "🧬 H4" if x.startswith("H4_") else
            ("🔄 Dir" if x == "Signal_Dir" else
             ("🕯️ Phys" if x in CANDLE_PHYSICS else
              ("🐋 Liq" if "Rolling" in x else "📊 Tech"))))
        fig_fi = px.bar(fi_df, x="Importance", y="Feature", orientation="h", color="Type",
                        title="Feature Importance (Post-SHAP)", hover_data=["Share(%)"])
        fig_fi.update_layout(height=max(400, len(active_fc) * 22), yaxis_title="")
        st.plotly_chart(fig_fi, use_container_width=True)

# ================================================================
# VOTING SCORECARD (Live)
# ================================================================
def show_voting_scorecard(lat, params):
    adx_t = I(params.get("adx_filter", 20))
    bb_sq = F(params.get("bb_squeeze_thresh", 0.02))
    rsi_e = I(params.get("rsi_entry", 45))
    mom_logic = params.get("momentum_logic", "dip")
    body_t = F(params.get("body_threshold", 0.3))
    wick_t = F(params.get("wick_threshold", 0.2))
    min_votes = I(params.get("min_votes", 2))

    close_val = F(lat.get("Close", 0))
    ema200 = F(lat.get("EMA_200", 0))
    adx_val = F(lat.get("ADX_14", 0))
    bbw_val = F(lat.get("Bband_Width", 0))
    rsi_val = F(lat.get("RSI_14", 50))
    body_val = F(lat.get("Body_Size", 0))

    is_chop = (adx_val < adx_t) or (bbw_val < bb_sq)
    if is_chop:
        regime = "CHOP"; regime_color = "#636e72"
        vote1 = vote2 = vote3 = 0; total = 0
        action = "NO TRADE"; action_color = "#636e72"
        v1_label, v2_label, v3_label = "Trend", "Momentum", "Pattern"
        v1_desc = f"ADX({adx_val:.0f})<{adx_t} or BBW({bbw_val:.3f})<{bb_sq}"
        v2_desc = v3_desc = "Chop zone"
    elif close_val > ema200 and ema200 > 0:
        regime = "🟢 BULL"; regime_color = "#00b894"; vote1 = 1
        v1_label = "Trend ⬆"; v1_desc = f"Close({close_val:.0f}) > EMA200({ema200:.0f})"
        if mom_logic == "dip":
            vote2 = 1 if rsi_val < rsi_e else 0; v2_desc = f"RSI({rsi_val:.0f}) < {rsi_e}"
        else:
            vote2 = 1 if rsi_val > rsi_e else 0; v2_desc = f"RSI({rsi_val:.0f}) > {rsi_e}"
        v2_label = "Momentum ⬆"
        lw = F(lat.get("Lower_Wick", 0))
        vote3 = 1 if body_val > body_t and lw > wick_t else 0
        v3_label = "Pattern ⬆"; v3_desc = f"Body({body_val:.2f})>{body_t:.2f} & LW({lw:.2f})>{wick_t:.2f}"
        total = vote1 + vote2 + vote3
        action = "BUY" if total >= min_votes else "HOLD"
        action_color = "#00b894" if action == "BUY" else "#636e72"
    elif close_val < ema200 and ema200 > 0:
        regime = "🔴 BEAR"; regime_color = "#d63031"; vote1 = 1
        v1_label = "Trend ⬇"; v1_desc = f"Close({close_val:.0f}) < EMA200({ema200:.0f})"
        if mom_logic == "dip":
            vote2 = 1 if rsi_val > rsi_e else 0; v2_desc = f"RSI({rsi_val:.0f}) > {rsi_e} (overbought)"
        else:
            vote2 = 1 if rsi_val < rsi_e else 0; v2_desc = f"RSI({rsi_val:.0f}) < {rsi_e} (breakdown)"
        v2_label = "Momentum ⬇"
        uw = F(lat.get("Upper_Wick", 0))
        vote3 = 1 if body_val > body_t and uw > wick_t else 0
        v3_label = "Pattern ⬇"; v3_desc = f"Body({body_val:.2f})>{body_t:.2f} & UW({uw:.2f})>{wick_t:.2f}"
        total = vote1 + vote2 + vote3
        action = "SELL" if total >= min_votes else "HOLD"
        action_color = "#d63031" if action == "SELL" else "#636e72"
    else:
        regime = "NEUTRAL"; regime_color = "#636e72"
        vote1 = vote2 = vote3 = 0; total = 0; action = "HOLD"; action_color = "#636e72"
        v1_label, v2_label, v3_label = "Trend", "Momentum", "Pattern"
        v1_desc = v2_desc = v3_desc = "Neutral"

    st.markdown(
        f"""<div style="background:linear-gradient(135deg,#2d3436,#636e72);
        padding:20px;border-radius:15px;margin:10px 0;">
        <h3 style="color:white;text-align:center;margin:0 0 5px 0;">V26 Bi-Dir Scorecard – {regime}</h3>
        <p style="color:#b2bec3;text-align:center;margin:0 0 15px 0;">Chop Filter: ADX={adx_val:.0f} BBW={bbw_val:.4f}</p>
        <div style="display:flex;justify-content:space-around;text-align:center;">
        <div><p style="color:{'#00b894' if vote1 else '#d63031'};font-size:36px;margin:0;">{'YES' if vote1 else 'NO'}</p>
        <p style="color:white;margin:0;font-weight:bold;">{v1_label}</p><p style="color:#b2bec3;font-size:11px;margin:0;">{v1_desc}</p></div>
        <div><p style="color:{'#00b894' if vote2 else '#d63031'};font-size:36px;margin:0;">{'YES' if vote2 else 'NO'}</p>
        <p style="color:white;margin:0;font-weight:bold;">{v2_label}</p><p style="color:#b2bec3;font-size:11px;margin:0;">{v2_desc}</p></div>
        <div><p style="color:{'#00b894' if vote3 else '#d63031'};font-size:36px;margin:0;">{'YES' if vote3 else 'NO'}</p>
        <p style="color:white;margin:0;font-weight:bold;">{v3_label}</p><p style="color:#b2bec3;font-size:11px;margin:0;">{v3_desc}</p></div>
        </div>
        <div style="text-align:center;margin-top:15px;padding:10px;background:{action_color};border-radius:10px;">
        <h2 style="color:white;margin:0;">Votes: {total}/3 → {action}</h2>
        <p style="color:white;margin:0;">Required: ≥{min_votes} | Regime: {regime}</p></div>
        </div>""", unsafe_allow_html=True)
    return total, action

# ================================================================
# HELPER: Process dual uploads
# ================================================================
def process_dual_uploads(up_h1, up_h4, data_regime):
    raw_h1, _ = load_data(up_h1)
    if "Close" not in raw_h1.columns:
        st.error("H1 CSV: No Close column."); st.stop()
    raw_h1 = parse_dates(raw_h1)
    orig_h1 = len(raw_h1)
    if orig_h1 > data_regime:
        raw_h1 = raw_h1.tail(data_regime).reset_index(drop=True)

    raw_h4, _ = load_data(up_h4)
    if "Close" not in raw_h4.columns:
        st.error("H4 CSV: No Close column."); st.stop()
    raw_h4 = parse_dates(raw_h4)
    orig_h4 = len(raw_h4)
    if orig_h4 > data_regime:
        raw_h4 = raw_h4.tail(data_regime).reset_index(drop=True)

    st.success(f"H1: {orig_h1:,} rows | H4: {orig_h4:,} rows")
    return raw_h1, raw_h4

# ================================================================
# INFINITE MINER V26
# ================================================================
def run_infinite_miner_v26(
    df_feat, fc, mine_capital, mine_fee,
    use_tgt_bal, tgt_bal, use_min_wr, min_wr,
    use_min_pf, min_pf, use_min_trades, min_trades_cond,
    any_cond, max_trials, asset_class,
    prog, log_container, best_box, chart_box,
):
    if asset_class == "crypto":
        tp_range, sl_range = (0.5, 5.0), (0.3, 3.0)
    else:
        tp_range, sl_range = (0.3, 2.5), (0.2, 1.5)

    asset_name = "BTC" if asset_class == "crypto" else "GOLD"
    state = {"best_balance": 0.0, "best_trial_data": None,
             "mining_success": False, "success_trial": None}
    trial_log = []

    def check_all(r):
        met = True
        if use_min_trades and r["signals"] < min_trades_cond: met = False
        if use_tgt_bal and r["final_balance"] < tgt_bal: met = False
        if use_min_wr and r["win_rate"] < min_wr: met = False
        if use_min_pf and r["profit_factor"] < min_pf: met = False
        if not any_cond: met = False
        return met

    def objective(trial):
        strategy_params = {
            "tp_mult": trial.suggest_float("tp_mult", tp_range[0], tp_range[1], step=0.1),
            "sl_mult": trial.suggest_float("sl_mult", sl_range[0], sl_range[1], step=0.1),
            "rsi_entry": trial.suggest_int("rsi_entry", 20, 70, step=5),
            "adx_filter": trial.suggest_int("adx_filter", 10, 40, step=5),
            "bb_squeeze_thresh": trial.suggest_float("bb_squeeze_thresh", 0.01, 0.05, step=0.005),
            "min_votes": trial.suggest_int("min_votes", 1, 3),
            "momentum_logic": trial.suggest_categorical("momentum_logic", ["dip", "breakout"]),
            "body_threshold": trial.suggest_float("body_threshold", 0.1, 0.6, step=0.05),
            "wick_threshold": trial.suggest_float("wick_threshold", 0.05, 0.4, step=0.05),
            "window": trial.suggest_int("window", 4, 24, step=2),
            "n_estimators": trial.suggest_int("n_estimators", 200, 1500, step=100),
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.005, 0.05, step=0.005),
            "threshold": trial.suggest_float("threshold", 0.40, 0.75, step=0.05),
            "use_candle_physics": trial.suggest_categorical("use_candle_physics", [True, False]),
            "use_trailing_stop": trial.suggest_categorical("use_trailing_stop", [True, False]),
            "trail_activation": trial.suggest_float("trail_activation", 0.3, 1.0, step=0.1),
            "trail_distance": trial.suggest_float("trail_distance", 0.5, 2.0, step=0.1),
            "trade_direction": "bidir",
            # V26
            "max_hold_hours": trial.suggest_int("max_hold_hours", 8, 48, step=4),
            "time_be_hours": trial.suggest_int("time_be_hours", 4, 24, step=2),
        }
        r = run_trial_v26(df_feat, fc, strategy_params, mine_capital, mine_fee)
        tn = trial.number + 1
        is_valid = r["score"] > PENALTY_SCORE
        all_met = check_all(r) if is_valid else False

        entry = {
            "Trial": tn, "🟢L": r.get("long_signals", 0), "🔴S": r.get("short_signals", 0),
            "Votes": strategy_params["min_votes"], "Mom": strategy_params["momentum_logic"][:3],
            "TP": strategy_params["tp_mult"], "SL": strategy_params["sl_mult"],
            "MaxH": strategy_params["max_hold_hours"], "TimeBE": strategy_params["time_be_hours"],
            "BBsq": round(strategy_params["bb_squeeze_thresh"], 3),
            "Trail": "Y" if strategy_params["use_trailing_stop"] else "N",
            "Thresh": strategy_params["threshold"], "Balance": r["final_balance"],
            "WR%": r["win_rate"], "Trades": r["signals"], "PF": r["profit_factor"],
            "BeSaves": r.get("be_saves", 0), "Score": r["score"],
            "Status": "+" if r["final_balance"] > mine_capital else ("-" if is_valid else "x"),
        }
        trial_log.append(entry)
        st.session_state["miner_trial_log"] = trial_log
        pct = min(int(5 + (tn / max_trials) * 90), 95)
        prog.progress(pct, f"Trial {tn}/{max_trials}")
        with log_container:
            st.dataframe(pd.DataFrame(trial_log[-20:]), use_container_width=True, hide_index=True)

        if is_valid:
            safe_trades = r["signals"] >= max(
                min_trades_cond if use_min_trades else MIN_TRADES_HARD, MIN_TRADES_HARD)
            if r["final_balance"] > state["best_balance"] and safe_trades:
                state["best_balance"] = r["final_balance"]
                state["best_trial_data"] = {
                    "name": f"V26_{asset_name}_BiDir_{datetime.now().strftime('%m%d_%H%M')}_{tn}",
                    **strategy_params, "strategy_type": "bidir_ensemble",
                    "score": round(r["score"], 4), "win_rate": r["win_rate"],
                    "total_profit": r["total_profit"], "signals": r["signals"],
                    "final_balance": r["final_balance"], "profit_factor": r["profit_factor"],
                    "long_signals": r.get("long_signals", 0), "short_signals": r.get("short_signals", 0),
                    "be_saves": r.get("be_saves", 0),
                    "created_at": datetime.now().isoformat(),
                    "asset_class": asset_class, "asset_name": asset_name,
                }
                st.session_state["miner_best_params"] = copy.deepcopy(state["best_trial_data"])
                st.session_state["miner_best_balance"] = r["final_balance"]
                save_to_bank(state["best_trial_data"], r["final_balance"], r["win_rate"], asset_name)
                with best_box:
                    st.markdown(
                        f"""<div style="background:linear-gradient(135deg,#6c5ce7,#a29bfe);padding:15px;border-radius:10px;">
                        <h3 style="color:white;margin:0;">Best (Trial #{tn})</h3>
                        <p style="color:white;font-size:16px;">Bal: <b>${r['final_balance']:,.2f}</b> |
                        WR: <b>{r['win_rate']:.1f}%</b> | ⏱️BE:{r.get('be_saves',0)} |
                        🟢{r.get('long_signals',0)}L 🔴{r.get('short_signals',0)}S</p></div>""",
                        unsafe_allow_html=True)

            if len(trial_log) > 1 and tn % 5 == 0:
                with chart_box:
                    valid_trials = [t for t in trial_log if t["Score"] > PENALTY_SCORE]
                    if valid_trials:
                        fig = go.Figure()
                        greens = [t for t in valid_trials if t["Balance"] > mine_capital]
                        reds = [t for t in valid_trials if t["Balance"] <= mine_capital]
                        if greens:
                            fig.add_trace(go.Scatter(x=[t["Trial"] for t in greens], y=[t["Balance"] for t in greens],
                                                     mode="markers", name="Profit", marker=dict(color="green", size=8)))
                        if reds:
                            fig.add_trace(go.Scatter(x=[t["Trial"] for t in reds], y=[t["Balance"] for t in reds],
                                                     mode="markers", name="Loss", marker=dict(color="red", size=8)))
                        bsf_v, bsf = [], mine_capital
                        for t in trial_log:
                            if t["Score"] > PENALTY_SCORE and t["Trades"] >= MIN_TRADES_HARD:
                                bsf = max(bsf, t["Balance"])
                            bsf_v.append(bsf)
                        fig.add_trace(go.Scatter(x=list(range(1, len(trial_log) + 1)), y=bsf_v,
                                                 mode="lines", name="Best",
                                                 line=dict(color="#6c5ce7", width=3, dash="dash")))
                        if use_tgt_bal:
                            fig.add_hline(y=tgt_bal, line_dash="dot", line_color="gold",
                                          annotation_text=f"Target: ${tgt_bal:,.0f}")
                        fig.add_hline(y=mine_capital, line_dash="dash", line_color="gray")
                        fig.update_layout(title="Mining Progress", xaxis_title="Trial",
                                          yaxis_title="Balance ($)", height=350,
                                          yaxis=dict(tickformat="$,.0f"))
                        st.plotly_chart(fig, use_container_width=True)

        if all_met:
            state["mining_success"] = True; state["success_trial"] = entry
            trial.study.stop()
        return r["score"]

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=int(max_trials), show_progress_bar=False)
    return state, trial_log

# ================================================================
# SIDEBAR
# ================================================================
st.sidebar.title("GENESIS V26")
st.sidebar.header("Asset Class")
asset_class = st.sidebar.radio("Select Asset Class", ["Crypto (BTC)", "Forex/Metal (Gold)"],
                               index=0, key="asset_class_radio")
asset_class_key = "crypto" if "Crypto" in asset_class else "gold"

st.sidebar.header("Presets")
all_presets = preset_names()
sel_name = st.sidebar.selectbox("Active Preset", all_presets, index=0)
active_p = get_preset(sel_name)
with st.sidebar.expander("Details"):
    st.json({k: v for k, v in active_p.items() if k != "name"})

st.sidebar.markdown("---")
st.sidebar.header("Strategy Bank")
saved_files = list_saved()
if saved_files:
    disp = [os.path.basename(f) for f in saved_files]
    bank_sel = st.sidebar.selectbox("Load Saved", ["-"] + disp)
    if bank_sel != "-":
        idx = disp.index(bank_sel)
        loaded = load_from_bank(saved_files[idx])
        if loaded:
            if st.sidebar.button(f"Import '{bank_sel}'"):
                ln = loaded.get("name", bank_sel.replace(".json", ""))
                loaded["name"] = ln
                upsert_preset(loaded)
                st.sidebar.success("Imported"); st.rerun()
else:
    st.sidebar.info("No saved strategies yet.")

st.sidebar.markdown("---")
st.sidebar.header("Secrets Manager")
secrets = load_secrets()
with st.sidebar.expander("API Keys"):
    oanda_id = st.text_input("OANDA ID", value=secrets.get("oanda_id", ""), key="sec_oa_id")
    oanda_token = st.text_input("OANDA Token", value=secrets.get("oanda_token", ""),
                                type="password", key="sec_oa_tok")
    if st.button("Save Keys", key="save_keys"):
        save_secrets({"oanda_id": oanda_id, "oanda_token": oanda_token})
        st.success("Saved")

st.sidebar.markdown("---")
st.sidebar.header("Portfolio")
exchange = st.sidebar.selectbox("Exchange", ["Kraken", "Coinbase"])
start_cap = st.sidebar.number_input("Capital ($)", 100, 1000000, 1000, 100)
fee_pct = st.sidebar.number_input("Fee (%)", 0.0, 1.0, 0.1, 0.01)
data_regime = st.sidebar.slider("Data Regime", 5000, 100000, 35000, 5000)

st.sidebar.markdown("---")
if len(all_presets) > 1:
    del_n = st.sidebar.selectbox("Delete", ["-"] + [n for n in all_presets if n != "Default_V26"])
    if del_n != "-":
        if st.sidebar.button(f"Delete '{del_n}'"):
            delete_preset(del_n); st.rerun()

# ================================================================
# MAIN
# ================================================================
st.title("GENESIS V26 — Bi-Directional Hedge Fund Engine")
st.caption(f"Asset: **{asset_class}** | BiDir + Chop + Time-Stop + Liquidity Sweeps + AI Sizing + SHAP")

tab_mine, tab_bt, tab_live, tab_concept = st.tabs([
    "⚒️ Infinite Miner", "💾 Backtest", "📡 Live Signals", "🧠 Concept Playbook"])

# ================================================================
# TAB 1: INFINITE MINER
# ================================================================
with tab_mine:
    st.header("V26 Bi-Directional Miner")
    if not HAS_OPTUNA:
        st.error("pip install optuna required!")
    else:
        st.markdown("""**V26 Upgrades:** 🧬 BiDir + ⛔ Chop + ⏱️ Time-Stop + 🐋 Liquidity Sweeps + 🎯 AI Sizing""")
        s1, s2 = st.columns(2)
        with s1: mine_cap = st.number_input("Start Capital ($)", 100, 1000000, 1000, 100, key="mc")
        with s2: mine_fee = st.number_input("Fee (%)", 0.0, 1.0, 0.1, 0.01, key="mf")

        st.markdown("### Stop Conditions")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            use_bal = st.checkbox("Balance >=", value=True)
            tgt_bal = st.number_input("$", 100, 10000000, 2000, 100, disabled=not use_bal, key="tb")
        with c2:
            use_wr = st.checkbox("Win Rate >=", value=False)
            min_wr = st.number_input("%", 0.0, 100.0, 50.0, 1.0, disabled=not use_wr, key="mw")
        with c3:
            use_pf = st.checkbox("PF >=", value=False)
            min_pf = st.number_input("PF", 0.0, 100.0, 1.5, 0.1, disabled=not use_pf, key="mp")
        with c4:
            use_mt = st.checkbox("Trades >=", value=True)
            min_trd = st.number_input("Trades", 5, 10000, 30, 5, disabled=not use_mt, key="mt")

        any_cond = use_bal or use_wr or use_pf or use_mt
        if not any_cond: st.warning("No conditions set.")
        max_trials = st.number_input("Max Trials", 10, 100000, 500, 50, key="mx")

        st.markdown("---")
        st.markdown("### Dual Timeframe Upload")
        col_up1, col_up2 = st.columns(2)
        with col_up1: up_h1_mine = st.file_uploader("H1 CSV", type=["csv", "txt"], key="csv_m_h1")
        with col_up2: up_h4_mine = st.file_uploader("H4 CSV", type=["csv", "txt"], key="csv_m_h4")

        if up_h1_mine is not None and up_h4_mine is not None:
            raw_h1, raw_h4 = process_dual_uploads(up_h1_mine, up_h4_mine, data_regime)
            if st.button("🧬 Start Bi-Dir Mining", type="primary", use_container_width=True):
                st.session_state["miner_best_params"] = None
                st.session_state["miner_best_balance"] = 0.0
                st.session_state["miner_done"] = False
                st.session_state["miner_trial_log"] = []
                prog = st.progress(0, "Computing features...")
                try: df_feat = calc_features(raw_h1, raw_h4)
                except Exception as e:
                    st.error(f"Feature error: {e}"); st.code(traceback.format_exc()); st.stop()
                fc = FEATURES_V26
                prog.progress(5, "Mining BiDir...")
                log_container = st.empty(); best_box = st.empty(); chart_box = st.empty()
                state, trial_log = run_infinite_miner_v26(
                    df_feat, fc, mine_cap, mine_fee, use_bal, tgt_bal, use_wr, min_wr,
                    use_pf, min_pf, use_mt, min_trd, any_cond, max_trials, asset_class_key,
                    prog, log_container, best_box, chart_box)
                prog.progress(95, "Complete!")
                st.session_state["miner_done"] = True
                st.markdown("---")
                btd = st.session_state.get("miner_best_params")
                if btd:
                    st.markdown("### Best Strategy")
                    b1, b2, b3, b4, b5 = st.columns(5)
                    b1.metric("Votes≥", btd.get("min_votes", 2))
                    b2.metric("TP", f"{btd.get('tp_mult', 1.5)}x")
                    b3.metric("SL", f"{btd.get('sl_mult', 1.0)}x")
                    b4.metric("MaxH", f"{btd.get('max_hold_hours', 24)}h")
                    b5.metric("TimeBE", f"{btd.get('time_be_hours', 12)}h")
                    st.markdown("---")
                    prog.progress(96, "Backtesting best...")
                    result, err = full_backtest(df_feat, fc, btd, mine_cap, mine_fee)
                    if err: st.error(f"Backtest: {err}")
                    else: show_results(result, btd, mine_cap, fc)
                    prog.progress(100, "Done!")
                    st.markdown("---")
                    st.markdown("### All Trials")
                    adf = pd.DataFrame(trial_log).sort_values("Score", ascending=False)
                    st.dataframe(adf, use_container_width=True, hide_index=True)
                    st.download_button("Download CSV", data=adf.to_csv(index=False),
                                       file_name=f"v26_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                       mime="text/csv", use_container_width=True)
        elif up_h1_mine is not None or up_h4_mine is not None:
            st.warning("Upload BOTH H1 and H4 CSV files.")
        else:
            st.info("Upload H1 + H4 CSV files to start.")

        # Save best
        best_params = st.session_state.get("miner_best_params")
        if best_params is not None:
            st.markdown("---")
            st.markdown("### Save Best")
            best_bal = st.session_state.get("miner_best_balance", 0.0)
            asset_name = best_params.get("asset_name", "BTC")
            default_name = f"{asset_name}_BiDir_{datetime.now().strftime('%m%d_%H%M')}"
            save_name = st.text_input("Name", value=default_name, key="miner_save_name")
            if st.button("Save as Preset", type="primary", use_container_width=True, key="save_best"):
                if save_name.strip():
                    ps = copy.deepcopy(best_params); ps["name"] = save_name.strip()
                    upsert_preset(ps); st.success(f"'{save_name.strip()}' saved!"); st.balloons()
                else: st.error("Enter a name.")

# ================================================================
# TAB 2: BACKTEST
# ================================================================
with tab_bt:
    st.header("Backtest — V26 Bi-Directional")
    p = active_p
    tp_m = F(p.get("tp_mult", 1.5)); sl_m = F(p.get("sl_mult", 1.0))
    rr = tp_m / sl_m if sl_m > 0 else 1.0
    st.info(f"Preset: **{p.get('name','?')}** | TP={tp_m}x SL={sl_m}x R/R={rr:.2f}:1 | "
            f"MaxHold={I(p.get('max_hold_hours',24))}h TimeBE={I(p.get('time_be_hours',12))}h")

    st.markdown("### Dual Timeframe Upload")
    col_bt1, col_bt2 = st.columns(2)
    with col_bt1: up_h1_bt = st.file_uploader("H1 CSV", type=["csv", "txt"], key="csv_bt_h1")
    with col_bt2: up_h4_bt = st.file_uploader("H4 CSV", type=["csv", "txt"], key="csv_bt_h4")

    if up_h1_bt is not None and up_h4_bt is not None:
        raw_h1, raw_h4 = process_dual_uploads(up_h1_bt, up_h4_bt, data_regime)
        if st.button("Run Backtest", type="primary", use_container_width=True):
            prog = st.progress(0, "Computing features...")
            try: df = calc_features(raw_h1, raw_h4)
            except Exception as e:
                st.error(f"Feature error: {e}"); st.code(traceback.format_exc()); st.stop()
            prog.progress(30, "Backtesting BiDir...")
            result, err = full_backtest(df, FEATURES_V26, p, start_cap, fee_pct)
            prog.progress(90, "Rendering...")
            if err: st.error(f"Backtest: {err}")
            else: st.success("Model saved"); show_results(result, p, start_cap, FEATURES_V26)
            prog.progress(100, "Done!")
    elif up_h1_bt is not None or up_h4_bt is not None:
        st.warning("Upload BOTH CSVs.")
    else:
        st.info("Upload H1 + H4 CSV files.")

# ================================================================
# TAB 3: LIVE SIGNALS
# ================================================================
with tab_live:
    st.header("Live — V26 Bi-Directional")
    p = active_p
    tp_l = F(p.get("tp_mult", 1.5)); sl_l = F(p.get("sl_mult", 1.0))
    rr_l = tp_l / sl_l if sl_l > 0 else 1.0

    if asset_class_key == "crypto":
        st.markdown(f"**Crypto** | Exchange: **{exchange}** | BiDir | R/R: **{rr_l:.2f}:1**")
        data_source = "ccxt"
    else:
        st.markdown(f"**Gold/Forex** | BiDir | R/R: **{rr_l:.2f}:1**")
        gold_source = st.radio("Source", ["OANDA API", "Manual OHLC"], key="gold_src")
        data_source = "oanda" if gold_source == "OANDA API" else "manual"

    if not os.path.exists(MODEL_PATH):
        st.error("No Model! Run Backtest or Miner first.")
    else:
        try:
            si = joblib.load(MODEL_PATH)
            st.success(f"Model V:{si.get('version','?')} | BiDir | PF:{si.get('profit_factor','?')}")
        except:
            st.success("Model loaded")

        if data_source == "ccxt":
            if st.button("Get V26 Signal", type="primary", use_container_width=True):
                with st.spinner(f"Connecting to {exchange}..."):
                    try:
                        ex = (ccxt.kraken({"enableRateLimit": True, "timeout": 30000})
                              if exchange == "Kraken"
                              else ccxt.coinbase({"enableRateLimit": True, "timeout": 30000}))
                        ohlcv = ex.fetch_ohlcv("BTC/USD", timeframe="1h", limit=300)
                        if not ohlcv: st.error("No data."); st.stop()
                        ldf = pd.DataFrame(ohlcv, columns=["Timestamp", "Open", "High", "Low", "Close", "Volume"])
                        ldf["Datetime"] = pd.to_datetime(ldf["Timestamp"], unit="ms")
                        ldf = ldf.sort_values("Timestamp").reset_index(drop=True)
                        price = F(ldf["Close"].iloc[-1])
                        lf = calc_features(ldf, None)
                        saved = joblib.load(MODEL_PATH)
                        sig_dir = compute_bidir_signals(
                            lf, I(saved.get("adx_filter", 20)), F(saved.get("bb_squeeze_thresh", 0.02)),
                            I(saved.get("rsi_entry", 45)), saved.get("momentum_logic", "dip"),
                            F(saved.get("body_threshold", 0.3)), F(saved.get("wick_threshold", 0.2)),
                            I(saved.get("min_votes", 2)))
                        lf["Signal_Dir"] = sig_dir; lat = lf.iloc[-1]
                        mdl = saved["model"]; fcols = saved["feature_columns"]
                        live_th = F(saved.get("best_threshold", 0.55))
                        xv = np.array([F(lat.get(f, 0)) for f in fcols], dtype=np.float64).reshape(1, -1)
                        prob = F(mdl.predict_proba(xv)[0][1]); conf = prob * 100
                        lat_dict = {col: F(lat.get(col, 0)) for col in lf.columns}
                        lat_dict["Close"] = price
                        total_votes, action = show_voting_scorecard(lat_dict, saved)
                        model_trigger = prob >= live_th and action not in ("HOLD", "NO TRADE")
                        live_dir = F(lat.get("Signal_Dir", 0)); atr_pv = F(lat.get("ATR_pct", 0))
                        atr_d = price * atr_pv
                        if live_dir == -1: tp_p = price - tp_l * atr_d; sl_p = price + sl_l * atr_d; sig_word = "SELL"
                        else: tp_p = price + tp_l * atr_d; sl_p = price - sl_l * atr_d; sig_word = "BUY"
                        if prob >= 0.85: tier = "🟣 Sniper (1.5x)"
                        elif prob >= 0.70: tier = "🔵 Standard (1.0x)"
                        else: tier = "🟢 Cautious (0.5x)"
                        c1, c2, c3, c4 = st.columns(4)
                        c1.metric("BTC/USD", f"${price:,.2f}"); c2.metric("XGB Conf", f"{conf:.1f}%")
                        c3.metric("Signal", sig_word if model_trigger else "HOLD"); c4.metric("Sizing", tier)
                        if model_trigger:
                            sig_color = "#00b09b" if action == "BUY" else "#d63031"
                            st.markdown(f"""<div style="background:linear-gradient(135deg,{sig_color},#96c93d);
                            padding:30px;border-radius:15px;text-align:center;">
                            <h1 style="color:white;">{sig_word}</h1>
                            <p style="color:white;">TP: ${tp_p:,.2f} | SL: ${sl_p:,.2f} | {tier}</p>
                            </div>""", unsafe_allow_html=True)
                        else:
                            st.markdown(f"""<div style="background:linear-gradient(135deg,#636e72,#b2bec3);
                            padding:30px;border-radius:15px;text-align:center;">
                            <h1 style="color:white;">HOLD</h1></div>""", unsafe_allow_html=True)
                    except ccxt.NetworkError as e: st.error(f"Network: {e}")
                    except ccxt.ExchangeError as e: st.error(f"Exchange: {e}")
                    except Exception as e: st.error(f"{type(e).__name__}: {e}"); st.code(traceback.format_exc())

        elif data_source == "oanda":
            st.markdown("### OANDA API")
            secrets = load_secrets()
            oa_id = st.text_input("Account ID", value=secrets.get("oanda_id", ""), key="oa_id_live")
            oa_token = st.text_input("API Token", value=secrets.get("oanda_token", ""),
                                     type="password", key="oa_tok_live")
            oa_env = st.selectbox("Environment", ["practice", "live"], key="oa_env")
            if st.button("Get Gold Signal", type="primary", use_container_width=True):
                if not oa_id or not oa_token: st.error("Enter OANDA credentials.")
                elif not HAS_REQUESTS: st.error("pip install requests")
                else:
                    with st.spinner("Connecting to OANDA..."):
                        try:
                            base_url = "https://api-fxpractice.oanda.com" if oa_env == "practice" else "https://api-fxtrade.oanda.com"
                            url = f"{base_url}/v3/instruments/XAU_USD/candles"
                            headers = {"Authorization": f"Bearer {oa_token}"}
                            oa_params = {"count": "300", "granularity": "H1", "price": "M"}
                            resp = req_lib.get(url, headers=headers, params=oa_params, timeout=30)
                            if resp.status_code != 200: st.error(f"OANDA Error {resp.status_code}"); st.stop()
                            data = resp.json(); rows = []
                            for cd in data.get("candles", []):
                                mid = cd.get("mid", {})
                                rows.append({"Datetime": cd.get("time", ""), "Open": float(mid.get("o", 0)),
                                             "High": float(mid.get("h", 0)), "Low": float(mid.get("l", 0)),
                                             "Close": float(mid.get("c", 0)), "Volume": int(cd.get("volume", 0))})
                            ldf = pd.DataFrame(rows)
                            ldf["Datetime"] = pd.to_datetime(ldf["Datetime"], errors="coerce")
                            ldf = ldf.sort_values("Datetime").reset_index(drop=True)
                            price = F(ldf["Close"].iloc[-1])
                            lf = calc_features(ldf, None)
                            saved = joblib.load(MODEL_PATH)
                            sig_dir = compute_bidir_signals(
                                lf, I(saved.get("adx_filter", 20)), F(saved.get("bb_squeeze_thresh", 0.02)),
                                I(saved.get("rsi_entry", 45)), saved.get("momentum_logic", "dip"),
                                F(saved.get("body_threshold", 0.3)), F(saved.get("wick_threshold", 0.2)),
                                I(saved.get("min_votes", 2)))
                            lf["Signal_Dir"] = sig_dir; lat = lf.iloc[-1]
                            mdl = saved["model"]; fcols = saved["feature_columns"]
                            live_th = F(saved.get("best_threshold", 0.55))
                            xv = np.array([F(lat.get(f, 0)) for f in fcols], dtype=np.float64).reshape(1, -1)
                            prob = F(mdl.predict_proba(xv)[0][1]); conf = prob * 100
                            lat_dict = {col: F(lat.get(col, 0)) for col in lf.columns}
                            lat_dict["Close"] = price
                            total_votes, action = show_voting_scorecard(lat_dict, saved)
                            model_trigger = prob >= live_th and action not in ("HOLD", "NO TRADE")
                            c1, c2, c3 = st.columns(3)
                            c1.metric("XAU/USD", f"${price:,.2f}"); c2.metric("Conf", f"{conf:.1f}%")
                            c3.metric("Signal", action if model_trigger else "HOLD")
                            if model_trigger:
                                atr_pv = F(lat.get("ATR_pct", 0)); atr_d = price * atr_pv
                                live_dir = F(lat.get("Signal_Dir", 0))
                                if live_dir == -1: tp_p, sl_p = price - tp_l * atr_d, price + sl_l * atr_d
                                else: tp_p, sl_p = price + tp_l * atr_d, price - sl_l * atr_d
                                sig_color = "#00b09b" if action == "BUY" else "#d63031"
                                st.markdown(f"""<div style="background:linear-gradient(135deg,{sig_color},#96c93d);
                                padding:30px;border-radius:15px;text-align:center;">
                                <h1 style="color:white;">{action} GOLD</h1>
                                <p style="color:white;">TP: ${tp_p:,.2f} | SL: ${sl_p:,.2f}</p>
                                </div>""", unsafe_allow_html=True)
                            else:
                                st.markdown(f"""<div style="background:linear-gradient(135deg,#636e72,#b2bec3);
                                padding:30px;border-radius:15px;text-align:center;">
                                <h1 style="color:white;">HOLD GOLD</h1></div>""", unsafe_allow_html=True)
                        except Exception as e: st.error(f"{type(e).__name__}: {e}"); st.code(traceback.format_exc())

        elif data_source == "manual":
            st.markdown("### Manual OHLC")
            mc1, mc2, mc3, mc4 = st.columns(4)
            m_open = mc1.number_input("Open", value=2650.0, step=0.01, format="%.2f", key="man_o")
            m_high = mc2.number_input("High", value=2660.0, step=0.01, format="%.2f", key="man_h")
            m_low = mc3.number_input("Low", value=2640.0, step=0.01, format="%.2f", key="man_l")
            m_close = mc4.number_input("Close", value=2655.0, step=0.01, format="%.2f", key="man_c")
            if st.button("Predict", type="primary", use_container_width=True):
                try:
                    n_hist = 250
                    prices = np.linspace(m_close * 0.98, m_close, n_hist) + np.random.normal(0, m_close * 0.001, n_hist)
                    hist_df = pd.DataFrame({
                        "Open": prices * (1 + np.random.normal(0, 0.001, n_hist)),
                        "High": prices * (1 + np.abs(np.random.normal(0, 0.002, n_hist))),
                        "Low": prices * (1 - np.abs(np.random.normal(0, 0.002, n_hist))),
                        "Close": prices, "Volume": np.zeros(n_hist)})
                    hist_df["Datetime"] = pd.date_range(end=datetime.now(), periods=n_hist, freq="1h")
                    new_row = pd.DataFrame([{"Open": m_open, "High": m_high, "Low": m_low,
                                             "Close": m_close, "Volume": 0.0, "Datetime": datetime.now()}])
                    combo = pd.concat([hist_df, new_row], ignore_index=True)
                    combo = parse_dates(combo); lf = calc_features(combo, None)
                    saved = joblib.load(MODEL_PATH)
                    sig_dir = compute_bidir_signals(
                        lf, I(saved.get("adx_filter", 20)), F(saved.get("bb_squeeze_thresh", 0.02)),
                        I(saved.get("rsi_entry", 45)), saved.get("momentum_logic", "dip"),
                        F(saved.get("body_threshold", 0.3)), F(saved.get("wick_threshold", 0.2)),
                        I(saved.get("min_votes", 2)))
                    lf["Signal_Dir"] = sig_dir; lat = lf.iloc[-1]
                    mdl = saved["model"]; fcols = saved["feature_columns"]
                    xv = np.array([F(lat.get(f, 0)) for f in fcols], dtype=np.float64).reshape(1, -1)
                    prob = F(mdl.predict_proba(xv)[0][1])
                    lat_dict = {col: F(lat.get(col, 0)) for col in lf.columns}
                    lat_dict["Close"] = m_close
                    total_votes, action = show_voting_scorecard(lat_dict, saved)
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Gold", f"${m_close:,.2f}"); c2.metric("Conf", f"{prob*100:.1f}%")
                    c3.metric("Signal", action)
                    st.info("Synthetic history. Upload real data for accuracy.")
                except Exception as e: st.error(f"{type(e).__name__}: {e}"); st.code(traceback.format_exc())

# ================================================================
# TAB 4: AI CONCEPT PLAYBOOK
# ================================================================
with tab_concept:
    st.header("🧠 AI Concept Playbook")
    st.markdown("*Translates your strategy JSON into a human-readable trading manual.*")
    p = active_p
    pname = p.get("name", "Unknown")
    tp_m = F(p.get("tp_mult", 1.5)); sl_m = F(p.get("sl_mult", 1.0))
    rr = tp_m / sl_m if sl_m > 0 else 1.0
    be_wr = sl_m / (tp_m + sl_m) * 100 if (tp_m + sl_m) > 0 else 50.0
    rsi_e = I(p.get("rsi_entry", 45)); adx_f = I(p.get("adx_filter", 20))
    bb_sq = F(p.get("bb_squeeze_thresh", 0.02)); min_votes = I(p.get("min_votes", 2))
    mom_logic = p.get("momentum_logic", "dip")
    body_t = F(p.get("body_threshold", 0.3)); wick_t = F(p.get("wick_threshold", 0.2))
    use_trail = p.get("use_trailing_stop", False)
    trail_act = F(p.get("trail_activation", 0.5)); trail_dist = F(p.get("trail_distance", 1.0))
    max_hold = I(p.get("max_hold_hours", 24)); time_be = I(p.get("time_be_hours", 12))
    thresh = F(p.get("threshold", 0.55)); window = I(p.get("window", 12))
    use_cp = p.get("use_candle_physics", True)

    if mom_logic == "dip":
        mom_bull = f"RSI(14) < {rsi_e} (buying the dip)"
        mom_bear = f"RSI(14) > {rsi_e} (selling the rally)"
    else:
        mom_bull = f"RSI(14) > {rsi_e} (breakout momentum)"
        mom_bear = f"RSI(14) < {rsi_e} (breakdown momentum)"

    trail_desc = (f"**Trailing Stop: ENABLED** ✅ — Activates after {trail_act}x ATR in your favor, "
                  f"trails {trail_dist}x ATR behind peak." if use_trail
                  else "**Trailing Stop: DISABLED** ❌ — Fixed TP/SL only.")

    playbook = f"""
---
# 📋 TRADING MANUAL: `{pname}`
*Auto-generated by Genesis V26 — {datetime.now().strftime('%Y-%m-%d %H:%M')}*

---
## 1. 🧭 MARKET REGIME FILTER
| Check | Condition | Purpose |
|-------|-----------|---------|
| **ADX Filter** | ADX(14) ≥ **{adx_f}** | Ensures directional momentum |
| **BB Squeeze** | BB Width ≥ **{bb_sq:.3f}** | Ensures sufficient volatility |

❌ If EITHER fails → **NO TRADE** (Chop zone).

---
## 2. 📊 REGIME DETECTION
| Regime | Rule | Direction |
|--------|------|-----------|
| 🟢 BULL | Close > EMA200 | LONG |
| 🔴 BEAR | Close < EMA200 | SHORT |

---
## 3. 🗳️ VOTING SYSTEM (≥{min_votes}/3 required)

### 🟢 BULL (Long):
| Vote | Condition |
|------|-----------|
| 1 Trend | Close > EMA200 + ADX > {adx_f} |
| 2 Momentum | {mom_bull} |
| 3 Pattern | Body > {body_t:.2f} + Lower_Wick > {wick_t:.2f} |

### 🔴 BEAR (Short):
| Vote | Condition |
|------|-----------|
| 1 Trend | Close < EMA200 + ADX > {adx_f} |
| 2 Momentum | {mom_bear} |
| 3 Pattern | Body > {body_t:.2f} + Upper_Wick > {wick_t:.2f} |

---
## 4. 🤖 AI CONFIRMATION
- XGBoost threshold: **{thresh:.0%}** confidence required
- Features: {len(FEATURES_V26)} indicators (incl. Liquidity Sweeps V26)

### Confidence Sizing:
| Probability | Size | Label |
|-------------|------|-------|
| ≥ 85% | 1.5x | 🟣 Sniper |
| ≥ 70% | 1.0x | 🔵 Standard |
| < 70% | 0.5x | 🟢 Cautious |

---
## 5. 💰 RISK MANAGEMENT
| Param | Value | Example (ATR=$500) |
|-------|-------|--------------------|
| TP | {tp_m}x ATR | ±${tp_m * 500:.0f} |
| SL | {sl_m}x ATR | ∓${sl_m * 500:.0f} |
| R/R | {rr:.2f}:1 | |
| BE WR | {be_wr:.1f}% | Min accuracy needed |

{trail_desc}

---
## 6. ⏱️ TIME CONTROLS (V26)
| Rule | Value | Purpose |
|------|-------|---------|
| Max Hold | **{max_hold}h** | Force-close zombie trades |
| Time BE | **{time_be}h** | Move SL to entry if in profit |
| Window | **{window} bars** | Max evaluation window |

---
## 7. 🛡️ SAFETY SYSTEMS
| System | Status |
|--------|--------|
| SHAP Pruning | ✅ Bottom 25% features removed |
| Anti-Cheat | ✅ Overfit/leakage detection |
| Chop Filter | ✅ ADX + BB Squeeze gate |
| Dual Timeframe | ✅ H4 shifted by 1 bar |
| Liquidity Sweeps | ✅ V26 Rolling High/Low detection |
| Time-Stop | ✅ V26 {max_hold}h hard stop |
| Time BE | ✅ V26 {time_be}h breakeven |

---
## 8. 📑 QUICK CHECKLIST
ENTRY:
[ ] ADX ≥ {adx_f}?
[ ] BB Width ≥ {bb_sq:.3f}?
[ ] Regime clear? (Close vs EMA200)
[ ] ≥{min_votes}/3 votes?
[ ] XGBoost ≥ {thresh:.0%}?

AFTER ENTRY:
[ ] TP at {tp_m}x ATR
[ ] SL at {sl_m}x ATR
[ ] Time-stop at {max_hold}h
[ ] BE check at {time_be}h

text

---
*⚠️ Educational only. Not financial advice.*
"""

    st.markdown(playbook)
    st.download_button("📥 Download Playbook", data=playbook,
                       file_name=f"playbook_{pname}_{datetime.now().strftime('%Y%m%d')}.md",
                       mime="text/markdown", use_container_width=True)
    with st.expander("🔧 Raw Strategy JSON"):
        st.json({k: v for k, v in p.items() if k != "name"})

# ================================================================
# FOOTER
# ================================================================
with st.expander("V26 Philosophy"):
    st.markdown("""
    **GENESIS V26 — Bi-Directional Hedge Fund Engine**

    | System | Description |
    |---|---|
    | 🧬 Bi-Dir Signals | Unified long+short per bar |
    | ⛔ Chop Filter | ADX + BB Squeeze gate |
    | 🎯 AI Confidence | 3-tier position sizing |
    | ⏱️ Time-Stop | Force-close zombie trades (V26) |
    | ⏱️ Time-BE | Breakeven after N hours in profit (V26) |
    | 🐋 Liquidity Sweeps | Detect whale manipulation zones (V26) |
    | 💀 Loser's Autopsy | Why trades failed analysis (V26) |
    | 🕯️ Trade Replay | Candlestick visualization (V26) |
    | 🧠 Concept Playbook | Auto-generated trading manual (V26) |
    | ✂️ SHAP Pruning | Bottom 25% features removed |
    | 🛡️ Anti-Cheat | Overfit & leakage detection |
    | 📊 Dual Timeframe | H1 + H4 with anti-cheat shift |

    Educational only. Not financial advice.
    """)