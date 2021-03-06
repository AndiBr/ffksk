select
	datum,
	dayly_value,
	(select 
		sum(b.dayly_value) 
	from (
		select
		  date(gekauftUm) as datum,
		  sum (verkaufspreis)/100.0 as dayly_value
		from kiosk_gekauft a
		join profil_kioskuser b
		  on a.kaeufer_id = b.id
		where b.username <> "Dieb"
		group by datum
		order by gekauftUm asc
	) b where b.datum <= a.datum) as accumulated_value
from (
	select
	  date(gekauftUm) as datum,
	  sum (verkaufspreis)/100.0 as dayly_value
	from kiosk_gekauft a
	join profil_kioskuser b
	  on a.kaeufer_id = b.id
	where b.username <> "Dieb"
	group by datum
	order by gekauftUm asc
) a
where datum > datetime(datetime('now'), '-2 months')
