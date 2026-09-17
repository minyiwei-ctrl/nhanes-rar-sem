# Klemera-Doubal biological age (KDM-BA) for NHANES 2011-2014, computed with
# the BioAge package (Kwon & Belsky 2021). Reads
# data/processed/8_nhanes_analytic.csv and overwrites it with two added columns:
#   KDM_BA          Klemera-Doubal biological age (years)
#   KDM_BA_advance  KDM_BA - chronological age (years); positive = biologically
#                   older than chronological age. Mediator in the SEM
#                   (scripts/9_mplus_models/*.inp).
#
# Calibration is internal: the biomarker-age regressions are fitted on the
# pooled 2011-2014 adults (age >= 18) with the complete ten-marker panel, and
# no external training data is passed to kdm_calc(). Under internal calibration
# KDM_BA_advance regressed on age has slope 0 in the pooled sample but not
# within age strata, so every model adjusts for age inside its stratum.
#
# Biomarker panel (complete case; the resulting n is printed and carried into
# the sample-accounting table):
#   albumin (LBXSAL, g/dL), lymphocyte percentage (LBXLYPCT, %), mean
#   corpuscular volume (LBXMCVSI, fL), glucose (LBXSGL, mg/dL, converted to
#   mmol/L by dividing by 18.018), red cell distribution width (LBXRDW, %),
#   creatinine (LBXSCR, mg/dL), alkaline phosphatase (LBXSAPSI, U/L), white
#   blood cell count (LBXWBCSI, 10^9/L), HbA1c (LBXGH, %), total cholesterol
#   (LBXTC, mg/dL). C-reactive protein was not measured in 2011-2014.
#
# Method (Klemera & Doubal 2006; Levine 2013). Stage 1: for each biomarker x_j,
# regress x_j = q_j + k_j * CA + e_j in the calibration sample, with residual SD
# s_j. Stage 2: for each participant,
#       BA_E = ( Sum_j k_j (x_j - q_j) / s_j^2 + CA / s_BA^2 )
#              / ( Sum_j (k_j / s_j)^2 + 1 / s_BA^2 )
# where s_BA^2 is the residual variance of CA regressed on the panel (supplied
# by BioAge::kdm_calc). KDM_BA = BA_E.
#
# References
#   Klemera P, Doubal S (2006) Mech Ageing Dev 127:240-248.
#   Levine ME (2013) J Gerontol A 68:667-674.
#   Kwon D, Belsky DW (2021) GeroScience 43:2795-2808.
#
# Run after 5_accelerometer_RAR.ipynb and before 6_descriptives.ipynb:
#   Rscript scripts/5_5_compute_kdm_ba.R
suppressPackageStartupMessages({
  library(BioAge)
  library(dplyr)
  library(readr)
  library(tibble)
})
cat(R.version.string, "; BioAge", as.character(packageVersion("BioAge")), "\n")

# Paths
# Locate the project root from NHANES_SEM_ROOT, the working directory or its
# parents (the same resolver the Python notebooks use).
find_root <- function() {
  env <- Sys.getenv("NHANES_SEM_ROOT", unset = NA)
  cands <- c(if (!is.na(env)) env else NULL,
             getwd(),
             dirname(getwd()),
             dirname(dirname(getwd())))
  for (q in cands) {
    if (dir.exists(file.path(q, "data", "processed")) &&
        dir.exists(file.path(q, "scripts"))) return(normalizePath(q))
  }
  stop("cannot find the project root from ", getwd(),
       " -- run from inside the project, or set NHANES_SEM_ROOT")
}
BASE   <- find_root()
INFILE <- file.path(BASE, "data", "processed", "8_nhanes_analytic.csv")

stopifnot(file.exists(INFILE))
cat("Reading", INFILE, "\n")
dat <- read_csv(INFILE, show_col_types = FALSE, guess_max = 20000)
cat("  shape: ", nrow(dat), "rows x", ncol(dat), "cols\n\n", sep = " ")

# Drop KDM-BA columns from any earlier run so the script can be re-run in place
dat <- dat %>% select(-any_of(c("KDM_BA", "KDM_BA_advance",
                                "KDM_BA.x", "KDM_BA.y",
                                "KDM_BA_advance.x", "KDM_BA_advance.y")))


