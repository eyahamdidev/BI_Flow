-- Row reconciliation (spec BO1 acceptance): fact_orders must hold exactly one row per distinct order in staging.
-- A dbt "singular" test passes when this query returns ZERO rows.
with s as (select count(distinct order_id) as n from {{ ref('stg_orders') }}),
     f as (select count(*) as n from {{ ref('fact_orders') }})
select s.n as staging_orders, f.n as fact_orders
from s, f
where s.n <> f.n
