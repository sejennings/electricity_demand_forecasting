SELECT * FROM gridcast.v_daily_load
WHERE region='DUK' AND year='2025' AND month='07'
ORDER BY peak_demand_mw DESC LIMIT 10
