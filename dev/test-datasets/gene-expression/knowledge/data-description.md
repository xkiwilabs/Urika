# Gene Expression Data Description

This dataset contains synthetic gene expression microarray data from a case-control study comparing tumour and normal tissue samples. The data simulates a typical differential expression experiment where the goal is to identify genes whose expression levels differ between conditions.

The CSV file has 80 rows (samples) and 202 columns:

- **sample_id**: Sample identifier (S001–S080).
- **condition**: Tissue type — `cancer` or `normal` (40 samples each).
- **gene_001 through gene_200**: Log2-normalised expression intensities for 200 genes.

The data is designed to present several realistic analytical challenges:

1. **High dimensionality**: With 200 features and only 80 samples, the data has a high feature-to-sample ratio (p >> n), making naive classifiers prone to overfitting.
2. **Differential expression**: A subset of genes (approximately 20–30) have genuinely different mean expression levels between cancer and normal samples, while the remaining genes are noise.
3. **Multiple testing**: Testing 200 genes simultaneously for differential expression requires correction for multiple comparisons (e.g., Bonferroni, Benjamini-Hochberg FDR).
4. **Correlated features**: Some gene groups have correlated expression patterns, reflecting co-regulation in biological pathways.

Appropriate analytical approaches include volcano plots, t-tests with FDR correction, regularised classifiers (LASSO, elastic net, ridge), dimensionality reduction (PCA), and feature importance analysis. The dataset tests whether Urika can handle wide data, apply appropriate feature selection, and avoid overfitting through cross-validation.
