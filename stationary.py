import ConfigParser
import reportlab
import os

config = ConfigParser.ConfigParser()
config.read(os.path.expanduser('~/printerface/email.cfg'))

pdir = os.path.expanduser("~/printerface/")
jobdir = pdir + 'pdf/'

from reportlab.lib.units import cm
from reportlab.lib.pagesizes import A4

pagewidth = A4[0] - 2*0.8*cm
vpad = 0.4*cm

def headerDetails(c, ctx, doctype="DELIVERY NOTE"):
	c.saveState()
	top = 27.6*cm
	textobject = c.beginText()
	textobject.setTextOrigin(2.75*cm, top)
	textobject.setFont("Helvetica", 8)
	textobject.textLines(config.get('Printing', 'address').replace("\\n", '\n'))
	textobject.textLines(config.get('Printing', 'vatreg'))
	textobject.textLines(config.get('Printing', 'fax1'))
	textobject.textLines(config.get('Printing', 'fax2'))
	textobject.textLines(config.get('Printing', 'email') + "      " + config.get('Printing', 'website'))
	c.drawText(textobject)
	c.setFont("Helvetica", 18)
	c.drawRightString(pagewidth, top, doctype)
	c.restoreState()
	c.drawImage(pdir + 'logo.gif', 0,top+0.5*cm, width=2.5*cm,height=3*cm, preserveAspectRatio=True, anchor='nw')

def topBox(c, x, y, title="Title", content="The quick brown", w=2*cm, h=2.0*cm, padleft=0.8*cm, align='l'):
	c.saveState()
	c.translate(x,y)
	c.rect(0.0,0,w,-h)

	c.saveState()
	c.setFillColorRGB(0.95,0.95,0.95)
	c.rect(0.0,0,w,-0.45*cm, fill=True)
	c.restoreState()
	
	c.setFont("Helvetica", 7)
	if align=='c':
		c.drawCentredString(w*0.5, -.33*cm, title)
	else:		
		c.drawString(0.8*cm, -.33*cm, title)
	
	textobject = c.beginText()
	textobject.setFont("Helvetica", 10.5)
	textobject.setTextOrigin(padleft, -1*cm)	
	textobject.textLines(content)
	c.drawText(textobject)
	c.restoreState()

def leftBox(c, x, y, title="Title", content="Quick brown", h=0.85*cm, w=2.0*cm, padding=0.3*cm, split=0.5):
	p = padding
	c.saveState()
	c.translate(x,y)
	c.rect(0,0,w,-h)

	c.saveState()
	c.setFillColorRGB(0.95,0.95,0.95)
	c.rect(0.0,0,w*split,-h, fill=True)
	c.restoreState()
	
	c.setFont("Helvetica", 8)
	c.drawString(p, -h+p, title)
	c.setFont("Helvetica", 10)
	if split > 0:
		c.drawString(w*split + p, -h+p, content)
	else:
		c.drawCentredString(w*0.5 + p, -h+p, content)
	c.restoreState()

def watermark(c, mark='CUSTOMER COPY'):
	c.saveState()
	c.setFillColorRGB(0.85,0.85,0.85)
	c.setFont("Helvetica-Bold", 54)
	c.drawCentredString(pagewidth/2, 7.5*cm, mark)
	c.restoreState()

def deliveryNote(c, ctx):
	for mark in ['CUSTOMER COPY', 'DRIVERS COPY', 'OFFICE COPY']:
		for page in ctx:
			deliveryNotePage(c, page, mark)

