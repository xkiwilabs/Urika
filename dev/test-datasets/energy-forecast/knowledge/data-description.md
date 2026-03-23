# Energy Demand Dataset — Data Collection Methods and Procedures

This dataset contains hourly electricity demand measurements from a regional power grid, recorded continuously over a 24-month period (January 2023 to December 2024). Demand is measured in megawatts (MW) at the transmission level using SCADA telemetry systems, aggregated to hourly resolution.

Weather covariates (temperature, wind speed, solar irradiance) are sourced from meteorological stations within the grid's service area and temporally aligned with demand readings. Temperature is in degrees Celsius, wind speed in metres per second, and solar irradiance is normalised (0-1 scale representing clear-sky fraction).

The data exhibits several well-known patterns in energy demand: a strong diurnal cycle driven by human activity (peak demand around 18:00, minimum around 04:00), reduced demand on weekends, annual seasonality from heating and cooling loads, and a non-linear relationship with temperature (demand increases at both high and low temperature extremes due to air conditioning and heating respectively). Holiday periods show reduced demand. A slight upward trend reflects growing energy consumption over the period.

For forecasting evaluation, the standard approach is to use the final 3 months as a test set, with the preceding data for training. Forecast horizons of 24 hours (day-ahead) and 48 hours are standard industry benchmarks. Metrics should include RMSE, MAE, and MAPE. The non-linear temperature interactions and multiple overlapping seasonalities make this problem well-suited to comparing traditional statistical methods (ARIMA, exponential smoothing), machine learning (gradient boosting with lag features), and deep learning (LSTM, Transformer) approaches.