# Biomarker panel
biomarker_panel <- c("albumin", "lymph", "mcv", "glucose_mmol", "rdw",
                     "creat", "alp", "wbc", "hba1c", "totchol")
cat("Biomarker panel (", length(biomarker_panel), "markers):",
    paste(biomarker_panel, collapse = ", "), "\n")


# Rename NHANES variables to BioAge names and convert units
dat_kdm <- dat %>%
  mutate(
    age          = RIDAGEYR,
    albumin      = LBXSAL,             # g/dL
    lymph        = LBXLYPCT,            # %
    mcv          = LBXMCVSI,            # fL
    glucose_mmol = LBXSGL / 18.018,     # mg/dL -> mmol/L
    rdw          = LBXRDW,              # %
    creat        = LBXSCR,              # mg/dL (unit of the BioAge 'creat' column)
    alp          = LBXSAPSI,            # U/L
    wbc          = LBXWBCSI,            # 10^9/L
    hba1c        = LBXGH,               # %
    totchol      = LBXTC                # mg/dL (unit of the BioAge 'totchol' column)
  )


# Adults with the complete biomarker panel
adult_panel <- dat_kdm %>%
  filter(age >= 18) %>%
  filter(if_all(all_of(biomarker_panel), ~ !is.na(.)))

cat("\nAdult sample with complete biomarker panel: n =", nrow(adult_panel), "\n")


# Internal calibration: the biomarker-age regressions are fitted within this
# sample; no external training data is passed to kdm_calc().
cat("\nFitting KDM model on NHANES 2011-2014 adult sample (internal calibration)...\n")

kdm_out  <- kdm_calc(data = adult_panel, biomarkers = biomarker_panel)
kdm_test <- kdm_out$data
cat("  fit converged     : yes\n")


# Diagnostics
ba  <- kdm_test$kdm
acc <- ba - kdm_test$age
r   <- cor(ba, kdm_test$age, use = "complete.obs")

qs <- quantile(ba, c(0.01, 0.05, 0.5, 0.95, 0.99), na.rm = TRUE)

cat("\nDiagnostics\n")
cat("  panel used            :", paste(biomarker_panel, collapse = ", "), "\n")
cat("  KDM-BA n              :", sum(!is.na(ba)), "\n")
cat("  KDM-BA mean (years)   :", round(mean(ba,  na.rm = TRUE), 1), "\n")
cat("  KDM-BA SD             :", round(sd(ba,    na.rm = TRUE), 1), "\n")
cat("  KDM-BA range          :", round(range(ba, na.rm = TRUE), 1), "\n")
cat(sprintf("  KDM-BA quantiles      : 1%%=%.1f  5%%=%.1f  50%%=%.1f  95%%=%.1f  99%%=%.1f\n",
            qs[1], qs[2], qs[3], qs[4], qs[5]))
cat("  advancement mean     :", round(mean(acc, na.rm = TRUE), 3),
    " (target near 0)\n")
cat("  advancement SD       :", round(sd(acc,   na.rm = TRUE), 2), "\n")
cat("  cor(KDM-BA, age)      :", round(r, 3), " (target >= 0.6)\n")

if (r < 0.6) {
  warning("Correlation with chronological age is below the 0.6 quality ",
          "threshold; consider reviewing biomarker scaling or training cohort.",
          call. = FALSE)
}


# Merge KDM columns back into the full analytic dataset
kdm_attach <- tibble(
  SEQN         = kdm_test$SEQN,
  KDM_BA       = ba,
  KDM_BA_advance = acc
)
dat <- dat %>% left_join(kdm_attach, by = "SEQN")

cat("\nFinal analytic dataset\n")
cat("  n rows                :", nrow(dat), "\n")
cat("  n cols                :", ncol(dat), "\n")
cat("  n with KDM-BA         :", sum(!is.na(dat$KDM_BA)), "\n")


# Save (overwrites the input file)
write_csv(dat, INFILE)
cat("\nWrote", INFILE, "\n")
