# Results — models run 2026-11-11T14:21:43+00:00

Generated automatically from `data/processed/dashboard.json`. Reference month October 2026; forecast window November 2026 – October 2028.

## Ranking: parameters projected to increase

Change = forecast mean Nov 2027–Oct 2028 minus the mean of the latest 12 observed months. P(increase) uses the selected model's out-of-sample error for that 12-month mean.

| # | Parameter | Unit | Latest 12 months | Nov 2027–Oct 2028 | Change (95% interval) | P(increase) | Likelihood | 30-yr trend | Selected model |
|---|---|---|---|---|---|---|---|---|---|
| 1 | CO₂ | ppm | 428.71 (2025-10 to 2026-09) | 434.76 | +6.05 (+5.06 to +7.04) | 100.0% | Virtually certain to increase | increasing (strong seasonal cycle) | Polynomial regression (quadratic) |
| 2 | Sea level | mm | 103.2 (2025-11 to 2026-10) | 112.1 | +8.9 (+3.5 to +14.3) | 99.9% | Virtually certain to increase | increasing (strong seasonal cycle) | ARIMA / SARIMA |
| 3 | Aerosol optical depth | unitless | 0.157 (2025-08 to 2026-07) | 0.161 | +0.004 (-0.006 to +0.015) | 79.0% | Likely to increase | no statistically significant trend (strong seasonal cycle) | Polynomial regression (quadratic) |
| 4 | Sea surface temperature | °C | 0.91 (2025-10 to 2026-09) | 1.00 | +0.08 (-0.15 to +0.32) | 75.6% | Likely to increase | increasing | ARIMA / SARIMA |
| 5 | Global temperature | °C | 1.21 (2025-10 to 2026-09) | 1.29 | +0.08 (-0.20 to +0.35) | 70.4% | Likely to increase | increasing | ARIMA / SARIMA |
| 6 | Arctic sea ice | million km² | 10.19 (2025-11 to 2026-10) | 10.25 | +0.07 (-0.53 to +0.67) | 58.5% | About as likely as not | decreasing (strong seasonal cycle) | ARIMA / SARIMA |
| 7 | Land temperature | °C | 1.48 (2025-10 to 2026-09) | 1.47 | -0.01 (-0.30 to +0.29) | 48.1% | About as likely as not | increasing | ARIMA / SARIMA |
| 8 | Precipitation | mm/day | 2.757 (2025-10 to 2026-09) | 2.620 | -0.137 (-0.253 to -0.021) | 1.0% | Very likely to decrease | no statistically significant trend | ARIMA / SARIMA |

## Latest observations and projections

| Parameter | Latest observation | Baseline 1991–2020 | Rate (last 30 yr) | +6 mo (Apr 2027) | +12 mo (Oct 2027) | +18 mo (Apr 2028) | +24 mo (Oct 2028) |
|---|---|---|---|---|---|---|---|
| CO₂ (ppm) | 426.07 (Sep 2026) | 381.91 | +2.238/yr (95% CI +2.18 to +2.3) | 434.56 [433.41, 435.71] | 429.91 [428.65, 431.18] | 437.35 [435.99, 438.72] | 432.73 [431.36, 434.09] |
| Sea level (mm) | 114.7 (Oct 2026) | 39.8 | +3.318/yr (95% CI +3.21 to +3.42) | 103.5 [99.1, 108.0] | 117.5 [111.5, 123.6] | 106.8 [100.4, 113.2] | 120.8 [114.2, 127.4] |
| Aerosol optical depth (unitless) | 0.199 (Jul 2026) | 0.168 | +4.831e-05/yr (95% CI -0.000215 to +0.000311) | 0.171 [0.146, 0.195] | 0.149 [0.124, 0.174] | 0.170 [0.144, 0.195] | 0.148 [0.122, 0.174] |
| Sea surface temperature (°C) | 1.10 (Sep 2026) | 0.47 | +0.01793/yr (95% CI +0.0137 to +0.0221) | 1.05 [0.83, 1.27] | 1.02 [0.74, 1.29] | 1.00 [0.71, 1.28] | 0.98 [0.69, 1.28] |
| Global temperature (°C) | 1.38 (Sep 2026) | 0.61 | +0.02535/yr (95% CI +0.0206 to +0.0301) | 1.28 [0.87, 1.69] | 1.31 [0.86, 1.77] | 1.28 [0.82, 1.73] | 1.33 [0.88, 1.79] |
| Arctic sea ice (million km²) | 6.69 (Oct 2026) | 11.10 | -0.05147/yr (95% CI -0.0609 to -0.0421) | 13.72 [12.88, 14.56] | 6.29 [5.43, 7.14] | 13.68 [12.76, 14.61] | 6.26 [5.30, 7.22] |
| Land temperature (°C) | 1.46 (Sep 2026) | 0.79 | +0.03073/yr (95% CI +0.0258 to +0.0357) | 1.44 [0.90, 1.99] | 1.46 [0.89, 2.02] | 1.47 [0.91, 2.03] | 1.48 [0.92, 2.05] |
| Precipitation (mm/day) | 2.643 (Sep 2026) | 2.629 | +3.314e-05/yr (95% CI -0.00314 to +0.00321) | 2.620 [2.261, 2.979] | 2.620 [2.261, 2.978] | 2.620 [2.261, 2.978] | 2.620 [2.261, 2.978] |

