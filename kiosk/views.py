from django.shortcuts import redirect, render, render_to_response, HttpResponseRedirect, reverse
from django.db.models import Count
from django.db import connection
from .models import Kontostand, Kiosk, Einkaufsliste, ZumEinkaufVorgemerkt, Gekauft, Kontakt_Nachricht, Start_News
from .models import GeldTransaktionen, ProduktVerkaufspreise, ZuVielBezahlt, Produktkommentar, Produktpalette
from profil.models import KioskUser
from profil.forms import UserErstellenForm
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse
from django.forms import formset_factory

from slackclient import SlackClient

from .forms import TransaktionenForm, EinzahlungenForm, RueckbuchungForm, Kontakt_Nachricht_Form
from django.contrib.auth.decorators import login_required, permission_required
import math
from django.conf import settings
from django.utils import timezone
import pytz
import datetime
from .queries import readFromDatabase
from django.contrib.auth import login, authenticate
import re

from django.db import transaction

from .bot import checkKioskContentAndFillUp, slack_PostNewProductsInKioskToChannel, slack_PostTransactionInformation, slack_TestMsgToUser, slack_SendMsg

from .charts import *

from profil.tokens import account_activation_token
from django.contrib.sites.shortcuts import get_current_site
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_text


# Create your views here.

def start_page(request):
	
	# Einkaeufer der Woche
	data = readFromDatabase('getEinkaeuferDerWoche')
	bestBuyers = []
	for item in data:
		bestBuyers.append(item['first_name'] + ' ' + item['last_name'])
	bestBuyers = ', '.join(bestBuyers)

	# Verwalter der Woche
	data = readFromDatabase('getVerwalterDerWoche')
	bestVerwalter = []
	for item in data:
		bestVerwalter.append(item['first_name'] + ' ' + item['last_name'])
	bestVerwalter = ', '.join(bestVerwalter)

	# Administrator
	data = KioskUser.objects.filter(visible=True, rechte='Admin')
	admins = []
	for item in data:
		admins.append(item.first_name + ' ' + item.last_name)
	admins = ', '.join(admins)

	# Verwalter
	data = KioskUser.objects.filter(visible=True, rechte='Accountant')
	accountants = []
	for item in data:
		accountants.append(item.first_name + ' ' + item.last_name)
	accountants = ', '.join(accountants)


	# Get the news: starred + latest 3
	newsStarred = Start_News.objects.filter(visible=True,starred=True).order_by('-date')
	news = Start_News.objects.filter(visible=True,starred=False).order_by('-date')[:3]

	news = list(news.values())
	newsStarred = list(newsStarred.values())
	news = news + newsStarred
	news = sorted(news, key=lambda k: k['date'], reverse=True) 
	# Add TimeZone information: It is stored as UTC-Time in the SQLite-Database
	for k,v in enumerate(news):
		#news[k]['date'] = pytz.timezone('UTC').localize(v['date'])
		#news[k]['created'] = pytz.timezone('UTC').localize(v['created'])
		# Add enumerator
		news[k]['html_id'] = 'collapse_'+str(k)


	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()
 
	return render(request, 'kiosk/start_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'bestBuyers': bestBuyers, 'bestVerwalter': bestVerwalter, 
		'admins': admins, 'accountants': accountants, 
		'chart_DaylyVkValue': Chart_UmsatzHistorie(), 
		'news': news,
		'excludeTopIcon': True,
		})


@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def imkiosk_page(request):
	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/imKiosk_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def offeneEkListe_page(request):
	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/offeneEkListe_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


