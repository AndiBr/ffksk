from django.db import models
from django.utils import timezone
import datetime
from dateutil import tz
from datetime import date
from django.core.validators import MinValueValidator
from django.db import transaction

from profil.models import KioskUser
from django.db import connection
from django.conf import settings
from django.template.loader import render_to_string
from .queries import readFromDatabase
from django.db.models import Max


# Create your models here.


class Produktpalette(models.Model):
	produktName = models.CharField(max_length=40)
	produktErstellt = models.DateTimeField(auto_now_add=True)
	produktGeaendert = models.DateTimeField(auto_now=True)
	kommentar = models.TextField(max_length=512,blank=True)

	def __str__(self):
		return ('ID ' + str(self.id) + ': ' + self.produktName)


class Kioskkapazitaet(models.Model):
	produktpalette = models.OneToOneField(
		Produktpalette,on_delete=models.CASCADE
		,primary_key=True)
	maxKapazitaet = models.IntegerField(validators=[MinValueValidator(0)])
	schwelleMeldung = models.IntegerField(validators=[MinValueValidator(0)])
	paketgroesseInListe = models.IntegerField(validators=[MinValueValidator(0)])

	def __str__(self):
		return(self.produktpalette.produktName +
			", Kapazit"+chr(228)+"t: " + str(self.maxKapazitaet))


class ProduktVerkaufspreise(models.Model):
	produktpalette = models.ForeignKey(
		Produktpalette, on_delete=models.CASCADE)
	verkaufspreis = models.IntegerField(validators=[MinValueValidator(0)])
	gueltigAb = models.DateTimeField(default=timezone.now)

	def __str__(self):
		price = '%.2f' % (self.verkaufspreis/100)
		return(self.produktpalette.produktName + ", " +
			str(price) + " "+chr(8364)+" g"+chr(252)+"ltig ab " + str(self.gueltigAb))

	def getActPrices(produktName):
		verkaufspreis = readFromDatabase('getActPrices',[produktName])
		return(verkaufspreis[0])


class Einkaufsliste(models.Model):
	kiosk_ID = models.AutoField(primary_key=True)
	produktpalette = models.ForeignKey(
		Produktpalette,on_delete=models.CASCADE)
	bedarfErstelltUm = models.DateTimeField(auto_now_add=timezone.now)

	def __str__(self):
		return("[#" + str(self.kiosk_ID) + "] " +
			self.produktpalette.produktName + ", Bedarf angemeldet um " +
			str(self.bedarfErstelltUm))

	def getEinkaufslisteCompressed():
		einkaufsliste = readFromDatabase('getEinkaufslisteCompressed')
		return(einkaufsliste)

	def getEinkaufsliste():
		einkaufsliste = readFromDatabase('getEinkaufsliste')
		return(einkaufsliste)

	# Eine Gruppe in der Einkaufsliste wird zum Einkauf vorgemerkt
	@transaction.atomic
	def einkaufGroupVormerken(ekGroupID,user):
		# Suchen von Gruppen in EinkaufslisteGroups und dann die IDs in Einkaufsliste
		groupEntries = EinkaufslisteGroups.objects.filter(gruppenID=ekGroupID)

		for grEntry in groupEntries:
			grEntryID = grEntry.einkaufslistenItem_id

			ekItem = Einkaufsliste.objects.get(kiosk_ID=grEntryID)
			vg = ZumEinkaufVorgemerkt(kiosk_ID=ekItem.kiosk_ID, bedarfErstelltUm=ekItem.bedarfErstelltUm,
				produktpalette_id=ekItem.produktpalette_id, einkaufsvermerkUm=timezone.now(),
				einkaeufer_id = user)
			vg.save()
			Einkaufsliste.objects.get(kiosk_ID=grEntryID).delete()

		EinkaufslisteGroups.objects.filter(gruppenID=ekGroupID).delete()
		return True

	def getCommentsOnProducts(ekGroupID):
		# Gebe die Kommentare aller Produkte zurueck
		comments = readFromDatabase('getCommentsOnProductsInEkList',[ekGroupID])
		return comments


