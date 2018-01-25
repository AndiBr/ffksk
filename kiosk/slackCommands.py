from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from django.conf import settings

from slackclient import SlackClient

from .models import Produktpalette
from profil.models import KioskUser

from .queries import readFromDatabase

import requests
import re


@csrf_exempt
def receiveSlackCommands(request):
	
	# Check if it is a POST-request
	if not request.method == "POST":
		return HttpResponse(status=406)
	message = request.POST

	# Verify the correct sender: Slack-FfE
	slack_verification_token = getattr(settings,'SLACK_VERIFICATION_TOKEN')
	if not message.get('token') == slack_verification_token:
		return HttpResponse(status=403)

	# Route the command to the correct function
	if message.get('command') == '/kiosk':
		# Start a function with threading
		#Thread(target=process_kiosk, args=[message]).start()
		process_kiosk(message)

	# No mapping for this command has been established, yet.
	else:
		try:
			slack_NotKnownCommandMsg(message.get('response_url'), message.get('command'))
		except:
			pass

	return HttpResponse(status=200)


# Process the command '/kiosk'
def process_kiosk(message):

	# Check if the user has an account in the kiosk
	if not KioskUser.objects.filter(slackName=message.get('user_name'), visible=True):
		attach = getCancelAttachementForResponse()
		slack_sendMessageToResponseUrl(message.get('response_url'), 'Ich kann deinen Slack-Account nicht mit deinem FfE-Konto verbinden.'+chr(10)+'Wende dich bitte an einen Administrator.', attach)

		# Weiter gehts bei slackMessages.receiveSlackCommands, wo die Antwort weiterverarbeitet wird.
		return

	# Filter the the command from spaces, but first bring together commands in quotation marks
	commandText = message.get('text')

	inQuot = re.findall(r'\"[\w\s]+\"', commandText)
	if not inQuot is None and not inQuot==[]:
		for x in inQuot:
			y = x.replace(' ','\s')
			commandText = re.sub(r'\"[\w\s]+\"',y[1:-1],commandText)

	commandText = commandText.split(' ')
	commandText = [x.replace('\s',' ') for x in commandText]

	commandText = list(filter(lambda a: a not in ['',' '], commandText))

	# Find the command 'buy'
	if not [x for x in commandText if x in ['Kaufen','Kauf','kauf','kaufen','Buy','buy','Buying','buying']] == []:
		command = [x for x in commandText if x in ['Kaufen','Kauf','kauf','kaufen','Buy','buy','Buying','buying']]
		process_kiosk_buy(message, commandText, command[0])

	# Find the command 'help'
	elif not [x for x in commandText if x in ['Hilfe','hilfe','help','Help','hilf','Hilf']] == [] or len(commandText)==1:
		kiosk_help(message)

	# No known kiosk-command found. Tell the user
	else:
		msg = 'Wie es scheint, ben'+chr(246)+'tigst du Hilfe...'
		kiosk_help(message, msg)

	return


# Process the command '/kiosk buy'
def process_kiosk_buy(message, commandText, command):
	# Remove command item from commandText
	commandText.remove(command)

	# Check, if help is needed
	if not len(commandText) in [1,2] or not [x for x in commandText if x in ['Hilfe','hilfe','help','Help','hilf','Hilf']] == []:
		kiosk_buy_help(message)
		return

	# In case of one more command item, it is seen as the kiosk item
	if len(commandText)==1:
		rawItemToBuy = commandText[0]
		numBuy = 1
	else:
		# In case of two more command items, check for the one that is a number. The other is the kios item
		numBuy = None
		
		try: numBuy = int(commandText[0])
		except: pass
		if not numBuy is None:
			rawItemToBuy = commandText[1]

		else:
			try: numBuy = int(commandText[1])
			except: pass
			if not numBuy is None:
				rawItemToBuy = commandText[0]
			else:
				msg = 'Wie es scheint, ben'+chr(246)+'tigst du Hilfe...'
				kiosk_buy_help(message, msg)
				return	

	# Search for the item with a 100 percent accordance
	itemAccordance = None
	itemToBuy = Produktpalette.objects.filter(produktName=rawItemToBuy, imVerkauf=True)
	if len(itemToBuy)==1: itemAccordance = 1

	# Search for the item with a likeness-query
	if itemAccordance is None:
		itemToBuy = Produktpalette.objects.filter(produktName__icontains=rawItemToBuy, imVerkauf=True)
		if len(itemToBuy)>=1: itemAccordance = 0.5

	# Search for the item with only parts of the string
	if itemAccordance is None:
		for i in range(len(rawItemToBuy)-1,2,-1):
			itemToBuy = Produktpalette.objects.filter(produktName__icontains=rawItemToBuy[0:i], imVerkauf=True)
			if len(itemToBuy)>=1: 
				itemAccordance = 0.25
				break

	# If no match was made, give back the complete list
	if itemAccordance is None:
		itemToBuy = Produktpalette.objects.filter(imVerkauf=True).order_by('produktName')

	# Create list of products plus price for selection
	txts = []
	for v in itemToBuy:
		prices = readFromDatabase('getProductNameAndPriceById',[v.id])
		txt = str(numBuy) + 'x ' + str(v.produktName) + ' | ' + '%.2f' % (prices[0]['verkaufspreis']/100.0*numBuy) + ' ' + chr(8364)
		txts.append({'text': txt, 'value': str(v.id)+'#'+str(numBuy)})

	# Prepare the selection and the button
	actionSelection = {'name': 'product_list','text': 'Auswahl ...', 'type': 'select', 'options': txts}
	actionButton = {'name': 'ConfirmOneItem', 'text': txts[0]['text'],'type': 'button','value': txts[0]['value']}

	# Send messages to respond
	if itemAccordance is None:
		# There is no accordance -> Give the complete products to select
		text = 'Was m'+chr(246)+'chtest Du kaufen? Ich konnte dich nicht verstehen und gebe dir die komplette Produktpalette zur Auswahl.'
		action = actionSelection

	elif itemAccordance==1 or len(itemToBuy)==1:
		# One item has been found. Just ask to confirm
		text = 'Du m'+chr(246)+'chtest folgendes kaufen?'
		action = actionButton

	elif itemAccordance<1:
		# There is a selection of possible products. Ask to select from them
		text = 'Was genau m'+chr(246)+'chtest Du kaufen? Deine Eingabe hat folgende Ergebnisse geliefert:'
		action = actionSelection

	else:
		# Fehler darf nicht passieren -> Error-Message
		text = 'Uuups. Da ist etwas schief gelaufen. Wende dich bitte an den Administrator.'
		action = None


	# Send the message
	attach = {
		'attachments': [
			{
				'text': text,
				'callback_id': 'kiosk_buy',
				'attachment_type': 'default',
				'actions': [
					action,
					{'name': 'Cancel', 'text': 'Abbrechen','type': 'button','value':'cancel','style':'danger'},
				]
			}
		]
	}
	slack_sendMessageToResponseUrl(message.get('response_url'),'*Einkaufen im Kiosk*',attach)

	# Weiter gehts bei slackMessages.receiveSlackCommands, wo die Antwort weiterverarbeitet wird.
	return