def datenschutz_page(request):

	# Get the contact data for the impressum
	datenschutz = getattr(settings,'DATENSCHUTZ')

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()
	return render(request, 'kiosk/datenschutz_page.html', {'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste, 'datenschutz': datenschutz})


def kontakt_page(request):

	successMsg = None
	errorMsg = None

	if request.method == "POST":

		form = Kontakt_Nachricht_Form(request.POST)

		if form.is_valid():
			try:
				data = KioskUser.objects.filter(visible=True, rechte='Admin')
				msg = 'Es kam eine neue Nachricht '+chr(252)+'ber das Kontaktformular herein. Bitte k'+chr(252)+'mmere dich im Admin-Bereich um diese Anfrage.'
				for u in data:
					slack_SendMsg(msg, user=u)

				form.save()
				successMsg = 'Deine Nachricht wurde an die Administratoren der Webseite gesendet. Dir wird so schnell wie m'+chr(246)+'glich an die E-Mail-Adresse "'+form.cleaned_data['email']+'" geantwortet. Bitte vergewissere dich, dass diese Adresse korrekt ist.'
				form = Kontakt_Nachricht_Form()

			except:
				errorMsg = 'Interner Fehler beim Speichern der Nachricht. Benutze alternativ die angegebene E-Mail-Adresse im Impressum.'

	else:
		# Load the contact formular
		form = Kontakt_Nachricht_Form()

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()
	return render(request, 'kiosk/kontakt_page.html', {'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste, 'form': form, 'successMsg': successMsg, 'errorMsg': errorMsg})


def impressum_page(request):

	# Get the contact data for the impressum
	impressum = getattr(settings,'IMPRESSUM')

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()
	return render(request, 'kiosk/impressum_page.html', {'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste, 'impressum': impressum,})



@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def home_page(request):
	currentUser = request.user
	kontostand = Kontostand.objects.get(nutzer__username=request.user).stand / 100.0

	# Hole die eigene Liste, welche einzukaufen ist
	persEinkaufsliste = ZumEinkaufVorgemerkt.getMyZumEinkaufVorgemerkt(currentUser.id)

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/home_page.html', 
		{'currentUser': currentUser, 'kontostand': kontostand, 'persEinkaufsliste': persEinkaufsliste,
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def kauf_page(request):
	if request.method == "POST":

		if 'buyAndDonate' in request.POST.keys():
			buyAndDonate = True
		else:
			buyAndDonate = False

		wannaBuyItem = request.POST.get("produktName")
		retVal = Kiosk.buyItem(wannaBuyItem,request.user,gekauft_per='web', buyAndDonate=buyAndDonate)
		buySuccess = retVal['success']

		retVal['msg'] = retVal['msg'][-1]
		request.session['buy_data'] = retVal

		if buySuccess:
			# Ueberpruefung vom Bot, ob Einkaeufe erledigt werden muessen. Bei Bedarf werden neue Listen zur Einkaufsliste hinzugefuegt.
			checkKioskContentAndFillUp()

			return HttpResponseRedirect(reverse('gekauft_page'))

		return(HttpResponseRedirect(reverse('kauf_abgelehnt_page')))


	else:
		# Hole den Kioskinhalt
		msg = ''
		allowed = True
		currentUser = request.user
		kontostand = Kontostand.objects.get(nutzer__username=request.user).stand / 100.0

		# Check, ob der Kontostand noch positiv ist.
		# Auser der Dieb, dieser hat kein Guthaben und darf beliebig negativ werden.
		if kontostand <=0 and not currentUser.username=='Dieb':
			msg = 'Dein Kontostand ist zu niedrig. Bitte wieder beim Admin einzahlen.'
			allowed = False

		# Kiosk Content for Buying
		kioskItemsToBuy = readFromDatabase('getKioskContentToBuy')
		# Delete values that are zero
		kioskItemsToBuy = [x for x in kioskItemsToBuy if x['ges_available']>0]
		
		# Einkaufsliste abfragen
		einkaufsliste = Einkaufsliste.getEinkaufsliste()
		# Hole den Kioskinhalt
		kioskItems = Kiosk.getKioskContent()

		return render(request, 'kiosk/kauf_page.html', 
			{'currentUser': currentUser, 'kontostand': kontostand, 'kioskItems': kioskItems, 'kioskItemsToBuy': kioskItemsToBuy
			, 'einkaufsliste': einkaufsliste, 'msg': msg, 'allowed': allowed})


@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def gekauft_page(request):

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()
	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	# Get the session data with details
	if 'buy_data' in request.session.keys():
		buy_data = request.session['buy_data']
		del request.session['buy_data']
	else:
		return HttpResponseRedirect(reverse('kauf_page'))

	# Get the current account
	currentUser = request.user
	account = Kontostand.objects.get(nutzer__username=request.user).stand / 100.0

	return render(request,'kiosk/gekauft_page.html',{'kioskItems': kioskItems
			, 'einkaufsliste': einkaufsliste, 'product': buy_data['product'], 
			'price': buy_data['price'], 'account': account, 
			'hasDonated': buy_data['hasDonated'], 'donation': buy_data['donation']})


@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def kauf_abgelehnt_page(request):

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()
	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	# Get the session data with details
	if 'buy_data' in request.session.keys():
		buy_data = request.session['buy_data']
		del request.session['buy_data']
	else:
		return HttpResponseRedirect(reverse('kauf_page'))

	# Get the current account
	currentUser = request.user
	account = Kontostand.objects.get(nutzer__username=request.user).stand / 100.0

	return render(request,'kiosk/kauf_abgelehnt_page.html',{'kioskItems': kioskItems
			, 'einkaufsliste': einkaufsliste, 'product': buy_data['product'], 
			'msg': buy_data['msg'], 'account': account, })



def kontobewegungen_page(request):
	s = 1
	return kontobewegungen_page_next(request,s)

@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def kontobewegungen_page_next(request,s):
	# Rufe alle Kontobewegungen ab, sowohl automatisch als auch manuell
	currentUser = request.user
	
	views = getattr(settings,'VIEWS')
	entriesPerPage = views['itemsInKontobewegungen']
	numTransactions = GeldTransaktionen.getLengthOfAllTransactions(request.user)
	try:
		numTransactions = numTransactions[0]["numTransactions"]
	except KeyError:
		numTransactions = numTransactions[0]["numtransactions"]
	
	maxPages = int(math.ceil(numTransactions/entriesPerPage))
	prevpage = int(s) - 1
	nextpage = int(s) + 1

	kontobewegungen = GeldTransaktionen.getTransactions(request.user,s,entriesPerPage,numTransactions)
	kontostand = Kontostand.objects.get(nutzer__username=request.user).stand / 100.0

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request,'kiosk/kontobewegungen_page.html',
		{'currentUser': currentUser, 'kontostand': kontostand, 'kontobewegungen': kontobewegungen,
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste, 
		'maxpage': maxPages, 'prevpage': prevpage, 'nextpage':nextpage})


@login_required
@permission_required('profil.do_einkauf',raise_exception=True)
def einkauf_vormerk_page(request):
	# Vormerken von Einkaeufen

	currentUser = request.user
	user = KioskUser.objects.get(id=currentUser.id)
	msg = ''
	color = 'danger'

	if request.method == "POST":

		if "best" in request.POST.keys():
			# Bestaetigung des ersten Einkaufens kommt zurueck
			user.instruierterKaeufer = True
			user.save()
			msg = 'Nun kannst du Eink'+chr(228)+'ufe vormerken.'
			color = 'success'
			
		elif not "gruppenID" in request.POST.keys():
			# Keine Bestaetigung wurde gemacht
			msg = 'Du hast die Instruktionen noch nicht best'+chr(228)+'tigt.'


		else:

			einkaufGroupID = request.POST.get("gruppenID")
			Einkaufsliste.einkaufGroupVormerken(einkaufGroupID,currentUser.id)

			msg = 'Die Liste #' +str(einkaufGroupID)+' wurde zu deiner pers'+chr(246)+'nlichen Einkaufsliste hinzugef'+chr(252)+'gt.'
			color = 'success'

			#return HttpResponseRedirect(reverse('vorgemerkt_page'))


	# Checken, ob User ein instruierter Kaeufer ist.
	isInstr = user.instruierterKaeufer

	# Hole die eigene Liste, welche einzukaufen ist
	#persEinkaufsliste = ZumEinkaufVorgemerkt.getMyZumEinkaufVorgemerkt(currentUser.id)	

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()
	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/einkauf_vormerk_page.html', 
		{'currentUser': currentUser, 'isInstr': isInstr,
		#'persEinkaufsliste':persEinkaufsliste, 
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste, 'msg': msg, 'color': color})



@login_required
@permission_required('profil.do_einkauf',raise_exception=True)
def vorgemerkt_page(request):
	
	currentUser = request.user
	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()
	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()
	# Hole die eigene Liste, welche einzukaufen ist
	persEinkaufsliste = ZumEinkaufVorgemerkt.getMyZumEinkaufVorgemerkt(currentUser.id)

	return render(request,'kiosk/vorgemerkt_page.html',
		{'currentUser': currentUser,'persEinkaufsliste':persEinkaufsliste,'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


# String Input to Cent Values
def strToCents(num):
	try:
		left = int(re.findall('^(\d+)',num)[0])
		right = re.findall('[.,](\d*)$',num)
		if right == []:
			right = 0
		else:
			right = int(right[0])

		erg = int(left*100 + right)

	except:
		erg = None

	return erg

# Der Verwalter pflegt den Einkauf ins System ein
@login_required
@permission_required('profil.do_verwaltung',raise_exception=True)
def einkauf_annahme_page(request):
	currentUser = request.user
	# Besorge alle User
	allUsers = readFromDatabase('getUsersToBuy')
	# Hier auch nach Einkaeufer und hoeher filtern, User duerfen nichts einkaufen.
	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/einkauf_annahme_page.html', 
		{'currentUser': currentUser, 'allUsers': allUsers,  
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


@login_required
@permission_required('profil.do_verwaltung',raise_exception=True)
def einkauf_annahme_user_page(request, userID):

	if request.method == "POST":
		
		# Get the "Verwalter"
		currentUser = request.user

		# Input-Daten den Produkten zuordnen
		keys = [x for x in request.POST.keys()]

		# Get the product IDs
		productIds = [int(re.findall('^input_id_angeliefert_(\d+)$',x)[0]) for x in keys if re.match('^input_id_angeliefert_\d+$', x)]
		
		# Connect the input values to the corresponding products and only allow correct entries
		formInp = []
		ret = []
		for x in productIds:
			a = request.POST['input_id_angeliefert_'+str(x)]
			try:
				a = int(a)
			except:
				a = None

			b = request.POST['input_id_bezahlt_'+str(x)]
			b = strToCents(b)

			if not a is None and not b is None:
				formInp.append({
					'userID': userID,
					'product_id':x ,
					'anzahlAngeliefert': a,
					'gesPreis': b,
				})

				# For each List-Item, Run the procedure of "Einkauf-Annahme"
				ret.append(ZumEinkaufVorgemerkt.einkaufAnnehmen(formInp[-1],currentUser))

		# Create the response for the website
		notifications = chr(10).join( [r['html'] for r in ret] )
			
		if getattr(settings,'ACTIVATE_SLACK_INTERACTION') == True:
				
			# Send new products info to kiosk channel
			angeliefert = []
			for a in ret:
				if not a['angeliefert'] is None:
					for aa in a['angeliefert']:
						angeliefert.append(aa.produktpalette.produktName)

			angeliefert = list(set(angeliefert))
			try:
				slack_PostNewProductsInKioskToChannel(angeliefert)
			except:	pass


			# Send Thank You message to user who bought the products
			gesPreis = 0.0
			for a in ret:
				if not a['dct'] is None:
					gesPreis += a['dct']['gesPreis']

			if gesPreis > 0.0:
				try:
					user = KioskUser.objects.get(id = userID)

					txt = 'Deine Produkte wurden im Kiosk verbucht und dir wurde der Betrag von '+str('%.2f' % gesPreis)+' '+chr(8364)+' erstattet.\nDanke f'+chr(252)+'rs einkaufen! :thumbsup::clap:'
					slack_SendMsg(txt,user)
				except:	pass


	else:
		notifications = ''

	# Einkaeufer wurde ausgewaehlt, jetzt seine vorgemerkten Einkaeufe zurueckgeben
	seineVorgemerktenEinkaeufe = ZumEinkaufVorgemerkt.getMyZumEinkaufVorgemerkt(userID)
	user = KioskUser.objects.get(id=userID)

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request,'kiosk/einkauf_annahme_user_page.html',
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste, 'seineVorgemerktenEinkaeufe': seineVorgemerktenEinkaeufe, 'user': user, 'notifications': notifications,})




@login_required
@permission_required('profil.do_admin_tasks',raise_exception=True)
def transaktion_page(request):

	currentUser = request.user
	errorMsg = ''
	successMsg = ''
	form = None

	if request.method == "POST":
		# Hier kommen die eingegebenen Daten der Transaktion an.
		form = TransaktionenForm(request.POST)

		if not form.is_valid():
			errorMsg = 'Formaler Eingabefehler. Bitte erneut eingeben.'

		else:

			schuldner = KioskUser.objects.get(id=form.cleaned_data['idFrom'])
			schuldnerKto = Kontostand.objects.get(nutzer=schuldner)

			if form.cleaned_data['idTo'] == form.cleaned_data['idFrom']:
				errorMsg = chr(220)+'berweiser(in) und Empf'+chr(228)+'nger(in) sind identisch.'

			elif int(100*float(form['betrag'].value())) > schuldnerKto.stand and schuldner.username not in ('Bank','Dieb','Bargeld','Bargeld_Dieb','Bargeld_im_Tresor'):
				errorMsg = 'Kontostand des Schuldners ist nicht gedeckt.'

			else:
				returnHttp = GeldTransaktionen.makeManualTransaktion(form,currentUser)

				if getattr(settings,'ACTIVATE_SLACK_INTERACTION') == True:
					try:
						slack_PostTransactionInformation(returnHttp)
					except:
						pass

				successMsg = 'Der Betrag von '+str('%.2f' % returnHttp['betrag'])+' '+chr(8364)+' wurde von '+returnHttp['userFrom'].username+' an '+returnHttp['userTo'].username+' '+chr(252)+'berwiesen.'
			
	# Besorge alle User
	#allUsers = KioskUser.objects.filter(visible=True).order_by('username')
	allUsers = readFromDatabase('getUsersForTransaction')

	if form is None or successMsg!='':
		form = TransaktionenForm()

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()
	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/transaktion_page.html', 
		{'user': currentUser, 'allUsers': allUsers,  
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'errorMsg': errorMsg, 'successMsg': successMsg, 'form': form,})



# Anmelden neuer Nutzer, Light-Version: Jeder darf das tun, aber nur Basics, jeder wird Standardnutzer
@transaction.atomic
def neuerNutzer_page(request):
	
	msg = ''
	color = '#ff0000'

	if request.method == "POST":

		if request.POST.get('what')=='testSlackName':
			slackName = request.POST.get('slackName')

			# Try to find the given Slack-User in the user list on slack
			slack_token = getattr(settings,'SLACK_O_AUTH_TOKEN')
			users = []
			next_cursor = ''
			nextIteration = True

			while nextIteration:
				sc = SlackClient(slack_token)
				ulist = sc.api_call(
					"users.list",
					limit=100,
					cursor=next_cursor,
				)

				if ulist.get('ok')==False:
					# No successful return of the members list
					error = True
					nextIteration = False
				else:
					users.extend( [ {'id':x.get('id'), 'name':x.get('name'), 'real_name':x.get('real_name')} for x in ulist.get('members',[]) ] )
					next_cursor = ulist.get('response_metadata',{}).get('next_cursor','')
					if next_cursor=='':
						error = False
						nextIteration = False
				
			if not error:
				matched = [ x for x in users if x['id']==slackName or x['name']==slackName ]
				if len(matched)==1:
					retVal = '<div class="alert alert-success alert-small">ok</div>'
				else:
					retVal = '<div class="alert alert-warning alert-small">Keinen Nutzer im Team gefunden</div>'
			else:
				retVal = '<div class="alert alert-danger alert-small">Fehler beim Zugriff auf Slack.</div>'

			return JsonResponse({'data': retVal})

		# Do the normal registration
		res = UserErstellenForm(request.POST)

		if res.is_valid():		
			res.is_superuser = False
			res.is_staff = False
			res.is_active = True
			res.instruierterKaeufer = False
			res.rechte = 'Buyer'
			res.visible = True

			u = res.save()
			u.refresh_from_db()

			# Generate Confirmation Email
			user = u.username
			current_site = get_current_site(request)
			if request.is_secure: protocol = 'https'
			else: protocol = 'http'
			domain = current_site.domain
			uid = force_text(urlsafe_base64_encode(force_bytes(u.pk)))
			token = account_activation_token.make_token(u)
			url = reverse('account_activate', kwargs={'uidb64': uid, 'token': token})
			#url = reverse('account_activate')+uid+'/'+token+'/' 

			msg = '*Verifiziere deinen FfE-Kiosk Account!*\n\n\r' +	'Hallo '+ user + ',\n\r'+ 'Du erh'+chr(228)+'lst diese Slack-Nachricht weil du dich auf der Webseite ' + str(current_site) + ' registriert hast.\n\r' + 'Bitte klicke auf den folgenden Link, um deine Registrierung zu best'+chr(228)+'tigen:\n\r'+ '\t'+ protocol + '://'+domain+url+ '\n\n\r'+ 'Hast du dich nicht auf dieser Webseite registriert? Dann ignoriere einfach diese Nachricht.\n\n\r'+ 'Dein FfE-Kiosk Team.'

			try:
				slack_SendMsg(msg,u)
			except:
				pass

			raw_password = res.cleaned_data.get('password1')
			user = authenticate(username=u.username, password=raw_password)
			login(request, user)
			return HttpResponseRedirect(reverse('registrationStatus'))

		else:
			form = UserErstellenForm(request.POST)

	else:
		form = UserErstellenForm()
	
	currentUser = request.user

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/neuerNutzer_page.html', 
		{'user': currentUser, 'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'form':form, 'msg':msg, 'color': color})	


@login_required
@permission_required('profil.do_verwaltung',raise_exception=True)
def einzahlung_page(request):

	currentUser = request.user
	errorMsg = ''
	successMsg = ''
	form = None

	if request.method == "POST":

		# Hier kommen die eingegebenen Daten der Transaktion an.
		form = EinzahlungenForm(request.POST)

		if not form.is_valid():
			errorMsg = 'Formaler Eingabefehler. Bitte erneut eingeben.'

		# Testen bei Auszahlung, ob nicht zu viel ausgezahlt wird
		else:

			auszUser = KioskUser.objects.get(id=form['idUser'].value())
		
			if form['typ'].value() == 'Auszahlung':
				auszKto = Kontostand.objects.get(nutzer=auszUser)
				
			if form['typ'].value() == 'Auszahlung' and int(100*float(form['betrag'].value())) > auszKto.stand:
					errorMsg = 'Das Konto deckt den eingegebenen Betrag nicht ab.'

			else:
				returnHttp = GeldTransaktionen.makeEinzahlung(form,currentUser)

				if getattr(settings,'ACTIVATE_SLACK_INTERACTION') == True:
					try:
						slack_PostTransactionInformation(returnHttp)
					except:
						pass
					
				successMsg = 'Der Betrag von '+str('%.2f' % returnHttp['betrag'])+' '+chr(8364)+' wurde f'+chr(252)+'r '+auszUser.username+' '+returnHttp['type']+'.'
	
	# Anzeige von Kontostand des Nutzers (fuer Auszahlungen)
	if request.method == "GET" and 'getUserKontostand' in request.GET.keys():
		if request.GET.get('getUserKontostand')=='true' and 'userID' in request.GET.keys():
			id = int(request.GET.get('userID'))
			kto = Kontostand.objects.get(nutzer__id=id)
			return HttpResponse(str('%.2f' % (kto.stand/100)) + ' ' + chr(8364))

	# Besorge alle User
	allUsers = readFromDatabase('getUsersForEinzahlung')

	if form is None or successMsg!='':
		form = EinzahlungenForm()

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()
	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/einzahlung_page.html', 
		{'user': currentUser, 'form': form, 'allUsers': allUsers,  
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'errorMsg': errorMsg, 'successMsg': successMsg})



@login_required
@permission_required('profil.do_einkauf',raise_exception=True)
def meine_einkaufe_page(request):
	currentUser = request.user

	# Hole die eigene Liste, welche einzukaufen ist
	persEinkaufsliste = ZumEinkaufVorgemerkt.getMyZumEinkaufVorgemerkt(currentUser.id)

	# Bearbeitung eines Loeschvorgangs
	if request.method == "POST":
		# Ueberpruefung des Inputs
		idToDelete = int(request.POST.get("productID"))
		for item in persEinkaufsliste:
			if item["id"] == idToDelete:
				maxNumToDelete = item["anzahlElemente"]
				break
			else:
				maxNumToDelete = 0
		
		numToDelete = int(request.POST.get("noToDelete"))
		
		# Wenn Input passt, dann wird geloescht
		if numToDelete <= maxNumToDelete:
			ZumEinkaufVorgemerkt.objects.filter(pk__in=ZumEinkaufVorgemerkt.objects.filter(produktpalette__id=idToDelete).values_list('pk')[:numToDelete]).delete()

			# Testen, ob wieder Produkte auf die allgemeine Einkaufsliste muessen
			checkKioskContentAndFillUp()

		return HttpResponseRedirect(reverse('meine_einkaufe_page'))

	
	# Ausfuehren der normalen Seitendarstellung

	# Hole die eigene Liste, welche einzukaufen ist
	persEinkaufsliste = ZumEinkaufVorgemerkt.getMyZumEinkaufVorgemerkt(currentUser.id)

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/meine_einkaufe_page.html', 
		{'currentUser': currentUser, 'persEinkaufsliste': persEinkaufsliste,
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})



@login_required
@permission_required('profil.do_admin_tasks',raise_exception=True)
def fillKioskUp(request):

	checkKioskContentAndFillUp()

	return redirect('home_page')


@login_required
@permission_required('profil.do_verwaltung', raise_exception=True)
def inventory(request):
	currentUser = request.user

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	# Get the kiosk-content, prepared for inventory form
	inventoryList = Kiosk.getKioskContentForInventory()

	# Processing the response of the inventory form
	if request.method == "POST":
		report = ZuVielBezahlt.makeInventory(request, currentUser, inventoryList)

		# Calculate the overall loss within this inventory
		loss = 0
		for item in report:
			if item['verlust'] == True:
				loss = loss + item["anzahl"] * item["verkaufspreis_ct"]
		loss = loss / 100

		tooMuch = 0
		for item in report:
			if item['verlust'] == False:
				tooMuch = tooMuch + item["anzahl"] * item["verkaufspreis_ct"]
		tooMuch = tooMuch / 100

		# Send notifications to Slack-Channel
		if request.POST.get('sendMessage', False) and request.POST.get('sendMessage','')=='sendMessage':

			txt = '@channel\n' + 'Seit der letzten Inventur wurden Produkte im Wert von *' + '%.2f' % loss + chr(8364) + '* nicht bezahlt:\n'
			sendMsg = False

			for r in report:
				if r['verlust'] is True:
					sendMsg = True
					txt += '\t' + str(r['anzahl']) + 'x ' + r['produkt_name'] + '\n'
			txt += '\n _Bitte nachbezahlen! Danke._'

			if sendMsg:
				print('here')
				slackSettings = getattr(settings,'SLACK_SETTINGS')
				slack_SendMsg(txt, channel=True)

		
		# Ueberpruefung vom Bot, ob Einkaeufe erledigt werden muessen. Bei Bedarf werden neue Listen zur Einkaufsliste hinzugefuegt.
		checkKioskContentAndFillUp()

		# Hole den Kioskinhalt
		kioskItems = Kiosk.getKioskContent()

		# Einkaufsliste abfragen
		einkaufsliste = Einkaufsliste.getEinkaufsliste()

		request.session['inventory_data'] = {'loss': loss, 'tooMuch':tooMuch,  
			'report': report,'kioskItems': kioskItems
			, 'einkaufsliste': einkaufsliste}
		return HttpResponseRedirect(reverse('inventory_done'))

	
	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/inventory_page.html', 
		{'currentUser': currentUser, 'inventoryList': inventoryList,
		'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste}) 


@login_required
@permission_required('profil.do_verwaltung', raise_exception=True)
def inventory_done(request):
	currentUser = request.user
	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()
	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	if 'inventory_data' in request.session.keys():
		inventory_data = request.session['inventory_data']
		del request.session['inventory_data']
	else:
		return HttpResponseRedirect(reverse('home_page'))

	inventory_data['currentUser'] = currentUser
	inventory_data['kioskItems'] = kioskItems
	inventory_data['einkaufsliste'] = einkaufsliste

	return render(request,'kiosk/inventory_conducted_page.html',inventory_data)


@login_required
@permission_required('profil.do_admin_tasks',raise_exception=True)
def statistics(request):

	# Verkaufsstatistik
	try: vkToday = readFromDatabase('getVKThisDay')[0]['dayly_value']
	except: vkToday = 0
	try: vkYesterday = readFromDatabase('getVKLastDay')[0]['dayly_value']
	except: vkYesterday = 0
	try: vkThisWeek = readFromDatabase('getVKThisWeek')[0]['weekly_value']
	except: vkThisWeek = 0
	try: vkLastWeek = readFromDatabase('getVKLastWeek')[0]['weekly_value']
	except: vkLastWeek = 0
	try: vkThisMonth = readFromDatabase('getVKThisMonth')[0]['monthly_value']
	except: vkThisMonth = 0
	try: vkLastMonth = readFromDatabase('getVKLastMonth')[0]['monthly_value']
	except: vkLastMonth = 0

	# Geldwerte
	vkValueKiosk = readFromDatabase('getKioskValue')
	vkValueKiosk = vkValueKiosk[0]['value']
	vkValueAll = readFromDatabase('getVkValueAll')
	vkValueAll = vkValueAll[0]['value']

	ekValueKiosk = readFromDatabase('getKioskEkValue')
	ekValueKiosk = ekValueKiosk[0]['value']
	ekValueAll = readFromDatabase('getEkValueAll')
	ekValueAll = ekValueAll[0]['value']

	priceIncrease = round((vkValueAll-ekValueAll)/ekValueAll * 100.0, 1)

	kioskBankValue = Kontostand.objects.get(nutzer__username='Bank')
	kioskBankValue = kioskBankValue.stand / 100.0

	gespendet = Kontostand.objects.get(nutzer__username='Gespendet')
	gespendet = gespendet.stand / 100.0

	bargeld = Kontostand.objects.get(nutzer__username='Bargeld')
	bargeld = - bargeld.stand / 100.0
	bargeld_tresor = Kontostand.objects.get(nutzer__username='Bargeld_im_Tresor')
	bargeld_tresor = - bargeld_tresor.stand / 100.0

	usersMoneyValue = readFromDatabase('getUsersMoneyValue')
	usersMoneyValue = usersMoneyValue[0]['value']


	# Bezahlte und unbezahlte Ware im Kiosk (Tabelle gekauft)
	datum = timezone.now().strftime('%Y-%m-%d %H:%M:%S')
	unBezahlt = readFromDatabase('getUmsatzUnBezahlt',[datum, datum, datum])
	for item in unBezahlt:
		if item['what'] == 'bezahlt': vkValueBezahlt = item['preis']
		if item['what'] == 'Dieb': stolenValue = item['preis']
		if item['what'] == 'alle': vkValueGekauft = item['preis']

	# Bargeld "gestohlen"
	bargeld_Dieb = Kontostand.objects.get(nutzer__username='Bargeld_Dieb')
	bargeld_Dieb = - bargeld_Dieb.stand / 100.0

	# Gewinn & Verlust
	theoAlloverProfit = vkValueAll - ekValueAll
	theoProfit = vkValueKiosk + kioskBankValue
	buyersProvision = theoAlloverProfit - theoProfit - gespendet

	adminsProvision = 0
	profitHandback = 0

	expProfit = theoProfit - stolenValue - bargeld_Dieb - adminsProvision - profitHandback

	bilanzCheck = usersMoneyValue - bargeld - stolenValue + kioskBankValue - bargeld_Dieb - bargeld_tresor
	checkExpProfit = -(usersMoneyValue -bargeld - vkValueKiosk - bargeld_tresor)

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	# Single Product Statistics
	singleProductStatistics = readFromDatabase('getProductPerItemStatistics')

	return render(request, 'kiosk/statistics_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'chart_Un_Bezahlt': Chart_Un_Bezahlt(), 
		'chart_UmsatzHistorie': Chart_UmsatzHistorie(),
		'chart_DaylyVkValue': Chart_DaylyVkValue(),
		'chart_WeeklyVkValue': Chart_WeeklyVkValue(),
		'chart_MonthlyVkValue': Chart_MonthlyVkValue(),
		'chart_Profits': Chart_Profits(),
		'singleProductStatistics': singleProductStatistics,
		#'chart_ProductsWin': Chart_ProductsWin(),
		#'chart_ProductsCount': Chart_ProductsCount(),
		#'chart_Stolen_ProductsWin': Chart_Stolen_ProductsWin(),
		#'chart_StolenProductsShare': Chart_StolenProductsShare(),
		'vkToday':vkToday, 'vkYesterday':vkYesterday, 'vkThisWeek':vkThisWeek, 'vkLastWeek':vkLastWeek,
		'vkThisMonth':vkThisMonth, 'vkLastMonth':vkLastMonth,
		'vkValueBezahlt': vkValueBezahlt, 'stolenValue': stolenValue, 'vkValueGekauft': vkValueGekauft, 
		'relDieb': stolenValue/vkValueGekauft*100.0, 'relBezahlt': vkValueBezahlt/vkValueGekauft*100.0, 
		'vkValueKiosk': vkValueKiosk, 'kioskBankValue': kioskBankValue, 
		'vkValueAll': vkValueAll, 'ekValueAll': ekValueAll, 'ekValueKiosk': ekValueKiosk,
		'bargeld': bargeld, 'bargeld_tresor':bargeld_tresor, 'bargeld_Dieb':bargeld_Dieb, 'usersMoneyValue': usersMoneyValue, 
		'priceIncrease': priceIncrease, 'theoAlloverProfit': theoAlloverProfit, 
		'theoProfit': theoProfit, 'buyersProvision': buyersProvision, 
		'adminsProvision': adminsProvision, 'profitHandback': profitHandback, 
		'expProfit': expProfit, 'bilanzCheck': bilanzCheck, 'checkExpProfit': checkExpProfit, 'gespendet': gespendet, }) 



@login_required
@permission_required('profil.do_einkauf',raise_exception=True)
def produktKommentare(request):

	# Besorge Liste aller Produktkommentare
	allProductComments = readFromDatabase('getAllProductComments')

	# Add TimeZone information: It is stored as UTC-Time in the SQLite-Database
	for k,v in enumerate(allProductComments):
		allProductComments[k]['erstellt'] = pytz.timezone('UTC').localize(v['erstellt'])


	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/produkt_kommentare_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'allProductComments': allProductComments, })


@login_required
@permission_required('profil.do_einkauf',raise_exception=True)
def produktKommentieren(request, s):
	
	# Processing a new comment from the site
	if request.method == "POST":
		productID = int(request.POST.get("productID"))
		comment = request.POST.get("kommentar")

		p = Produktpalette.objects.get(id=productID)
		k = Produktkommentar(produktpalette = p, kommentar = comment)
		k.save()

		return HttpResponseRedirect(reverse('produkt_kommentieren_page', kwargs={'s':s}))
	
	productID = s

	# Besorge Liste aller Produktkommentare
	allCommentsOfProduct = readFromDatabase('getAllCommentsOfProduct',[productID])
	productName = allCommentsOfProduct[0]["produkt_name"]
	latestComment = allCommentsOfProduct[0]["kommentar"]

	# Add TimeZone information: It is stored as UTC-Time in the SQLite-Database
	for k,v in enumerate(allCommentsOfProduct):
		allCommentsOfProduct[k]['erstellt'] = pytz.timezone('UTC').localize(v['erstellt'])

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/produkt_kommentieren_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'allCommentsOfProduct': allCommentsOfProduct, 
		'productName': productName, 'productID': productID, 'latestComment': latestComment, })