class EinkaufslisteGroups(models.Model):
	einkaufslistenItem = models.OneToOneField(Einkaufsliste, to_field='kiosk_ID', on_delete=models.CASCADE)
	gruppenID = models.IntegerField()

	def __str__(self):
		return("Element: [#" + str(self.einkaufslistenItem.kiosk_ID) + "] Gruppe " +
			str(self.gruppenID))


class ZumEinkaufVorgemerkt(models.Model):
	kiosk_ID = models.AutoField(primary_key=True)
	produktpalette = models.ForeignKey(
		Produktpalette,on_delete=models.CASCADE)
	bedarfErstelltUm = models.DateTimeField()
	einkaufsvermerkUm = models.DateTimeField(auto_now_add=timezone.now)
	einkaeufer = models.ForeignKey(
		KioskUser,on_delete=models.CASCADE)

	def __str__(self):
		return("[#" + str(self.kiosk_ID) + "] " +
			self.produktpalette.produktName + ", vorgemerkt um " +
			str(self.einkaufsvermerkUm) + ", von " + str(self.einkaeufer))

	def getMyZumEinkaufVorgemerkt(currentUserID):
		persEinkaufsliste = readFromDatabase('getMyZumEinkaufVorgemerkt',[currentUserID])
		return(persEinkaufsliste)


	@transaction.atomic
	def einkaufAnnehmen(form, currentUser):

		finanz = getattr(settings,'FINANZ')
		prodVkPreis = ProduktVerkaufspreise.getActPrices(form.data.get('produktName'))
		prodVkPreis = prodVkPreis.get('verkaufspreis')
		eingabefehler = False

		# Checken, ob Eingaben syntaktisch korrekt sind
		if not form.is_valid():
			errorMsg = "Fehler in Eingabe. Sind die Zahlen korrekt eingegeben?"
			eingabefehler = True
		else:
			userID = int(form['userID'].value())
			produktName = form['produktName'].value()
			anzahlElemente = int(form['anzahlElemente'].value())
			anzahlAngeliefert = int(form['anzahlAngeliefert'].value())
			gesPreis = int(100*float(form['gesPreis'].value()))

			# Pruefen, ob nicht mehr einkgekauft wurde, als auf der Liste stand
			if anzahlAngeliefert > anzahlElemente:
				errorMsg = "Die Anzahl angelieferter Elemente ist zu gro"+chr(223)+"."
				eingabefehler = True

			# Pruefen, dass die Kosten niedrig genug sind, so dass eine Marge zwischen Einkauf und Verkauf von 10 % vorhanden ist.
			minProduktMarge = finanz['minProduktMarge']

			if float(gesPreis) > float(anzahlAngeliefert) * (1-float(minProduktMarge)) * float(prodVkPreis):
				errorMsg = "Die Einkaufskosten sind zu hoch. Produkte k"+chr(246)+"nnen nicht angenommen werden."
				eingabefehler = True

		if eingabefehler == True:

			# Hole den Kioskinhalt
			kioskItems = Kiosk.getKioskContent()
			# Einkaufsliste abfragen
			einkaufsliste = Einkaufsliste.getEinkaufsliste()

			# Bei Eingabefehler, Eine Alert-Meldung zurueck, dass Eingabe falsch ist
			return render_to_string('kiosk/fehler_message.html', {'message':errorMsg, 'user':currentUser, 'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})
			# Hier am besten die <form> aufloesen und das manuell bauen, POST wie oben GET nutzen, der Token muss in die uebergebenen Daten im JavaScript mit rein.

		else:

			# Wenn Eingabe passt, dann wird der Einkaufspreis errechnet, zu den Produkten geschrieben und die Produkte in das Kiosk gelegt. Geldueberweisung von der Bank an den Einkaeufer

			# Einkaufspreis berechnen
			prodEkPreis = int(gesPreis / anzahlAngeliefert)
			datum = timezone.now()

			angeliefert = ZumEinkaufVorgemerkt.objects.filter(einkaeufer__id=userID,
				produktpalette__produktName=produktName).order_by('kiosk_ID')[:anzahlAngeliefert]

			# Eintragen der Werte und Schreiben ins Kiosk
			for an in angeliefert:

				k = Kiosk(kiosk_ID=an.kiosk_ID,bedarfErstelltUm=an.bedarfErstelltUm,
				produktpalette_id=an.produktpalette_id, einkaufsvermerkUm=an.einkaufsvermerkUm,
				einkaeufer_id = an.einkaeufer_id, geliefertUm = datum,
				verwalterEinpflegen_id = currentUser.id, einkaufspreis = prodEkPreis)
				# Aufpassen, dass dann ein zweistelliger Nachkommawert eingetragen wird!
				k.save()
				an.delete()

			# Gewinn und Gesamtrechnung berechnen
			gewinnEK = finanz['gewinnEK']
			provision = int(((float(prodVkPreis) * float(anzahlAngeliefert)) - float(gesPreis)) * float(gewinnEK))
			gesPreis = gesPreis + provision


			# Geldueberweisung von der Bank an den Einkaeufer
			userBank = KioskUser.objects.get(username='Bank')
			userAnlieferer = KioskUser.objects.get(id=userID)
			GeldTransaktionen.doTransaction(userBank,userAnlieferer,gesPreis,datum,
			"Erstattung Einkauf " + produktName + " (" + str(anzahlAngeliefert) + "x)" )#" um " + str(datum.astimezone(tz.tzlocal())))
			# Aufpassen, dass dann ein zweistelliger Nachkommawert eingetragen wird!

			# Hole den Kioskinhalt
			kioskItems = Kiosk.getKioskContent()
			# Einkaufsliste abfragen
			einkaufsliste = Einkaufsliste.getEinkaufsliste()

			return render_to_string('kiosk/einkauf_angenommen_page.html',
				{'gesPreis':gesPreis/100, 'user':currentUser,'userAnlieferer':userAnlieferer,
				'produktName':produktName,'anzahlElemente':anzahlElemente,'kioskItems': kioskItems,
					'einkaufsliste': einkaufsliste})


class Kiosk(models.Model):
	kiosk_ID = models.AutoField(primary_key=True)
	produktpalette = models.ForeignKey(
		Produktpalette,on_delete=models.CASCADE)
	bedarfErstelltUm = models.DateTimeField()
	einkaufsvermerkUm = models.DateTimeField()
	einkaeufer = models.ForeignKey(
		KioskUser,on_delete=models.CASCADE,related_name='kiosk_einkaeufer')
	geliefertUm = models.DateTimeField(auto_now_add=timezone.now)
	verwalterEinpflegen = models.ForeignKey(
		KioskUser,on_delete=models.CASCADE,related_name='kiosk_verwalter')
	einkaufspreis = models.IntegerField(validators=[MinValueValidator(0)])

	def __str__(self):
		price = '%.2f' % (self.einkaufspreis/100)
		return("[#" + str(self.kiosk_ID) + "] " +
			self.produktpalette.produktName + ", EK: " +
			str(price) + " "+chr(8364)+", um " +
			str(self.geliefertUm) + ', von ' + str(self.einkaeufer) + ' (' + str(self.verwalterEinpflegen) + ')')

	def getKioskContent():
		kioskItems = readFromDatabase('getKioskContent')
		return(kioskItems)

	def getKioskContentForInventory():
		kioskItems = readFromDatabase('getKioskContentForInventory')
		return(kioskItems)	

	# Kauf eines Produkts auf 'kauf_page'
	@transaction.atomic
	def buyItem(wannaBuyItem,user):
		# Suchen eines Produkts in Tabelle 'Kiosk' zwischenspeichern und loeschen
		item = Kiosk.objects.filter(produktpalette__produktName=wannaBuyItem)[:1].get()
		Kiosk.objects.get(kiosk_ID=item.pk).delete()

		# Abfrage des aktuellen Verkaufspreis fuer das Objekt
		actPrices = ProduktVerkaufspreise.getActPrices(wannaBuyItem)
		actPrices = actPrices.get('verkaufspreis')

		# Ablage des Kaufs in Tabelle 'Gekauft'
		g = Gekauft(kiosk_ID=item.kiosk_ID, produktpalette=item.produktpalette,
			bedarfErstelltUm=item.bedarfErstelltUm, einkaufsvermerkUm=item.einkaufsvermerkUm,
			einkaeufer=item.einkaeufer, geliefertUm=item.geliefertUm,
			verwalterEinpflegen=item.verwalterEinpflegen, einkaufspreis=item.einkaufspreis,
			gekauftUm = timezone.now(), kaeufer = user, verkaufspreis=actPrices)

		# Automatische Geldtransaktion vom User zur Bank
		userBank = KioskUser.objects.get(username='Bank')
		GeldTransaktionen.doTransaction(g.kaeufer,userBank,g.verkaufspreis,g.gekauftUm,
			"Kauf " + g.produktpalette.produktName)# + " um " + str(g.gekauftUm.astimezone(tz.tzlocal())))

		g.save()
		
		return True


class Gekauft(models.Model):
	kiosk_ID = models.AutoField(primary_key=True)
	produktpalette = models.ForeignKey(
		Produktpalette,on_delete=models.CASCADE)
	bedarfErstelltUm = models.DateTimeField()
	einkaufsvermerkUm = models.DateTimeField()
	einkaeufer = models.ForeignKey(
		KioskUser,on_delete=models.CASCADE,related_name='gekauft_einkaeufer')
	geliefertUm = models.DateTimeField()
	verwalterEinpflegen = models.ForeignKey(
		KioskUser,on_delete=models.CASCADE,related_name='gekauft_verwalter')
	einkaufspreis = models.IntegerField(validators=[MinValueValidator(0)])
	gekauftUm = models.DateTimeField(auto_now_add=timezone.now)
	kaeufer = models.ForeignKey(
		KioskUser,on_delete=models.CASCADE,related_name='gekauft_kaeufer')
	# Verkaufspreis ist eigentlich nicht noetig, ergibt sich aus Relationen, die Dokumentationstabellen sollen aber sicherheitshalber diese Info speichern (zum Schutz vor Loesuchungen in anderen Tabellen).
	verkaufspreis = models.IntegerField(validators=[MinValueValidator(0)])

	def __str__(self):
		price = '%.2f' % (self.verkaufspreis/100)
		return("[#" + str(self.kiosk_ID) + "] " +
			self.produktpalette.produktName + ", VK: " +
			str(price) + " "+chr(8364)+", gekauft von " +
			str(self.kaeufer) + " um " + str(self.gekauftUm))


class GeldTransaktionen(models.Model):
	AutoTrans_ID = models.AutoField(primary_key=True)
	vonnutzer = models.ForeignKey(
		KioskUser, on_delete=models.CASCADE,related_name='nutzerVon')
	zunutzer = models.ForeignKey(
		KioskUser, on_delete=models.CASCADE,related_name='nutzerZu')
	betrag = models.IntegerField(validators=[MinValueValidator(0)])
	kommentar = models.TextField(max_length=512,blank=True)
	datum = models.DateTimeField(auto_now_add=timezone.now)

	def __str__(self):
		betr = '%.2f' % (self.betrag/100)
		return("[#" +
			str(self.AutoTrans_ID) + "] " + str(betr) +
			" "+chr(8364)+" von " + str(self.vonnutzer) + " an " +
			str(self.zunutzer))

	# Abfrage der Anzahl aller Transaktionen
	def getLengthOfAllTransactions(user):
		allTransactions = readFromDatabase('getLengthOfAllTransactions',[user.id, user.id])
		return(allTransactions)

	# Abfrage einer Auswahl an Transaktionen eines Nutzers zur Anzeige bei den Kontobewegungen
	def getTransactions(user,page,limPP,maxIt):
		if int(page)*int(limPP) > int(maxIt):
			limPPn = int(limPP) - (int(page)*int(limPP) - int(maxIt))
		else:
			limPPn = limPP

		allTransactions = readFromDatabase('getTransactions',
			[user.id, user.id, int(page)*int(limPP), limPPn])

		return(allTransactions)


	@transaction.atomic
	def doTransaction(vonnutzer,zunutzer,betrag,datum, kommentar):
		t = GeldTransaktionen(vonnutzer=vonnutzer, zunutzer=zunutzer, betrag = betrag, datum=datum, kommentar=kommentar)

		# Besorge den Kontostand des 'vonNutzer' und addiere neuen Wert
		print(t.betrag)
		vonNutzerKonto = Kontostand.objects.get(nutzer_id=t.vonnutzer)
		vonNutzerKonto.stand = vonNutzerKonto.stand - t.betrag
		vonNutzerKonto.save()

		# Besorge den Kontostand des 'zuNutzer' und addiere neuen Wert
		zuNutzerKonto = Kontostand.objects.get(nutzer_id=t.zunutzer)
		zuNutzerKonto.stand = zuNutzerKonto.stand + t.betrag
		zuNutzerKonto.save()

		t.save()


	@transaction.atomic
	def makeManualTransaktion(form,currentUser):
		# Durchfuehren einer Ueberweisung aus dem Admin-Bereich

		idFrom = int(form['idFrom'].value())
		idTo = int(form['idTo'].value())
		betrag = int(100*float(form['betrag'].value()))
		kommentar = form['kommentar'].value()

		userFrom = KioskUser.objects.get(id=idFrom)
		userTo = KioskUser.objects.get(id=idTo)

		kommentar = kommentar + ' (' + userFrom.username + ' --> ' + userTo.username + ')'

		GeldTransaktionen.doTransaction(vonnutzer=userFrom, zunutzer=userTo,
			betrag=betrag, datum=timezone.now(), kommentar=kommentar)

		return render_to_string('kiosk/transaktion_done_page.html',
			{'userFrom':userFrom, 'user':currentUser,'userTo':userTo,
			'betrag':betrag/100})


	@transaction.atomic
	def makeEinzahlung(form,currentUser):
		# Durchfuehren einer Einzahlung bzw. Auszahlung (GegenUser ist 'Bargeld')
		barUser = KioskUser.objects.get(username='Bargeld')

		if form['typ'].value() == 'Einzahlung':
			idFrom = barUser.id
			idTo = int(form['idUser'].value())
			ezaz = 'eingezahlt'
		else:
			idTo = barUser.id
			idFrom = int(form['idUser'].value())
			ezaz = 'ausgezahlt'

		betrag = int(100*float(form['betrag'].value()))
		kommentar = form['kommentar'].value()

		userFrom = KioskUser.objects.get(id=idFrom)
		userTo = KioskUser.objects.get(id=idTo)

		kommentar = kommentar + ' (' + form['typ'].value() + ')'

		GeldTransaktionen.doTransaction(vonnutzer=userFrom, zunutzer=userTo,
			betrag=betrag, datum=timezone.now(), kommentar=kommentar)

		return render_to_string('kiosk/einzahlung_done_page.html',
			{'ezaz':ezaz, 'user':currentUser,
			'betrag':betrag/100})




# Aus den GeldTransaktionen ergibt sich eigentlich der Kontostand, aber zur Sicherheit (Loeschen von Tabelleneintraegen, Bugs, etc.) wird der Kontostand zusaetzlich gespeichert, bei jeder Transaktion wird dem aktuellen Stand die neue Transaktion angerechnet. Keine weitere Kopplung -> andere Tabellen koennen crashen, ohne den Kontostand zu beschaedigen.
class Kontostand(models.Model):
	nutzer = models.OneToOneField(KioskUser, on_delete=models.CASCADE,
		primary_key = True)
	stand = models.IntegerField()

	def __str__(self):
		stnd = '%.2f' % (self.stand/100)
		return(str(self.nutzer) + ": " + str(stnd) + "  "+chr(8364))



# At inventory, here the paid but not taken items are registered
class ZuVielBezahlt(models.Model):
	produkt = models.ForeignKey(
		Produktpalette,on_delete=models.CASCADE)
	datum = models.DateTimeField(auto_now_add=True)
	preis = models.IntegerField()


	def __str__(self):
		preis = '%.2f' % (self.preis/100)
		return(self.produkt.produktName + ": " + str(preis) + "  "+chr(8364))


	@transaction.atomic
	def makeInventory(request, currentUser, inventoryList):
		report = []
		# Go through all items in the kiosk
		for item in inventoryList:
			# Check, if the item should be considered
			if not request.POST.get(item["checkbutton_id_name"]) is None:
				# Get the should- and is- count of the item
				isVal = int(request.POST.get(item["count_id_name"]))
				shouldVal = item["anzahl"]
				
				# Check, if stock is higher, lower or equal
				if shouldVal == isVal:
					diff = 0
					report.append({'id': item["id"], 
						'produkt_name': item["produkt_name"], 
						'verkaufspreis_ct': item["verkaufspreis_ct"],
						'verlust': False,
						'anzahl': diff,
						'message': 'OK.'})

				if shouldVal < isVal:
					# Too much has been bought. Now, a new item will be created in the list and be pushed to the kiosk. Notice in table of to much bought items will be given.
					diff = isVal - shouldVal

					datum = timezone.now()
					p = Produktpalette.objects.get(id=item["id"])
					maxGroup = EinkaufslisteGroups.objects.all().aggregate(Max('gruppenID'))
					maxGroup = maxGroup["gruppenID__max"] + 1	

					for i in range(0,diff):
						e = Einkaufsliste(produktpalette = p)
						e.save()
						eg = EinkaufslisteGroups(einkaufslistenItem=e,gruppenID=maxGroup)
						eg.save()
						ok = Einkaufsliste.einkaufGroupVormerken(maxGroup,currentUser.id)

						z = ZuVielBezahlt(produkt = p, datum = datum, preis = int(item["verkaufspreis_ct"]))
						z.save()

					angeliefert = ZumEinkaufVorgemerkt.objects.filter(einkaeufer__id=currentUser.id,
						produktpalette__id=item["id"]).order_by('kiosk_ID')[:diff]

					# Eintragen der Werte und Schreiben ins Kiosk
					for an in angeliefert:
						k = Kiosk(kiosk_ID=an.kiosk_ID,bedarfErstelltUm=an.bedarfErstelltUm,
							produktpalette_id=an.produktpalette_id, einkaufsvermerkUm=an.einkaufsvermerkUm,
							einkaeufer_id = an.einkaeufer_id, geliefertUm = datum,
							verwalterEinpflegen_id = currentUser.id, einkaufspreis = 0)
						k.save()
						an.delete()


					report.append({'id': item["id"], 
						'produkt_name': item["produkt_name"], 
						'verkaufspreis_ct': item["verkaufspreis_ct"],
						'verlust': False,
						'anzahl': diff,
						'message': str(diff) + ' zu viel gekauft.'})
				
				if shouldVal > isVal:
					# Items have not been payed. Now, the "thieve" "buys" them.
					diff = shouldVal-isVal
					user = KioskUser.objects.get(username='Dieb')
					buyItem = item["produkt_name"]

					for x in range(0,diff):
						buySuccess = Kiosk.buyItem(buyItem,user)

					report.append({'id': item["id"], 
						'produkt_name': item["produkt_name"], 
						'verkaufspreis_ct': item["verkaufspreis_ct"],
						'verlust': True,
						'anzahl': diff,
						'message': str(diff) + ' nicht bezahlt. Nun "kauft" diese der Dieb.'})

		return(report)