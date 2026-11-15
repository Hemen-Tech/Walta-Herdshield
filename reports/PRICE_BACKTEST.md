# Price backtest (1 month ahead, time-based)

- Month-to-month price pairs available: 55; pairs with a drift estimated only from earlier months: 44
- Typical month-to-month change: median +0.015, standard deviation 0.135 (log scale)
- Mean absolute error, 'no change' forecast: **0.0809**
- Mean absolute error, constant-drift forecast: **0.0818**

Result: the drift model does NOT beat the 'no change' forecast. Month-to-month noise
(~14%) is far larger than the drift (~1.5%/month), so the engine uses drift = 0 by default.
Limits: ~14 months, thin coverage, no seasonality test possible with less than 2 full years.
