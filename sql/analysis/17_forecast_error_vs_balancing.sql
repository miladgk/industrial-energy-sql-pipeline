-- =============================================================
-- 17_forecast_error_vs_balancing.sql
-- What happens on the grid when the day-ahead forecasts are wrong?
--
-- net_surprise_mw = wind error - consumption error (day-ahead):
--   negative: less wind and/or more demand than forecast (system short)
--   positive: more wind and/or less demand than forecast (system long)
-- Slots are grouped in 500 MW bins (open-ended below -1500 and from
-- +1500 up). Each bin shows averages of:
--   mfrr_need   Fingrid's estimate of the mFRR energy needed (377)
--   mfrr_up     activated upward mFRR, published as values >= 0 (375)
--   mfrr_down   activated downward mFRR, published as values <= 0 (376)
-- and the median imbalance price (319). Net activation is up + down.
--
-- This is an association, not a cause: market parties trade after the
-- day-ahead forecast, and many other things move the balance.
--
-- Parameters: start, end (timestamptz, end exclusive)
-- Techniques: self-join of a view, LEFT JOINs, FLOOR binning with
--             LEAST/GREATEST, PERCENTILE_CONT, corr() aggregate
-- =============================================================

WITH surprise AS (
    SELECT w.start_time,
           w.error_mw - c.error_mw AS net_surprise_mw
    FROM forecast_vs_actual w
    JOIN forecast_vs_actual c
      ON c.start_time = w.start_time
     AND c.variable = 'consumption'
     AND c.product  = 'day_ahead'
     -- implied by the join, but PostgreSQL does not carry a range across it: without this
     -- line the consumption side reads the whole history, not just the window
     AND c.start_time >= %(start)s
     AND c.start_time <  %(end)s
    WHERE w.variable = 'wind'
      AND w.product  = 'day_ahead'
      AND w.start_time >= %(start)s
      AND w.start_time <  %(end)s
),
joined AS (
    SELECT s.start_time,
           s.net_surprise_mw,
           nd.value  AS mfrr_need_mw,
           up.value  AS mfrr_up_mw,
           dn.value  AS mfrr_down_mw,
           px.value  AS imbalance_price
    FROM surprise s
    LEFT JOIN fingrid_observation nd ON nd.dataset_id = 377 AND nd.start_time = s.start_time
    LEFT JOIN fingrid_observation up ON up.dataset_id = 375 AND up.start_time = s.start_time
    LEFT JOIN fingrid_observation dn ON dn.dataset_id = 376 AND dn.start_time = s.start_time
    LEFT JOIN fingrid_observation px ON px.dataset_id = 319 AND px.start_time = s.start_time
),
binned AS (
    SELECT joined.*,
           LEAST(GREATEST(FLOOR(net_surprise_mw / 500) * 500, -2000), 1500) AS bin
    FROM joined
)
SELECT
    CASE WHEN bin = -2000 THEN NULL ELSE bin END        AS bin_from_mw,
    CASE WHEN bin =  1500 THEN NULL ELSE bin + 500 END  AS bin_to_mw,
    COUNT(*)                                            AS slots,
    AVG(net_surprise_mw)                                AS mean_net_surprise_mw,
    AVG(mfrr_need_mw)                                   AS mean_mfrr_need_mw,
    AVG(mfrr_up_mw)                                     AS mean_mfrr_up_mw,
    AVG(mfrr_down_mw)                                   AS mean_mfrr_down_mw,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY imbalance_price) AS median_imbalance_price,
    AVG(imbalance_price)                                AS mean_imbalance_price,
    (SELECT corr(net_surprise_mw, mfrr_need_mw) FROM joined)              AS r_surprise_vs_mfrr_need,
    (SELECT corr(net_surprise_mw, mfrr_up_mw + mfrr_down_mw) FROM joined) AS r_surprise_vs_net_mfrr,
    (SELECT corr(net_surprise_mw, imbalance_price) FROM joined)           AS r_surprise_vs_price
FROM binned
GROUP BY bin
ORDER BY bin;
