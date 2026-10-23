# flex-loglinear

This baseline is a purely statistical forecaster: a second-order autoregression on the logarithm of the lens's nowcast over the last 16 weeks. It can follow growth and decline and a turning trend without any epidemic mechanism, so it shows how much of a theory's skill an assumption-free time series model already has.

Uncertainty comes from the model's own residuals: 4000 paths are run forward to the target week, each step adding a residual drawn at random, and the forecast is the distribution of the paths' ends, scaled to what the resolution vintage will report. The lens cuts the far upper tail of that distribution, as it does for every forecast built on it. Resampling residuals rather than assuming a distribution lets the data decide how wide and how skewed the forecast is.
