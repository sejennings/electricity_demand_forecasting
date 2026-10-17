CREATE OR REPLACE VIEW gridcast.v_daily_load AS
WITH ranked AS (
  SELECT region, year, month, timestamp_utc, demand_mw,
    CAST(timestamp_utc AS date) AS demand_date,
    row_number() OVER (
      PARTITION BY region, year, month, CAST(timestamp_utc AS date)
      ORDER BY demand_mw DESC, timestamp_utc ASC
    ) AS peak_rank
  FROM gridcast.hourly_demand
)
SELECT region, year, month, demand_date, count(*) AS observed_hours,
  avg(demand_mw) AS average_demand_mw, min(demand_mw) AS minimum_demand_mw,
  max(demand_mw) AS peak_demand_mw, sum(demand_mw) AS observed_energy_mwh,
  min(CASE WHEN peak_rank = 1 THEN timestamp_utc END) AS peak_time_utc
FROM ranked
GROUP BY region, year, month, demand_date