Values in brackets are 95% prediction intervals.

## Model validation

Rolling-origin evaluation: 20 origins, 6 months apart, each forecasting to October 2028.

| Parameter | Selected | RMSE | MAE | MAPE | MASE | Skill vs best baseline | Best baseline | 80% / 95% coverage | Residual check |
|---|---|---|---|---|---|---|---|---|---|
| CO₂ | Polynomial regression (quadratic) | 0.5837 | 0.4616 | 0.11% | 0.114 | +54% | Random walk with drift | 84% / 97% | one-step errors remain autocorrelated (Ljung-Box p <= 0.05): the model misses some persistent structure, so intervals may be optimistic; no significant bias; errors are non-normal (heavy tails or skew). |
| Sea level | ARIMA / SARIMA ARIMA(2, 1, 1)x(0, 1, 1)[12] | 2.643 | 2.047 | n/a | 0.395 | +14% | Random walk with drift | 81% / 97% | no significant autocorrelation left in one-step errors (Ljung-Box p > 0.05); no significant bias; errors consistent with normality. |
| Aerosol optical depth | Polynomial regression (quadratic) | 0.009827 | 0.007584 | 4.42% | 0.838 | +16% | Seasonal naive | 88% / 97% | one-step errors remain autocorrelated (Ljung-Box p <= 0.05): the model misses some persistent structure, so intervals may be optimistic; no significant bias; errors consistent with normality. |
| Sea surface temperature | ARIMA / SARIMA ARIMA(1, 0, 1) trend=ct | 0.1214 | 0.09328 | n/a | 0.797 | +16% | Persistence (naive) | 82% / 94% | no significant autocorrelation left in one-step errors (Ljung-Box p > 0.05); no significant bias; errors consistent with normality. |
| Global temperature | ARIMA / SARIMA ARIMA(2, 1, 1)x(0, 1, 1)[12] | 0.1717 | 0.1315 | n/a | 0.720 | +23% | Random walk with drift | 88% / 97% | no significant autocorrelation left in one-step errors (Ljung-Box p > 0.05); systematic bias of -0.029 per month (t-test p <= 0.05); errors consistent with normality. |
| Arctic sea ice | ARIMA / SARIMA ARIMA(1, 1, 2)x(0, 1, 1)[12] | 0.3886 | 0.3167 | 3.63% | 0.874 | +16% | Random walk with drift | 85% / 98% | no significant autocorrelation left in one-step errors (Ljung-Box p > 0.05); no significant bias; errors consistent with normality. |
| Land temperature | ARIMA / SARIMA ARIMA(1, 0, 1) trend=ct | 0.2144 | 0.1673 | n/a | 0.712 | +20% | Seasonal naive | 90% / 98% | no significant autocorrelation left in one-step errors (Ljung-Box p > 0.05); systematic bias of -0.0653 per month (t-test p <= 0.05); errors consistent with normality. |
| Precipitation | ARIMA / SARIMA ARIMA(1, 0, 1) trend=ct | 0.1448 | 0.1162 | 4.50% | 0.751 | +23% | Persistence (naive) | 87% / 98% | no significant autocorrelation left in one-step errors (Ljung-Box p > 0.05); no significant bias; errors consistent with normality. |

### All models (RMSE)

