"""Forecasting models.

Every model exposes ``fit(y)`` on a complete monthly pandas Series and
``predict(h)`` returning an ndarray of h point forecasts for the months that
follow the end of ``y``. Uncertainty is NOT taken from model internals: it is
estimated from each model's own out-of-sample errors in rolling-origin
validation (see validation.py), which keeps intervals comparable across very
different model families.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


def _months(index: pd.DatetimeIndex) -> np.ndarray:
    return index.month.values


def _future_index(y: pd.Series, h: int) -> pd.DatetimeIndex:
    return pd.date_range(y.index[-1] + pd.offsets.MonthBegin(1), periods=h, freq="MS")


class Model:
    name = "base"
    label = "Base"
    family = "baseline"
    description = ""

    def __init__(self, seasonal: bool):
        self.seasonal = seasonal

    def fit(self, y: pd.Series) -> "Model":
        self.y = y
        return self

    def predict(self, h: int) -> np.ndarray:  # pragma: no cover
        raise NotImplementedError


class Naive(Model):
    name, label, family = "naive", "Persistence (naive)", "baseline"
    description = "Every future month equals the last observed month."

    def predict(self, h):
        return np.repeat(self.y.iloc[-1], h)


class SeasonalNaive(Model):
    name, label, family = "snaive", "Seasonal naive", "baseline"
    description = "Each future month equals the same calendar month one year earlier (repeated)."

    def predict(self, h):
        last = self.y.iloc[-12:].values
        return np.array([last[i % 12] for i in range(h)])


class Drift(Model):
    name, label, family = "drift", "Random walk with drift", "baseline"
    description = "Last value plus the average month-to-month change over the last 30 years (seasonal: year-on-year change, applied to the last year)."

    def fit(self, y):
        self.y = y
        w = y.iloc[-360:]
        if self.seasonal:
            self.slope = (w.iloc[-12:].mean() - w.iloc[:12].mean()) / (len(w) - 12)
        else:
            self.slope = (w.iloc[-1] - w.iloc[0]) / (len(w) - 1)
        return self

    def predict(self, h):
        if self.seasonal:
            last = self.y.iloc[-12:].values
            return np.array([last[i % 12] + self.slope * (12 * (i // 12 + 1)) for i in range(h)])
        return self.y.iloc[-1] + self.slope * np.arange(1, h + 1)


class _Regression(Model):
    degree = 1
    window = 360  # months of history used (30 years)

    def _X(self, t, months):
        cols = [t ** d for d in range(1, self.degree + 1)]
        if self.seasonal:
            cols += [(months == m).astype(float) for m in range(2, 13)]
        return np.column_stack([np.ones_like(t)] + cols)

    def fit(self, y):
        self.y = y
        w = y.iloc[-self.window:]
        self.t0 = len(y) - len(w)
        t = (np.arange(len(w)) / 120.0)
        X = self._X(t, _months(w.index))
        self.beta, *_ = np.linalg.lstsq(X, w.values, rcond=None)
        self.n = len(w)
        return self

    def predict(self, h):
        t = (np.arange(self.n, self.n + h) / 120.0)
        X = self._X(t, _months(_future_index(self.y, h)))
        return X @ self.beta


class LinearTrend(_Regression):
    name, label, family = "linear", "Linear regression (trend + month effects)", "regression"
    description = "Ordinary least squares on a linear time trend (plus calendar-month dummies for seasonal series), fitted to the most recent 30 years."
    degree = 1


class PolyTrend(_Regression):
    name, label, family = "poly2", "Polynomial regression (quadratic)", "regression"
    description = "Quadratic time trend (captures acceleration) plus calendar-month dummies, fitted to the most recent 30 years."
    degree = 2


class ETS(Model):
    name, label, family = "ets", "Exponential smoothing (Holt-Winters, damped)", "statistical"
    description = "Additive-error exponential smoothing with a damped additive trend and additive seasonality where the series is seasonal (statsmodels)."

    def fit(self, y):
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        self.y = y
        w = y.iloc[-360:]
        self.res = ExponentialSmoothing(
            w.values, trend="add", damped_trend=True,
            seasonal="add" if self.seasonal else None, seasonal_periods=12 if self.seasonal else None,
            initialization_method="estimated",
        ).fit(optimized=True)
        return self

    def predict(self, h):
        return np.asarray(self.res.forecast(h))


class SARIMA(Model):
    name, label, family = "sarima", "ARIMA / SARIMA", "statistical"
    description = "Seasonal ARIMA with order chosen by AIC from a small candidate set on the full training record, then re-estimated at every validation origin (statsmodels SARIMAX)."
    order = (1, 1, 1)
    sorder = (0, 1, 1, 12)

    def __init__(self, seasonal, order=None, sorder=None, trend=None):
        super().__init__(seasonal)
        if order:
            self.order = order
        self.sorder = sorder if sorder is not None else ((0, 1, 1, 12) if seasonal else (0, 0, 0, 0))
        self.trend = trend

    def fit(self, y):
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        self.y = y
        w = y.iloc[-360:]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.res = SARIMAX(w.values, order=self.order, seasonal_order=self.sorder, trend=self.trend,
                               enforce_stationarity=False, enforce_invertibility=False).fit(disp=False, maxiter=200)
        return self

    def predict(self, h):
        return np.asarray(self.res.forecast(h))

    @classmethod
    def select(cls, y: pd.Series, seasonal: bool) -> "SARIMA":
        """Pick (p,d,q)(P,D,Q) by AIC on the last 30 years."""
        from statsmodels.tsa.statespace.sarimax import SARIMAX

        w = y.iloc[-360:].values
        cands = []
        nons = [((1, 1, 1), "n"), ((2, 1, 1), "n"), ((1, 1, 2), "n"), ((0, 1, 1), "n"), ((1, 1, 1), "t"), ((1, 0, 1), "ct")]
        seas = [(0, 1, 1, 12), (1, 1, 1, 12)] if seasonal else [(0, 0, 0, 0)]
        for o, tr in nons:
            for so in seas:
                if so[1] == 1 and tr == "ct":
                    continue
                try:
                    warnings.simplefilter("ignore")
                    r = SARIMAX(w, order=o, seasonal_order=so, trend=None if tr == "n" else tr,
                                enforce_stationarity=False, enforce_invertibility=False).fit(disp=False, maxiter=200)
                    cands.append((r.aic, o, so, None if tr == "n" else tr))
                except Exception:  # noqa: BLE001
                    continue
        aic, o, so, tr = min(cands, key=lambda c: c[0])
        m = cls(seasonal, order=o, sorder=so, trend=tr)
        m.selection = {"order": list(o), "seasonal_order": list(so), "trend": tr, "aic": round(float(aic), 1),
                       "candidates_tried": len(cands)}
        return m

    @property
    def spec(self) -> str:
        s = f"ARIMA{self.order}"
        if self.sorder and self.sorder[3]:
            s += f"x{self.sorder[:3]}[12]"
        if self.trend:
            s += f" trend={self.trend}"
        return s


class GradientBoosting(Model):
    name, label, family = "gbr", "Gradient boosting (lag features)", "machine learning"
    description = ("scikit-learn GradientBoostingRegressor predicting the month-to-month change from lagged changes, "
                   "lagged levels relative to the 12-month mean and calendar month; multi-step forecasts are produced "
                   "recursively. Trees cannot extrapolate levels, so the model works on differences.")
    lags = (1, 2, 3, 6, 12, 24)

    def _features(self, d: np.ndarray, lvl_dev: np.ndarray, months: np.ndarray, i: int) -> list[float]:
        return [d[i - l] for l in self.lags] + [lvl_dev[i - 1], np.sin(2 * np.pi * months[i] / 12), np.cos(2 * np.pi * months[i] / 12)]

    def fit(self, y):
        from sklearn.ensemble import GradientBoostingRegressor

        self.y = y
        w = y.iloc[-360:]
        v = w.values
        d = np.r_[np.nan, np.diff(v)]
        lvl = v - pd.Series(v).rolling(12, min_periods=1).mean().values
        mo = _months(w.index)
        X, Y = [], []
        for i in range(max(self.lags) + 1, len(v)):
            X.append(self._features(d, lvl, mo, i))
            Y.append(d[i])
        self.model = GradientBoostingRegressor(n_estimators=300, max_depth=3, learning_rate=0.03, subsample=0.8,
                                               random_state=42).fit(np.array(X), np.array(Y))
        self._v, self._d, self._mo = list(v), list(d), list(mo)
        return self

    def predict(self, h):
        v, d, mo = list(self._v), list(self._d), list(self._mo)
        out = []
        for k in range(h):
            m_next = (mo[-1] % 12) + 1
            mo.append(m_next)
            lvl = np.array(v) - pd.Series(v).rolling(12, min_periods=1).mean().values
            i = len(v)
            dd = np.array(d + [np.nan])
            x = self._features(dd, np.r_[lvl, np.nan], np.array(mo), i)
            step = float(self.model.predict(np.array([x]))[0])
            d.append(step)
            v.append(v[-1] + step)
            out.append(v[-1])
        return np.array(out)


MODEL_CLASSES = [Naive, SeasonalNaive, Drift, LinearTrend, PolyTrend, ETS, SARIMA, GradientBoosting]
BASELINES = {"naive", "snaive", "drift"}

NOT_USED = {
    "prophet": "Not used: Prophet's piecewise-linear trend with automatic changepoints adds a heavy dependency and, for "
               "these smooth monthly climate series, offers nothing beyond the ETS/SARIMA/regression trend models already "
               "validated here.",
    "lstm": "Not used: each series has 300-1,800 monthly points (a few hundred independent seasonal cycles). That is far "
            "too little to train a recurrent network without overfitting, and deep models cannot be justified over the "
            "statistical models on out-of-sample skill at this sample size.",
}
