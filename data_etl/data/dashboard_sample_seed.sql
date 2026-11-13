-- ALMAI Dashboard sample data from the provided Excel export.

-- Demonstration only: do not treat Excel row as latest authoritative Dev SQL Server.

-- Transactions and full-set replace prevent stale scenario/sector records.
BEGIN;

INSERT INTO core.bank_snapshot (bank_id, as_of_date, dashboard_source_id)
VALUES (-48858, DATE '2026-06-30', 693257)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    dashboard_source_id = EXCLUDED.dashboard_source_id,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO finance.earnings (bank_id, as_of_date, margin, roa, roe, non_ii, non_ic, non_int_cost, eff_mgn_tax, roa_ex, roe_ex)
VALUES (-48858, DATE '2026-06-30', 0.0406960344142166, -0.00487746685294892, -0.0102112325527202, 26880, 1627248, 0.0976883450182761, 0.199, -0.00467401845208352, -0.00985075336277214)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    margin = EXCLUDED.margin,
    roa = EXCLUDED.roa,
    roe = EXCLUDED.roe,
    non_ii = EXCLUDED.non_ii,
    non_ic = EXCLUDED.non_ic,
    non_int_cost = EXCLUDED.non_int_cost,
    eff_mgn_tax = EXCLUDED.eff_mgn_tax,
    roa_ex = EXCLUDED.roa_ex,
    roe_ex = EXCLUDED.roe_ex,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO finance.funding (bank_id, as_of_date, loan2deposit, nll2deposit, nll2coredeposit, net_noncore_funding_dependence, funding_cost)
VALUES (-48858, DATE '2026-06-30', 1.65916059845322, NULL, NULL, NULL, 0.0104430094139657)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    loan2deposit = EXCLUDED.loan2deposit,
    nll2deposit = EXCLUDED.nll2deposit,
    nll2coredeposit = EXCLUDED.nll2coredeposit,
    net_noncore_funding_dependence = EXCLUDED.net_noncore_funding_dependence,
    funding_cost = EXCLUDED.funding_cost,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO finance.capital (bank_id, as_of_date, tier1, tier1_ratio, tier1_risk_based_ratio, total_risk_based_ratio, leverage, leverage_asset)
VALUES (-48858, DATE '2026-06-30', 17114000, 0.471719955898566, 0.988962727535394, 0.999653279399017, 2.09355242394861, 36280000)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    tier1 = EXCLUDED.tier1,
    tier1_ratio = EXCLUDED.tier1_ratio,
    tier1_risk_based_ratio = EXCLUDED.tier1_risk_based_ratio,
    total_risk_based_ratio = EXCLUDED.total_risk_based_ratio,
    leverage = EXCLUDED.leverage,
    leverage_asset = EXCLUDED.leverage_asset,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO risk.liquidity (bank_id, as_of_date, st2asset, sti2asset, nll2asset, lcr)
VALUES (-48858, DATE '2026-06-30', 0.111669867832145, NULL, NULL, 5.94430707550798)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    st2asset = EXCLUDED.st2asset,
    sti2asset = EXCLUDED.sti2asset,
    nll2asset = EXCLUDED.nll2asset,
    lcr = EXCLUDED.lcr,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO risk.asset_quality (bank_id, as_of_date, cecl, loss_rate, alll)
VALUES (-48858, DATE '2026-06-30', 133387.222702744, 0, 185380)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    cecl = EXCLUDED.cecl,
    loss_rate = EXCLUDED.loss_rate,
    alll = EXCLUDED.alll,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO risk.interest_rate_risk (bank_id, as_of_date, gap_ratio, yield_curve_risk, option_risk, basis_risk, stress_eve, stress_dynamic_gap, stress_nii12, stress_efficiency_ratio, ncua_base_eve_ratio, ncua_u300_eve_ratio, ncua_duration, krd_3m, krd_1y, krd_3y, krd_5y, krd_7y, krd_10y, krd_20y, krd_30y, gap_asset_nonsens)
