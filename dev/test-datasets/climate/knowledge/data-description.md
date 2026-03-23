# CO2 Emissions Data Description

This dataset is the Our World in Data CO2 and greenhouse gas emissions dataset, a comprehensive compilation of global emissions data sourced from the Global Carbon Project, Climate Watch, BP Statistical Review, and other authoritative sources. It is freely available and regularly updated.

The CSV file contains approximately 50,000+ rows and 70+ columns, covering 200+ countries and regions from 1750 to the present. Key columns include:

- **country**: Country or region name.
- **year**: Year of observation.
- **iso_code**: ISO 3166-1 alpha-3 country code.
- **population**: Total population.
- **gdp**: Gross domestic product (in international dollars).
- **co2**: Annual CO2 emissions from fossil fuels and industry (million tonnes).
- **co2_per_capita**: CO2 emissions per person (tonnes per person).
- **coal_co2, oil_co2, gas_co2, cement_co2, flaring_co2**: Emissions by source.
- **cumulative_co2**: Cumulative CO2 emissions since records began.
- **energy_per_capita**: Primary energy consumption per person (kWh).
- **energy_per_gdp**: Energy intensity of GDP (kWh per dollar).
- **share_global_co2**: Country's share of global CO2 emissions (%).
- **methane, nitrous_oxide**: Non-CO2 greenhouse gas emissions.

This dataset presents several analytical challenges:

1. **Scale**: The largest dataset in the test suite (~30 MB), testing how Urika handles bigger data.
2. **Missing data**: Historical records are sparse for many countries before 1900, and some variables are only available for recent decades.
3. **Panel structure**: The data is longitudinal (countries observed over time), requiring panel data methods or time-aware modelling.
4. **Multi-collinearity**: Many variables (GDP, population, energy consumption) are strongly correlated.
5. **Non-stationarity**: Emission trends change over time, so relationships identified in one period may not hold in another.

Appropriate analytical approaches include panel regression, time-series decomposition, clustering of emission trajectories, random forests with temporal features, and changepoint detection. The dataset tests whether Urika can profile large files, handle missing data intelligently, and apply temporal analysis methods.
