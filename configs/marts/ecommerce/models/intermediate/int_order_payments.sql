-- One row per order. An order can be paid in several parts (e.g. voucher + credit card).
-- payment_value        = total paid
-- main_payment_type    = the type that paid the largest amount (ties broken alphabetically -> deterministic)
-- payment_installments = largest installment count among the order's payments
with by_type as (
    select order_id, payment_type, sum(payment_value) as type_value
    from {{ ref('stg_order_payments') }}
    group by order_id, payment_type
),
main_type as (
    select order_id, payment_type as main_payment_type
    from (
        select *, row_number() over (partition by order_id order by type_value desc, payment_type) as rn
        from by_type
    )
    where rn = 1
)
select
    p.order_id,
    sum(p.payment_value)        as payment_value,
    max(p.payment_installments) as payment_installments,
    count(*)                    as n_payments,
    any_value(m.main_payment_type) as main_payment_type
from {{ ref('stg_order_payments') }} p
join main_type m using (order_id)
group by p.order_id