VALUES (-48858, DATE '2026-06-30', 0.0881604272815841, NULL, -0.0000755105145612, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, -0.0823556607827961, 0.178808658417514, 1.37215210786354, -0.151615688359184, 1.47482418022932, 2.67150415566516, 1.53575484885431, 0.0878697217937214, 2140594.33504579)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    gap_ratio = EXCLUDED.gap_ratio,
    yield_curve_risk = EXCLUDED.yield_curve_risk,
    option_risk = EXCLUDED.option_risk,
    basis_risk = EXCLUDED.basis_risk,
    stress_eve = EXCLUDED.stress_eve,
    stress_dynamic_gap = EXCLUDED.stress_dynamic_gap,
    stress_nii12 = EXCLUDED.stress_nii12,
    stress_efficiency_ratio = EXCLUDED.stress_efficiency_ratio,
    ncua_base_eve_ratio = EXCLUDED.ncua_base_eve_ratio,
    ncua_u300_eve_ratio = EXCLUDED.ncua_u300_eve_ratio,
    ncua_duration = EXCLUDED.ncua_duration,
    krd_3m = EXCLUDED.krd_3m,
    krd_1y = EXCLUDED.krd_1y,
    krd_3y = EXCLUDED.krd_3y,
    krd_5y = EXCLUDED.krd_5y,
    krd_7y = EXCLUDED.krd_7y,
    krd_10y = EXCLUDED.krd_10y,
    krd_20y = EXCLUDED.krd_20y,
    krd_30y = EXCLUDED.krd_30y,
    gap_asset_nonsens = EXCLUDED.gap_asset_nonsens,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO finance.income_attribution (bank_id, as_of_date, ia_option_spread, ia_cap_income, ia_option_income, ia_oas_income, ia_un_gain, ia_nii)
VALUES (-48858, DATE '2026-06-30', 0.00165986955676228, 617898.137955671, 48051.8045857041, 554497.965569908, 88842.1850156581, 1309290.09312694)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    ia_option_spread = EXCLUDED.ia_option_spread,
    ia_cap_income = EXCLUDED.ia_cap_income,
    ia_option_income = EXCLUDED.ia_option_income,
    ia_oas_income = EXCLUDED.ia_oas_income,
    ia_un_gain = EXCLUDED.ia_un_gain,
    ia_nii = EXCLUDED.ia_nii,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO risk.loss_distribution (bank_id, as_of_date, par_beta_min, par_beta_max, par_beta_a, par_beta_b, p95_loss, p85_loss, loss5_distance, loss15_distance)
VALUES (-48858, DATE '2026-06-30', 10802700.9611221, 20258466.8416095, 5.65223720563283, 2.29533793630632, 0.161991522282823, 0.101946213698256, 0.212113537546422, 0.45496132739044)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    par_beta_min = EXCLUDED.par_beta_min,
    par_beta_max = EXCLUDED.par_beta_max,
    par_beta_a = EXCLUDED.par_beta_a,
    par_beta_b = EXCLUDED.par_beta_b,
    p95_loss = EXCLUDED.p95_loss,
    p85_loss = EXCLUDED.p85_loss,
    loss5_distance = EXCLUDED.loss5_distance,
    loss15_distance = EXCLUDED.loss15_distance,
    updated_at = CURRENT_TIMESTAMP;

INSERT INTO analysis.camels (bank_id, as_of_date, score_c, score_a, score_m, score_e, score_l, score_s, cfs_score_c, cfs_score_a, cfs_score_m, cfs_score_e, cfs_score_l, cfs_score_s)
VALUES (-48858, DATE '2026-06-30', 0.5, 0.5, 5, 3.75, 1.25, 3.25, 0.477657014250408, 0, 0, 0.0405723011698557, 0.111669867832145, 0.0701396023408448)
ON CONFLICT (bank_id, as_of_date) DO UPDATE SET
    score_c = EXCLUDED.score_c,
    score_a = EXCLUDED.score_a,
    score_m = EXCLUDED.score_m,
    score_e = EXCLUDED.score_e,
    score_l = EXCLUDED.score_l,
    score_s = EXCLUDED.score_s,
    cfs_score_c = EXCLUDED.cfs_score_c,
    cfs_score_a = EXCLUDED.cfs_score_a,
    cfs_score_m = EXCLUDED.cfs_score_m,
    cfs_score_e = EXCLUDED.cfs_score_e,
    cfs_score_l = EXCLUDED.cfs_score_l,
    cfs_score_s = EXCLUDED.cfs_score_s,
    updated_at = CURRENT_TIMESTAMP;

