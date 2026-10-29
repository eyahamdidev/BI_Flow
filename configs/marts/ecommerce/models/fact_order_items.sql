-- One row per order item (grain: order_id + order_item_id). Use this for item- or seller-level analysis,
-- where an order's several categories/sellers must not be collapsed into one.
select
    i.order_id,
    i.order_item_id,
    i.product_id,
    i.seller_id,
    o.order_purchase_timestamp,
    o.order_purchase_timestamp::date as order_date,
    o.order_status,
    i.shipping_limit_date,
    i.price,
    i.freight_value,
    d.product_category,
    s.seller_state
from {{ ref('stg_order_items') }} i
join {{ ref('stg_orders') }}       o using (order_id)
left join {{ ref('dim_product') }} d using (product_id)
left join {{ ref('dim_seller') }}  s using (seller_id)
