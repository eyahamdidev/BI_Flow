-- One row per order: the table every KPI in configs/kpis/ecommerce.yaml reads.
-- Its column list is a contract with BO5 (`marts.fact_orders` in the dataset YAML); the ETL checks it after build.
--
-- delivery_days : purchase -> delivered to customer, in fractional days (NULL if not delivered)
-- delay_days    : delivered date - estimated date, in whole days (negative = early; NULL if not delivered)
-- is_late       : delivered on a later calendar day than estimated (consistent with delay_days > 0)
-- has_impossible_dates : delivered before purchase (BO3 flags these; kept, not deleted, so KPIs can filter)
select
    o.order_id,
    o.customer_id,
    c.customer_unique_id,
    c.customer_state,
    o.order_status,
    o.order_purchase_timestamp,
    o.order_purchase_timestamp::date as order_date,
    o.order_approved_at,
    o.order_delivered_carrier_date,
    o.order_delivered_customer_date,
    o.order_estimated_delivery_date,

    p.payment_value,
    p.payment_installments,
    p.main_payment_type,
    p.n_payments,

    i.items_value,
    i.freight_value,
    i.n_items,
    i.product_category,

    r.review_score,
    r.n_reviews,

    date_diff('second', o.order_purchase_timestamp, o.order_delivered_customer_date) / 86400.0 as delivery_days,
    date_diff('day', o.order_estimated_delivery_date::date, o.order_delivered_customer_date::date) as delay_days,
    case
        when o.order_delivered_customer_date is null then null
        else o.order_delivered_customer_date::date > o.order_estimated_delivery_date::date
    end as is_late,
    coalesce(o.order_delivered_customer_date < o.order_purchase_timestamp, false) as has_impossible_dates
from {{ ref('stg_orders') }} o
left join {{ ref('dim_customer') }}       c using (customer_id)
left join {{ ref('int_order_payments') }} p using (order_id)
left join {{ ref('int_order_items') }}    i using (order_id)
left join {{ ref('int_order_reviews') }}  r using (order_id)
