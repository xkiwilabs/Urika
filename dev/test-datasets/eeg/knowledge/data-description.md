# EEG Motor Imagery Data Description

This dataset contains synthetic EEG data from a motor imagery brain-computer interface (BCI) experiment. Ten participants performed left-hand and right-hand motor imagery tasks while 7-channel EEG was recorded at 250 Hz. The experiment also includes rest trials as a baseline condition.

Each row represents a single time point within a trial epoch. Columns are:

- **participant_id**: Participant identifier (P01–P10).
- **trial**: Trial number within each participant (1–20).
- **channel**: EEG electrode name (Fz, Cz, Pz, C3, C4, O1, O2), placed according to the international 10-20 system.
- **condition**: Motor imagery condition — `left_hand`, `right_hand`, or `rest`.
- **epoch_ms**: Time in milliseconds from epoch onset (0–996 in 4 ms steps, corresponding to 250 Hz sampling).
- **amplitude_uv**: EEG voltage amplitude in microvolts.

The data is structured as long-format time series. Each trial consists of a 1-second epoch (250 samples per channel) time-locked to a visual cue instructing the participant which hand to imagine moving (or to rest). The key neurophysiological feature of interest is event-related desynchronisation (ERD) of the mu rhythm (8–13 Hz) and beta rhythm (13–30 Hz) over sensorimotor cortex. During left-hand motor imagery, ERD is expected to be stronger over the right motor cortex (channel C4), and vice versa for right-hand imagery (channel C3). This contralateral pattern provides the basis for classification.

The data is synthetic and designed for testing time-series analysis pipelines, spectral feature extraction, and classification workflows. Realistic noise and inter-participant variability are included, but the lateralised ERD effect is embedded in the signal to ensure classifiability.
