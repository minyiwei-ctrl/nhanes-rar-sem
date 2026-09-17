# R environment

Used by one stage, `scripts/5_5_compute_kdm_ba.R` (Klemera–Doubal biological
age). R ≥ 4.2 with:

```r
install.packages(c("dplyr", "readr", "tibble", "remotes"))
remotes::install_github("dayoonkwon/BioAge")   # kdm_calc()
```

`BioAge` is installed from GitHub and has no CRAN release; the script
records the installed version in its console output when it runs
(`packageVersion("BioAge")`).