DELETE FROM finance.balance_sheet_sector WHERE bank_id = -48858 AND as_of_date = DATE '2026-06-30';

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Loan', 28496037.9543306, 30068987.0999999, 4.92112039369398, 0.135836059178818, 4.665231147994);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Investment', 374200, 374200, 0, 1, 0);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Deposit', 17174972.6825097, 18068354.1899999, 1.49302884148751, 0.270551957946421, 1.09578287368242);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'ST', 3829983.90867498, 3830463.95999999, 0.0856498134640688, 1, 3.69785458281664);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Asset', 34297380.1530056, 35870809.3499999, 4.09842749158411, 0.23397207252411, 4.30554193548883);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'TimeDeposit', 6129396.08953755, 6221721.60999999, 0.76313256731753, 0.651451228982602, 3.02006247472232);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'NMD', 11045576.5929722, 11846632.58, 1.898061872675, 0.0669628765209558, 0.0851723143843801);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Borrowing', 0, NULL, 0, 0, 0);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Liability', 17914995.9525097, 18808377.4599999, 1.4313555880628, 0.270551957946421, 1.05266885031081);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'MMDA', 0, 0, 0, 0, 0);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Saving', 1841255.1205236, 1951757.15, 1.43979514021097, 0.160374350962606, 0.01);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Transaction', 9204321.47244859, 9894875.43, 1.98973467769815, 0.0485375295397525, 0.1);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'NonInterest', 0, 0, 0, 0, 0);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'Equity', 16382384.2004959, 17062431.8899999, 7.01396023408448, 0.191213054524279, 7.89127140300748);

INSERT INTO finance.balance_sheet_sector (bank_id, as_of_date, sector_code, sector_value, sector_face, sector_duration, sector_gap_ratio, sector_rate)
VALUES (-48858, DATE '2026-06-30', 'OBS', 0, 0, 0, 0, 0);

DELETE FROM risk.interest_rate_scenario WHERE bank_id = -48858 AND as_of_date = DATE '2026-06-30';

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'D400', NULL, NULL, NULL, NULL, NULL, 374200, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'D300', -0.018767360355766, 0.365156212533082, 0.247290803805383, 0.0984825520003647, 17602299.3756922, 374200, 1186454.36919203, 2305982.60555658, -330348.695473692, -716784.965588914, -0.0195211918866567, 4.1575130749724, 2.03464401089279, 1097326.60079029, 2121710.15420846);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'D200', -0.0145003435331269, 0.250861921494825, 0.144730818030689, 0.100374606131017, 17627272.0141877, 374200, 1280371.13020935, 2548059.75404758, -255601.499757596, -522424.664461426, -0.0150802074874661, 2.90170924382185, 1.59623971800843, 1190643.94875046, 2364357.22178335);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'D100', -0.0111469272795528, 0.141586065878812, 0.03586697336643, 0.101964744539516, 17272755.694897, 374200, 1359820.47364644, 2748807.66546654, -192538.151648499, -362352.081547452, -0.0113444420540761, 2.03751789412834, 1.14557475710822, 1269374.72042224, 2564198.14926646);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'Base', -0.0102112325527202, 0.0828994444759598, -0.0256911357651265, 0.102599942823719, 16382384.2004959, 374200, 1391523.63690477, 2822248.32376091, -167284.334839273, -303168.628667506, -0.00985075336277214, 1.60461856208362, 0.897105883233432, 1300902.58160729, 2638085.10666964);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'U100', -0.0103306629038119, 0.0601115064895882, -0.0493203644368542, 0.102861546923995, 15185206.1201043, 374200, 1404539.70904173, 2826697.86907187, -156873.2455517, -299280.646061731, -0.00923455020569092, 1.4307199740484, 0.804886644255157, 1313900.19619852, 2642939.01753827);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'U200', -0.0105799659241363, 0.0481706029717117, -0.0612292405228331, 0.10308552162472, 13984437.5016526, 374200, 1415661.29232288, 2823581.25655091, -147954.872235699, -301563.890397388, -0.0087068145502882, 1.33761892841457, 0.760655751239649, 1325034.24528217, 2640088.52523408);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'U300', -0.0108637171077164, 0.0387172496473934, -0.0701110834251357, 0.103298122353321, 12839553.1970756, 374200, 1426220.28102311, 2817832.80237927, -139485.273722505, -305997.586186572, -0.00820586983618348, 1.26504750235711, 0.729115229690582, 1335608.02619751, 2634553.32449852);

INSERT INTO risk.interest_rate_scenario (bank_id, as_of_date, scenario_code, roe, gap_ratio, repricing_gap_ratio, dynamic_gap, eve, investments, nii, nii24, ni, ni24, roe_ex, gap_rsal_ratio, repricing_gap_rsal_ratio, adj_nii, adj_nii24)
VALUES (-48858, DATE '2026-06-30', 'U400', -0.0111341334201248, 0.0309796252843986, -0.0771367932276734, 0.103508968903703, 11772949.5232193, 374200, 1436699.54499736, 2811397.56704941, -131081.590739919, -311023.942262851, -0.00770911625426366, 1.20706249258016, 0.705351336734494, 1346099.51556404, 2628278.2232797);

COMMIT;