| Parameter | Persistence (naive) | Seasonal naive | Random walk with drift | Linear regression (trend + month effects) | Polynomial regression (quadratic) | Exponential smoothing (Holt-Winters, damped) | ARIMA / SARIMA | Gradient boosting (lag features) |
|---|---|---|---|---|---|---|---|---|
| CO₂ | 4.499 | 4.38 | 1.267 | 3.506 | **0.5837** | 1.109 | 0.9258 | 1.081 |
| Sea level | 8.876 | 6.047 | 3.081 | 5.686 | 3.187 | 3.229 | **2.643** | 2.723 |
| Aerosol optical depth | 0.02196 | 0.01167 | 0.01191 | 0.009893 | **0.009827** | 0.01145 | 0.01021 | 0.01573 |
| Sea surface temperature | 0.1451 | 0.1539 | 0.1474 | 0.1408 | 0.1238 | 0.1453 | **0.1214** | 0.1381 |
| Global temperature | 0.2409 | 0.2301 | 0.2242 | 0.182 | 0.1824 | 0.2098 | **0.1717** | 0.2163 |
| Arctic sea ice | 5.119 | 0.4624 | 0.4618 | 0.4867 | 0.4571 | 0.5977 | **0.3886** | 0.5677 |
| Land temperature | 0.2885 | 0.2678 | 0.2935 | 0.2162 | 0.2197 | 0.2518 | **0.2144** | 0.2671 |
| Precipitation | 0.189 | 0.1943 | 0.1922 | 0.1449 | 0.1542 | 0.155 | **0.1448** | 0.1711 |

## Not available


## Insights

- **Very likely to be higher by 2028.** The validated forecasts give at least a 90% chance that the November 2027 – October 2028 average will exceed the latest 12 months for CO₂ (100.0%) and sea level (99.9%).
- **Likely, but not certain, to be higher.** Aerosol optical depth (79%), sea surface temperature (76%) and global temperature (70%): more likely than not to rise, with probabilities between 66% and 90%. Year-to-year variability is large enough that a lower two-year average remains possible.
- **Projected to be lower.** Precipitation (1% chance of an increase) is projected lower: an expected return toward normal after an unusually high recent 12 months, not a long-term decline (its 30-year trend is not statistically significant).
- **No clear direction over two years.** For Arctic sea ice (59%) and land temperature (48%), the projected change is small compared with year-to-year variability and forecast error. Their long-term records still show: Arctic sea ice decreasing; land temperature increasing. A clear long-term trend can coexist with an uncertain two-year outlook.
- **CO₂ growth is the most predictable signal.** Mauna Loa CO₂ averaged 428.7 ppm over Oct 2025 – Sep 2026. The selected model (Polynomial regression (quadratic)) projects 434.8 ppm for Nov 2027-Oct 2028 (95% interval +5.1 to +7.0 ppm change). The 30-year trend is 22.4 ppm per decade and the recent 15-year rate is 25.2 ppm per decade versus 19.8 before.
- **Sea-level rise has accelerated.** Satellite altimetry shows global mean sea level rising 3.6 mm/yr over Nov 2011 – Oct 2026 compared with 2.6 mm/yr over Nov 1996 – Oct 2011. The projected change in the annual mean to Nov 2027-Oct 2028 is +8.9 mm (95% interval +3.5 to +14.3).
- **Global temperature: high level, but year-to-year swings dominate a 2-year outlook.** GISTEMP's latest monthly anomaly is +1.38 °C (Sep 2026, vs 1951-1980), ranked #2 of 147 for that calendar month. The 30-year trend is +0.25 °C/decade, but over two years ENSO-driven variability (not modelled explicitly) is comparable in size, which is why the interval is wide.
- **Arctic sea ice continues its long decline, with large variability.** The 30-year trend in monthly extent is -0.51 million km² per decade. September 2026 extent was 4.81 million km²; the three lowest Septembers on record are 2012 (3.57), 2020 (4.00), 2007 (4.27).
- **Where warming is strongest.** In GISTEMP's 1981-2025 change map the Arctic (64-90°N) warmed 2.94 °C versus 0.93 °C for the globe (about 3.1×). Northern mid-latitudes (24-64°N) warmed 1.46 °C, the tropics 0.71 °C and the Southern Ocean belt (64-24°S) only 0.44 °C.
- **Co-variability (not causation).** After removing shared trends (year-to-year differences, 1993-2025), the strongest statistically significant associations are: Global temperature & Land temperature r = +0.94; Global temperature & Sea surface temperature r = +0.84; Sea surface temperature & Land temperature r = +0.67. These reflect shared physical drivers (e.g. ENSO) or measurement overlap and do not by themselves establish cause.
- **What the uncertainty bands mean.** Intervals come from each model's own errors when it was repeatedly re-trained on past data and asked to forecast the following months (20 rolling origins). They capture typical forecast error, not structural surprises such as a major volcanic eruption, a step change in emissions, or an instrument change.
- **Why these trends matter.** Rising CO₂ is the dominant driver of the long-term warming seen in the temperature records (an attribution established by physical climate science, not by the correlations computed here). Warmer oceans and melting land ice raise sea level, which compounds coastal flooding; Arctic sea-ice loss reduces surface reflectivity and amplifies regional warming.
