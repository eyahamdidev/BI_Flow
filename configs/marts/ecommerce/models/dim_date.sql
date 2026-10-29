-- One row per calendar day between the first and last purchase (a "date spine": no gaps, even on days
-- without orders, so charts and joins by day never silently drop a day).
with bounds as (
    select
        min(order_purchase_timestamp)::date as lo,
        max(order_purchase_timestamp)::date as hi
    from {{ ref('stg_orders') }}
),
days as (
    select unnest(generate_series(lo::timestamp, hi::timestamp, interval 1 day))::date as date_day
    from bounds
)
select
    date_day,
    year(date_day)                       as year,
    quarter(date_day)                    as quarter,
    month(date_day)                      as month,
    strftime(date_day, '%Y-%m')          as year_month,
    date_trunc('month', date_day)::date  as month_start,
    isodow(date_day)                     as iso_day_of_week,
    isodow(date_day) in (6, 7)           as is_weekend
from days