# Send back general '/kiosk' help
def kiosk_help(message, msg=''):
	msg = msg+chr(10)+'*Kiosk Hilfe*'+chr(10)+'Nach dem `/kiosk`-Befehl musst du ein Stichwort schreiben, was du tun m'+chr(246)+'chtest. Zum Beispiel:'+chr(10)+'```/kiosk Kaufen```'+chr(10)+'Dort bekommst du jeweils weitere Informationen.'+chr(10)+'(Alle Befehle: `Hilfe`, `Kaufen`, `Spenden`)'
	slack_sendMessageToResponseUrl(message.get('response_url'), msg, getOkAttachementForResponse())
	return

def kiosk_buy_help(message, msg=''):
	msg = msg+chr(10)+'*Kiosk Kaufen Hilfe*'+chr(10)+'Nach dem `/kiosk Kaufen`-Befehl musst du ein Stichwort schreiben, was du kaufen m'+chr(246)+'chtest. Optional kannst du als Zahl noch die Menge zu kaufender Produkte anf'+chr(252)+'gen. Zum Beispiel:'+chr(10)+'```/kiosk Kaufen 2 Pizza```'+chr(10)+'```/kiosk Kaufen Pesto```'+chr(10)+'```/kiosk Kaufen saure```'+chr(10)+'```/kiosk Kaufen "Saure Zunge" 5```'+chr(10)+'Falls ich mir nicht sicher bin, was genau du kaufen m'+chr(246)+'chtest oder es '+chr(228)+'hnliche Produkte gibt, gebe ich dir eine Auswahl zum Anklicken und Best'+chr(228)+'tigen.'
	slack_sendMessageToResponseUrl(message.get('response_url'), msg, getOkAttachementForResponse())
	return

def getCancelAttachementForResponse():
	attach = {
		'attachments': [
			{
				'text': '',
				'callback_id': 'cancel_action',
				'attachment_type': 'default',
				'actions': [
					{'name': 'Cancel', 'text': 'Abbrechen','type': 'button','value':'cancel','style':'danger'},
				]
			}
		]
	}
	return attach

def getOkAttachementForResponse():
	attach = {
		'attachments': [
			{
				'text': '',
				'callback_id': 'OK_action',
				'attachment_type': 'default',
				'actions': [
					{'name': 'OK', 'text': 'OK','type': 'button','value':'OK','style':'good'},
				]
			}
		]
	}
	return attach

# Send back a ephemeral message to the response url
def slack_sendMessageToResponseUrl(url, text, furtherDict={}):
	data = {'text':text}
	data.update(furtherDict)
	r = requests.post(url,json=data)
	return


# Send back a message to the sender and tell, that the command does not exist.
def slack_NotKnownCommandMsg(response_url, command):
	msg = "Ich konnte leider mit folgendem Befehl nichts anfangen: '" + command + "'."+chr(10)+'Wende dich bitte an einen Administrator.'
	slack_sendMessageToResponseUrl(response_url, msg, getCancelAttachementForResponse())
	return
