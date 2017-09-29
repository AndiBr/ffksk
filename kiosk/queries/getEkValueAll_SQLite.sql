with a as (
  select
    sum(einkaufspreis)/100.0 as value
  from kiosk_kiosk

  union all

  select
    sum(einkaufspreis) /100.0 as value
  from kiosk_gekauft
)

select
  sum(value) as value
from a