def anleitung(request):

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/anleitung_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


def ersteSchritte(request):

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/ersteschritte_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


def slackInfos(request):

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/slackinfo_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


def regelwerk(request):

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/regelwerk_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})


@login_required
@permission_required('profil.do_verwaltung',raise_exception=True)
def rueckbuchung(request):

	# Abfrage aller Nutzer
	allActiveUsers = KioskUser.objects.filter(is_active=True,visible=True)
	# Hier Ordnen: .order_by('username')
	dieb = KioskUser.objects.filter(username='Dieb')
	allActiveUsers = allActiveUsers.union(dieb)

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/rueckbuchungen_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste,
		'allActiveUsers': allActiveUsers, })


@login_required
@permission_required('profil.do_verwaltung',raise_exception=True)
def rueckbuchung_user(request, userID):
	
	user = KioskUser.objects.get(id=userID)
	currentUser = request.user
	RueckbuchungFormSet = formset_factory(RueckbuchungForm, extra=0)

	notifications = ''

	if request.method=='POST':
		formset = RueckbuchungFormSet(request.POST)

		if formset.is_valid():
			
			# Do the Rueckbuchung
			ret = []
			for f in formset:
				
				r = Gekauft.rueckbuchen(f)
				if r['anzahlZurueck'] > 0:
				
					html = str(r['anzahlZurueck'])+' '+r['product']+' wurden ins Kiosk zur'+chr(252)+'ck verbucht.'+chr(10)+'Der Betrag von '+str('%.2f' % r['price'])+' '+chr(8364)+' wurde gutgeschrieben.'
					r['html'] = render_to_string('kiosk/success_message.html', {'message':html})

					r['slackMsg'] = 'Dir wurde das Produkt "'+str(r['anzahlZurueck'])+'x '+str(r['product'])+'" r'+chr(252)+'ckgebucht und der Betrag von '+str('%.2f' % r['price'])+' '+chr(8364)+' erstattet.\nDein Kiosk-Verwalter'

					ret.append(r)

			# Create the response for the website
			notifications = chr(10).join( [r['html'] for r in ret] )

			# Write Slack-Messages to the user
			if getattr(settings,'ACTIVATE_SLACK_INTERACTION') == True:
				# Send notice to user
				
				for r in ret:
					try:
						u = KioskUser.objects.get(id = r['userID'])
						slack_SendMsg(r['slackMsg'],u)
					except:	pass


			# Get the new/updated formset
			seineKaeufe = readFromDatabase('getBoughtItemsOfUser', [userID])
			formset = RueckbuchungFormSet(initial=seineKaeufe)

	else:
		seineKaeufe = readFromDatabase('getBoughtItemsOfUser', [userID])
		formset = RueckbuchungFormSet(initial=seineKaeufe)

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/rueckbuchungen_user_page.html', {'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste, 'user': user, 'formset':formset, 'notifications': notifications, })



@login_required
@permission_required('profil.perm_kauf',raise_exception=True)
def slackComTest(request):

	currentUser = request.user
	slack_TestMsgToUser(currentUser)

	# Hole den Kioskinhalt
	kioskItems = Kiosk.getKioskContent()

	# Einkaufsliste abfragen
	einkaufsliste = Einkaufsliste.getEinkaufsliste()

	return render(request, 'kiosk/slackComTest_page.html', 
		{'kioskItems': kioskItems, 'einkaufsliste': einkaufsliste})
