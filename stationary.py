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

	c.setFont("Helvetica", 10)
	c.drawString(0, 0.5*cm, config.get('Printing', 'terms'))

def topBox(c, x, y, title="Title", content="The quick brown", w=2*cm, h=2.0*cm, padleft=0.8*cm, align='l', ht=0.45*cm):
	c.saveState()
	c.translate(x,y)
	c.rect(0.0,0,w,-h)

	c.saveState()
	c.setFillColorRGB(0.95,0.95,0.95)
	c.rect(0.0,0,w,-ht, fill=True)
	c.restoreState()
	
	c.setFont("Helvetica", 7)
	if align=='c':
		for lineon, text in enumerate(title.splitlines()):
			c.drawCentredString(w*0.5, -.33*cm*(lineon+1), text)
	else:		
		c.drawString(0.8*cm, -.33*cm, title)
	
	textobject = c.beginText()
	textobject.setFont("Helvetica", 10.5)
	textobject.setTextOrigin(padleft, -(0.55*cm + ht))	
	textobject.textLines(content)
	c.drawText(textobject)
	c.restoreState()
	return (x+w, y-h)

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
	return (x+w, y-h)

def watermark(c, mark='CUSTOMER COPY'):
	c.saveState()
	c.setFillColorRGB(0.85,0.85,0.85)
	c.setFont("Helvetica-Bold", 54)
	c.drawCentredString(pagewidth/2, 7.5*cm, mark)
	c.restoreState()

def outline(c):
	c.saveState()
	c.setStrokeColorRGB(0.6,0.6,0.6)
	c.setFillColorRGB(0.6,0.6,0.6)
	c.rect(0.0,0,pagewidth,28.1*cm)
	c.restoreState()

def rightHeaderBlock(c, ctx, y=3*cm):
	h = 0.85*cm
	w = 9*cm
	(x, y) = leftBox(c, pagewidth-w, y, w=w, title='DATE', content=ctx['date'])
	(x, y) = leftBox(c, pagewidth-w, y, w=w, title='PAGE', content=ctx['page'])
	(x, y) = leftBox(c, pagewidth-w, y, w=w, title='DOCUMENT No.', content=ctx['doc_num'])
	return y

def addressHorizDoubleBox(c, ctx, h=3.4*cm, w=9.0*cm, y=3*cm, lhs='INVOICE TO', rhs='DELIVERY ADDRESS'):
	topBox(c, 0*cm, y, h=h, w=w, title=lhs, content=ctx['addr_invoice'])
	topBox(c, pagewidth-w, y, h=h, w=w, title=rhs, content=ctx['addr_delivery'])
	return y - h

def accountSection(c, ctx, h = 1.25*cm, y=0):
	w=pagewidth / 5.0
	topBox(c, 0*w, y, w=w, h=h, title="ACCOUNT No.", content=ctx['accno'])
	topBox(c, 1*w, y, w=w, h=h, title="YOUR REF.",   content=ctx['custref'])
	topBox(c, 2*w, y, w=w, h=h, title="OUR REF.",    content=ctx['ourref'])
	topBox(c, 3*w, y, w=w, h=h, title="ORDER DATE",  content=ctx['ord_date'])
	topBox(c, 4*w, y, w=w, h=h, title="DATE REQ.",   content=ctx['req_date'])
	y = y-h

	w = pagewidth / 2.0
	topBox(c, 0*w, y, w=w, h=h, title="SALES PERSON", content=ctx['salesperson'])
	topBox(c, 1*w, y, w=w, h=h, title="INSTRUCTIONS", content=ctx['instructions'])
	return y-h

def writeDelnote(c, ctx):
	for mark in ['CUSTOMER COPY', 'ACCOUNTS COPY']:
		for page in ctx:
			deliveryNotePage(c, page, mark)

def deliveryNotePage(c, ctx, mark):	
	
	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)
	
	watermark(c, mark=mark)
	outline(c)
	headerDetails(c, ctx)

	y = rightHeaderBlock(c, ctx, y = 27.2*cm)		
	y = addressHorizDoubleBox(c, ctx, y=y-vpad)
	y = accountSection(c, ctx, y=y-vpad)
	
	# base this section on 9 column format, with some *2, *3 width columns
	y = y - vpad
	w = pagewidth / 9.0	
	h = 11*cm
	(x, y0) = topBox(c, 0, y, w=2*w, h=h, title="PRODUCT CODE", content=ctx['prod_code'])
	(x, y0) = topBox(c, x, y, w=5*w, h=h, title="PRODUCT DESCRIPTION", content=ctx['prod_desc'])
	(x, y0) = topBox(c, x, y, w=w,   h=h, title="QTY", content=ctx['prod_qty'], padleft=0.2*cm)
	(x, y)  = topBox(c, x, y, w=w,   h=h, title="UNIT", content=ctx['prod_unit'], padleft=0.2*cm)
	
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

def writeInvoice(c, ctx):
	for mark in ['CUSTOMERS COPY', 'ACCOUNTS COPY']:
		for page in ctx:
			accountNotePage(c, page, mark)

def writeCrednote(c, ctx):
	writeInvoice(c, ctx)

