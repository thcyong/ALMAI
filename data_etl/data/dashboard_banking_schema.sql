-- ALMAI | Banking Dashboard business-domain schema
-- Generated from DashboardItems_202611090412(1).xlsx (331 source fields, one example row).
-- NON-DESTRUCTIVE: does NOT DROP finance.metric_value or other existing objects.
-- RevisionID is fixed to 0 in the source query for the current phase; no historical versions.
-- A source column's unit/financial definition must be validated against Dev metadata.
-- NUMERIC used without fixed scale to avoid rounding source rates or financial values.

BEGIN;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS risk;
CREATE SCHEMA IF NOT EXISTS analysis;

-- Banking Context / Base Information
CREATE TABLE IF NOT EXISTS core.bank_snapshot (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    dashboard_source_id BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT bank_snapshot_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Profitability / Profitability Indicators
CREATE TABLE IF NOT EXISTS finance.earnings (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    margin NUMERIC,
    roa NUMERIC,
    roe NUMERIC,
    non_ii NUMERIC,
    non_ic NUMERIC,
    non_int_cost NUMERIC,
    eff_mgn_tax NUMERIC,
    roa_ex NUMERIC,
    roe_ex NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT earnings_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Funding Source / Funding Structure
CREATE TABLE IF NOT EXISTS finance.funding (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    loan2deposit NUMERIC,
    nll2deposit NUMERIC,
    nll2coredeposit NUMERIC,
    net_noncore_funding_dependence NUMERIC,
    funding_cost NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT funding_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Capital / Capital & Leverage
CREATE TABLE IF NOT EXISTS finance.capital (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    tier1 NUMERIC,
    tier1_ratio NUMERIC,
    tier1_risk_based_ratio NUMERIC,
    total_risk_based_ratio NUMERIC,
    leverage NUMERIC,
    leverage_asset NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT capital_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Liquidity Risk / Liquidity Indicators
CREATE TABLE IF NOT EXISTS risk.liquidity (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    st2asset NUMERIC,
    sti2asset NUMERIC,
    nll2asset NUMERIC,
    lcr NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT liquidity_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Credit & Asset Quality / Loss Provision
CREATE TABLE IF NOT EXISTS risk.asset_quality (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    cecl NUMERIC,
    loss_rate NUMERIC,
    alll NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT asset_quality_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Balance Sheet Structure / Sector Detail Rollup
CREATE TABLE IF NOT EXISTS finance.balance_sheet_sector (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    sector_code TEXT NOT NULL,
    sector_value NUMERIC,
    sector_face NUMERIC,
    sector_duration NUMERIC,
    sector_gap_ratio NUMERIC,
    sector_rate NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT balance_sheet_sector_pk PRIMARY KEY (bank_id, as_of_date, sector_code)
);

-- Interest Rate Risk / Interest Rate Risk Rollup
CREATE TABLE IF NOT EXISTS risk.interest_rate_risk (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    gap_ratio NUMERIC,
    yield_curve_risk NUMERIC,
    option_risk NUMERIC,
    basis_risk NUMERIC,
    stress_eve NUMERIC,
    stress_dynamic_gap NUMERIC,
    stress_nii12 NUMERIC,
    stress_efficiency_ratio NUMERIC,
    ncua_base_eve_ratio NUMERIC,
    ncua_u300_eve_ratio NUMERIC,
    ncua_duration NUMERIC,
    krd_3m NUMERIC,
    krd_1y NUMERIC,
    krd_3y NUMERIC,
    krd_5y NUMERIC,
    krd_7y NUMERIC,
    krd_10y NUMERIC,
    krd_20y NUMERIC,
    krd_30y NUMERIC,
    gap_asset_nonsens NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT interest_rate_risk_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Interest Rate Risk / Interest Rate Scenario Results
CREATE TABLE IF NOT EXISTS risk.interest_rate_scenario (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    scenario_code TEXT NOT NULL,
    roe NUMERIC,
    gap_ratio NUMERIC,
    repricing_gap_ratio NUMERIC,
    dynamic_gap NUMERIC,
    eve NUMERIC,
    investments NUMERIC,
    nii NUMERIC,
    nii24 NUMERIC,
    ni NUMERIC,
    ni24 NUMERIC,
    roe_ex NUMERIC,
    gap_rsal_ratio NUMERIC,
    repricing_gap_rsal_ratio NUMERIC,
    adj_nii NUMERIC,
    adj_nii24 NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT interest_rate_scenario_pk PRIMARY KEY (bank_id, as_of_date, scenario_code)
);

-- Profitability / Income Attribution
CREATE TABLE IF NOT EXISTS finance.income_attribution (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    ia_option_spread NUMERIC,
    ia_cap_income NUMERIC,
    ia_option_income NUMERIC,
    ia_oas_income NUMERIC,
    ia_un_gain NUMERIC,
    ia_nii NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT income_attribution_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Model Risk & Loss / Loss Distribution & Model Parameters
CREATE TABLE IF NOT EXISTS risk.loss_distribution (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    par_beta_min NUMERIC,
    par_beta_max NUMERIC,
    par_beta_a NUMERIC,
    par_beta_b NUMERIC,
    p95_loss NUMERIC,
    p85_loss NUMERIC,
    loss5_distance NUMERIC,
    loss15_distance NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT loss_distribution_pk PRIMARY KEY (bank_id, as_of_date)
);

-- Bank Rating / CAMELS Model Score
CREATE TABLE IF NOT EXISTS analysis.camels (
    bank_id BIGINT NOT NULL,
    as_of_date DATE NOT NULL,
    score_c NUMERIC,
    score_a NUMERIC,
    score_m NUMERIC,
    score_e NUMERIC,
    score_l NUMERIC,
    score_s NUMERIC,
    cfs_score_c NUMERIC,
    cfs_score_a NUMERIC,
    cfs_score_m NUMERIC,
    cfs_score_e NUMERIC,
    cfs_score_l NUMERIC,
    cfs_score_s NUMERIC,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT camels_pk PRIMARY KEY (bank_id, as_of_date)
);

-- A stable, simple entry point for the current NII/EVE use case.
-- This is a VIEW, not another stored table or a history feature.
CREATE OR REPLACE VIEW risk.bank_base_nii_eve AS
SELECT bank_id, as_of_date, nii, eve, updated_at
FROM risk.interest_rate_scenario
WHERE scenario_code = 'Base';

COMMIT;