def deliveryNotePage(c, ctx, mark):
	from reportlab.lib.units import inch
	
	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)
	
	watermark(c, mark=mark)

	c.saveState()
	c.setStrokeColorRGB(0.6,0.6,0.6)
	c.setFillColorRGB(0.6,0.6,0.6)
	c.rect(0.0,0,pagewidth,28.1*cm)
	c.restoreState()

	c.setFont("Helvetica", 10)
	c.drawString(0, 0.5*cm, config.get('Printing', 'terms'))

	# move to top left, draw address label
	headerDetails(c, ctx)

	y = 27.2*cm
	h = 0.85*cm
	w = 9*cm
	leftBox(c, pagewidth-w, y-0*h, w=w, title='DATE', content=ctx['date'])
	leftBox(c, pagewidth-w, y-1*h, w=w, title='PAGE', content=ctx['page'])
	leftBox(c, pagewidth-w, y-2*h, w=w, title='DOCUMENT No.', content=ctx['doc'])
	y = y - h*3

	y = y - vpad
	h = 3.4*cm 
	w = 9.0*cm
	topBox(c, 0*cm, y, h=h, w=w, title="INVOICE TO", content=ctx['addr_invoice'])
	topBox(c, pagewidth-w, y, h=h, w=w, title="DELIVERY ADDRESS", content=ctx['addr_delivery'])
	y = y - h

	y = y - vpad
	w = pagewidth / 5.0	
	h = 1.25*cm

	topBox(c, 0*w, y, w=w, h=h, title="ACCOUNT No.", content=ctx['accno'])
	topBox(c, 1*w, y, w=w, h=h, title="YOUR REF.",   content=ctx['custref'])
	topBox(c, 2*w, y, w=w, h=h, title="OUR REF.",    content=ctx['ourref'])
	topBox(c, 3*w, y, w=w, h=h, title="ORDER DATE",  content=ctx['ord_date'])
	topBox(c, 4*w, y, w=w, h=h, title="DATE REQ.",   content=ctx['req_date'])
	y = y-h

	w = pagewidth / 2.0
	topBox(c, 0*w, y, w=w, h=h, title="SALES PERSON", content=ctx['salesperson'])
	topBox(c, 1*w, y, w=w, h=h, title="INSTRUCTIONS", content=ctx['instructions'])
	y = y-h

	# base this section on 9 column format, with some *2, *3 width columns
	y = y - vpad
	w = pagewidth / 9.0	
	h = 11*cm
	topBox(c, 0*w, y, w=2*w, h=h, title="PRODUCT CODE", content=ctx['pcode'])
	topBox(c, 2*w, y, w=5*w, h=h, title="PRODUCT DESCRIPTION", content=ctx['pdesc'])
	topBox(c, 7*w, y, w=w, h=h, title="QTY", content=ctx['pqty'], padleft=0.2*cm)
	topBox(c, 8*w, y, w=w, h=h, title="UNIT", content=ctx['punit'], padleft=0.2*cm)
	y = y-h

	w = pagewidth / 2.0
	h = 0.45*cm
	topBox(c, 0, y, w=w, h=h, title='SECTION TO BE COMPLETED BY CUSTOMER', content='', align='c')
	topBox(c, w, y, w=w, h=h, title=config.get('Printing', 'inv_rhs'), content='', align='c')
	y = y-h
	h = 0.85*cm
	leftBox(c, 0, y, w=w, h=h, title='SIGNED', content='')
	leftBox(c, w, y, w=w, h=h, title='NUMBER OF CASES', content='')
	y = y-h
	leftBox(c, 0, y, w=w, h=h, title='PRINT NAME', content='')
	leftBox(c, w, y, w=w, h=h, title='DRIVER\'S NAME', content='')
	y = y-h
	leftBox(c, 0, y, w=w, h=h, title='POSITION', content='')
	leftBox(c, w, y, w=w, h=h, title='VEHICLE REGISTRATION', content='')
	y = y-h
	leftBox(c, 0, y, w=w, h=h, title='TIME', content='')
	leftBox(c, w, y, w=w, h=h, title='CHECKER/PICKER', content='')
	y = y-h
	leftBox(c, 0, y, w=w, h=h, title='DATE', content='')
	leftBox(c, w, y, w=w, h=h, title='', content='PLEASE SIGN AND RETURN WITH DRIVER', split=0.0)

	c.showPage()

def writePage(drawfn, content):
	from reportlab.pdfgen import canvas
	
	p = jobdir + "hello.pdf"
	c = canvas.Canvas(p, pagesize=A4)
 	print('formatting %s to %s with %s' % (content, p, drawfn))
 	drawfn(c, content)
 	c.save()

	return p

class DocFormatter(object):
	def format(self, ctx):
		print('formatting %s' % ctx['name'])
		return []

if __name__=="__main__":
	# launch the server on the specified port
	try:
		os.makedirs(jobdir)
		os.makedirs(rawdir)

	except:
		pass

	chuff = dict(date='04/10/12', doc='731/289073', 
		addr_invoice='SAMPLE ACCOUNT\nCHRIS SHUCKSMITH',
		addr_delivery='CHRIS SHUCKSMITH\nFLAT 999 MIDNIGHT TERRACE\n32 GREAT NOWHERE ST. LONDON SE1 W1J\n IF OUT PSE LEAVE WITH THE\nCAT',
		accno='MULTI-21', custref='OSCAR FOX', ourref='289073',
		ord_date='04/10/12', req_date='05/10/12',
		salesperson='SAMPLE ACCOUNT', instructions='TO BE DELIVERED LDN0510',
	)

	ctx = []
	for page,sz in enumerate([18,3]):
		order = dict(
				page=str(page+1),
				pcode="SMP109\n"*sz,
				pdesc="CH CHEESY BOISES Bord Sec     07\n"*sz,
				pqty="3\n"*sz,
				punit="BOTT\n"*sz
			)

		ctx.append( dict(order.items() + chuff.items()))

	p = writePage(deliveryNote, ctx)

 	try:
		os.startfile(p)
	except:
		pass