def accountNotePage(c, ctx, mark):
		
	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)
	
	watermark(c, mark=mark)
	outline(c)
	headerDetails(c, ctx, doctype=ctx['doctype'])

	y = rightHeaderBlock(c, ctx, y = 27.2*cm)		
	y = addressHorizDoubleBox(c, ctx, lhs='INVOICE ADDRESS', y=y-vpad)
	y = accountSection(c, ctx, y=y-vpad)
	
	# 8 column section, individual widths
	y = y - vpad
	h = 11*cm
	(x, y0) = topBox(c, 0, y, w=2.4*cm, h=h, ht=0.9*cm, title="PRODUCT CODE", content=ctx['prod_code'], padleft=0.2*cm, align='c');
	(x, y0) = topBox(c, x, y, w=6.6*cm, h=h, ht=0.9*cm, title="PRODUCT DESCRIPTION", content=ctx['prod_desc'], padleft=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=1.5*cm, h=h, ht=0.9*cm, title="QTY", content=ctx['prod_qty'], padleft=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=2.0*cm, h=h, ht=0.9*cm, title="PRICE", content=ctx['prod_price'], padleft=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=1.7*cm, h=h, ht=0.9*cm, title="UNIT", content=ctx['prod_unit'], padleft=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=1.5*cm, h=h, ht=0.9*cm, title="", content=ctx['prod_blank'], padleft=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=2.5*cm, h=h, ht=0.9*cm, title="NET AMOUNT", content=ctx['prod_net'], padleft=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=pagewidth-x, h=h, ht=0.9*cm, title="VAT\nCODE", content=ctx['prod_vcode'], padleft=0.2*cm, align='c')
	
	w = 8.0*cm
	(x, y) = leftBox(c, pagewidth-w, y0, w=w, title='TOTAL NET', content=ctx['tot_net'])
	(x, y) = leftBox(c, pagewidth-w, y,  w=w, title='TOTAL VAT', content=ctx['tot_vat'])
	(x, y) = leftBox(c, pagewidth-w, y,  w=w, title='AMOUNT DUE', content=ctx['tot_due'])

	y = y0 - vpad
	h = 2.4*cm
	(x, y0) = topBox(c, 0, y, w=2.5*cm, h=h, title="VAT CODE", content=ctx['summ_code'], padleft=0.2*cm, align='c');
	(x, y0) = topBox(c, x, y, w=2.8*cm, h=h, title="NET", content=ctx['summ_netamt'], padleft=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=2.8*cm, h=h, title="VAT RATE", content=ctx['summ_rate'], padleft=0.2*cm, align='c')
	(x, y)  = topBox(c, x, y, w=2.8*cm, h=h, title="VAT", content=ctx['summ_vat'], padleft=0.2*cm, align='c')

	(x, y0) = topBox(c, 0, y-vpad, w=x, h=h, title="", content=ctx['summ_box'], ht=0)

	c.showPage()

def writePage(drawfn, content, count=0):
	from reportlab.pdfgen import canvas
	
	p = jobdir + "%s.pdf" % str(count)
	c = canvas.Canvas(p, pagesize=A4)
 	print('formatting %s to %s with %s' % (content, p, drawfn))
 	drawfn(c, content)
 	c.save()

	return p

class DocFormatter(object):
	def format(self, ctx):
		print('formatting %s' % ctx['name'])
		mname = 'write' + ctx['templ'].title()
		if hasattr(self, mname):
			return self.writePage( getattr(self, mname), ctx['parsed'], ctx['name'])
		print('Warning: No formatting function %s' % mname)
		return []

	def writeInvoice(self,c, ctx):
		for mark in ['CUSTOMERS COPY', 'ACCOUNTS COPY']:
			for page in ctx:
				accountNotePage(c, page, mark)

	def writeCrednote(self,c, ctx):
		writeInvoice(c, ctx)

	def writeDelnote(self,c, ctx):
		for mark in ['CUSTOMER COPY', 'ACCOUNTS COPY']:
			for page in ctx:
				deliveryNotePage(c, page, mark)

	def writePage(self,drawfn, content, count=0):
		from reportlab.pdfgen import canvas
	
		p = jobdir + "%s.pdf" % str(count)
		c = canvas.Canvas(p, pagesize=A4)
	 	print('formatting %s to %s with %s' % (content, p, drawfn))
	 	drawfn(c, content)
 		c.save()

		return p

if __name__=="__main__":
	# launch the server on the specified port
	try:
		os.makedirs(jobdir)
		os.makedirs(rawdir)

	except:
		pass

	chuff = dict(date='04/10/12', doc_num='731/289073', 
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
				prod_code="SMP109\n"*sz,
				prod_desc="CH CHEESY BOISES Bord Sec     07\n"*sz,
				prod_qty="3\n"*sz,
				prod_unit="BOTT\n"*sz
			)

		ctx.append( dict(order.items() + chuff.items()))

	p = writePage(writeDelnote, ctx, count=0)

 	try:
		os.startfile(p)
	except:
		pass

	# CREDIT NOTE / STATEMENT / INVOICE paperwork
	extra = dict( doctype='CREDIT NOTE', 
		summ_code='5\n'*4, summ_netamt='12345.67\n'*4,summ_rate='0.00\n'*4, summ_vat='0.00\n'*4,
		tot_net='12345.00', tot_vat='0.00', tot_due='12345.00')

	ctx = []
	for page,sz in enumerate([18,3]):
		order = dict(
				page=str(page+1),
				prod_code="SMP109\n"*sz,
				prod_desc="CH CHEESY BOISES Bord Sec     07\n"*sz,
				prod_qty="3\n"*sz,
				prod_unit="BOTT\n"*sz,
				prod_price="200.00\n"*18,
				prod_blank="\n"*18,
				prod_net="1499.40\n"*18,
				prod_vcode="5\n"*18
			)

		ctx.append( dict(order.items() + chuff.items() + extra.items()))


	writePage(writeInvoice, ctx, count=1)

    
