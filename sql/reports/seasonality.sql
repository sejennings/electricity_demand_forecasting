SELECT season, sum(observed_hours) AS observed_hours,
  sum(average_demand_mw * observed_hours)/sum(observed_hours) AS weighted_average_demand_mw
FROM gridcast.v_seasonality WHERE region='DUK' AND year='2025'
GROUP BY season ORDER BY season
