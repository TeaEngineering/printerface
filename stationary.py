import ConfigParser
import reportlab
import os
import sys

from reportlab.pdfgen import canvas

config = ConfigParser.ConfigParser()
config.read('defaults.cfg')
config.read(os.path.expanduser('~/printerface/email.cfg'))

from reportlab.lib.units import cm
from reportlab.lib.pagesizes import A4, landscape

pagewidth = A4[0] - 2*0.8*cm
vpad = 0.4*cm
top = 27.6*cm

def headerDetails(c, ctx, doctype="DELIVERY NOTE", terms_key='terms'):
	c.saveState()
	c.setFillColorRGB(0,0,0)

	textobject = c.beginText(0*cm, top-1.5*cm)
	textobject.setFont("Helvetica", 8)
	textobject.textLines(config.get('Printing', 'address').split("\\n"))
	c.drawText(textobject)

	textobject = c.beginText(5.5*cm, top-1.5*cm)
	textobject.setFont("Helvetica", 8)
	textobject.textLine(config.get('Printing', 'vatreg'))
	textobject.textLine(config.get('Printing', 'fax1'))
	textobject.textLine(config.get('Printing', 'fax2'))
	textobject.textLine(config.get('Printing', 'email'))
	textobject.textLine(config.get('Printing', 'website'))
	c.drawText(textobject)

	c.setFont("Helvetica", 18)
	c.drawRightString(pagewidth, top, doctype)
	c.restoreState()
	c.drawImage(os.path.expanduser(config.get('Printing', 'logo')) , 0.0*cm, top-1.1*cm, width=7.0*cm,height=1.8*cm, preserveAspectRatio=True, anchor='sw')
	if config.get('Printing', 'logo2'):
		c.drawImage(os.path.expanduser(config.get('Printing', 'logo2')), 5.0*cm, top-0.9*cm, width=5.0*cm,height=1.4*cm, preserveAspectRatio=True, anchor='sw')

	c.setFont("Helvetica", 10)
	c.drawString(0, 0.40*cm, config.get('Printing', terms_key))

	# marker of progress on CLI
	sys.stdout.write('.')
	sys.stdout.flush()

def topBox(c, x, y, title="Title", content="The quick brown", w=2*cm, h=2.0*cm, pad=0.3*cm, align='l', ht=0.45*cm, fontsz=10.5,font='Helvetica', colfmt='l'):
	c.saveState()
	c.translate(x,y)
	c.rect(0.0,0,w,-h)

	c.saveState()
	c.setFillColorRGB(0.95,0.95,0.95)
	c.rect(0.0,0,w,-ht, fill=True)
	c.restoreState()

	hfontsz = 7
	c.setFont("Helvetica", hfontsz)
	lineheight = hfontsz * 1.2
	if align=='c':
		for lineno, text in enumerate(title.splitlines()):
			c.drawCentredString(w*0.5, -.33*cm*(lineno+1), text)
	else:
		c.drawString(0.8*cm, -.33*cm, title)

	# default "leading" (line spacing) is 120% of the font size, in points. The native unit of reportlib is points
	lineheight = fontsz * 1.3
	c.setFont(font, fontsz)
	for lineno, line in enumerate(content.split('\n')):
		if colfmt == 'da':
			c.drawAlignedString(w - pad, -(0.52*cm + ht + lineheight*lineno), line)
		elif colfmt == 'dr':
			c.drawRightString(w-pad, -(0.52*cm + ht + lineheight*lineno), line)
		elif colfmt == 'dc':
			c.drawCentredString(w/2, -(0.52*cm + ht + lineheight*lineno), line)
		else:
			c.drawString(pad, -(0.52*cm + ht + lineheight*lineno), line)

	c.restoreState()
	return (x+w, y-h)

def stTopBox(c, x, y, title="Title", content="The quick brown", w=2*cm, h=2.0*cm, ht=0.45*cm, pad=0.1*cm, colfmt='l'):
	return topBox(c, x, y, title=title, content=content, w=w, h=h, pad=pad, align='c', fontsz=8, ht=ht, colfmt=colfmt)

def leftBox(c, x, y, title="Title", content="Quick brown", h=0.85*cm, w=2.0*cm, padding=0.3*cm, split=0.5, colfmt='l'):
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
		if colfmt == 'dr':
			c.drawRightString(w-p, -h+p, content)
		else:
			c.drawString(w*split + p, -h+p, content)
	else:
		c.drawCentredString(w*0.5 + p, -h+p, content)
	c.restoreState()
	return (x+w, y-h)

def watermark(c, mark='CUSTOMER COPY',fontsz=54,x=pagewidth/2):
	c.saveState()
	c.setFillColorRGB(0.85,0.85,0.85)
	c.setFont("Helvetica-Bold", fontsz)
	c.drawCentredString(x, 7.5*cm, mark)
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
	(x, y) = leftBox(c, pagewidth-w, y, w=w, title='DOCUMENT No.', content=ctx['doc_num'].replace('\n',' '))
	return y

def addressHorizDoubleBox(c, ctx, h=3.4*cm, w=9.0*cm, y=3*cm, lhs='INVOICE TO', rhs='DELIVERY ADDRESS'):
	topBox(c, 0*cm, y, h=h, w=w, title=lhs, content=ctx['addr_invoice'])
	topBox(c, pagewidth-w, y, h=h, w=w, title=rhs, content=ctx.get('addr_delivery', ctx['addr_invoice']))
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
	topBox(c, 1*w, y, w=w, h=h, title="INSTRUCTIONS", content=ctx['instructions'].replace('\n', ' '))
	return y-h

def deliveryNotePage(c, ctx, mark):

	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)

	watermark(c, mark=mark)
	#outline(c)
	headerDetails(c, ctx)

	y = rightHeaderBlock(c, ctx, y = 27.2*cm)
	y = addressHorizDoubleBox(c, ctx, y=y-vpad)
	y = accountSection(c, ctx, y=y-vpad)

	# base this section on 9 column format, with some *2, *3 width columns
	y = y - vpad
	w = pagewidth / 9.0
	h = 11*cm
	(x, y0) = topBox(c, 0, y, w=2*w, h=h, title="PRODUCT CODE", content=ctx['prod_code'], font='Courier')
	(x, y0) = topBox(c, x, y, w=5*w, h=h, title="PRODUCT DESCRIPTION", content=ctx['prod_desc'], font='Courier')
	(x, y0) = topBox(c, x, y, w=w,   h=h, title="QTY", content=ctx['prod_qty'], pad=0.2*cm, colfmt='dr', font='Courier')
	(x, y)  = topBox(c, x, y, w=w,   h=h, title="UNIT", content=ctx['prod_unit'], pad=0.2*cm, font='Courier')

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

def accountNotePage(c, ctx, mark):

	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)

	watermark(c, mark=mark)
	#outline(c)
	headerDetails(c, ctx, doctype=ctx['doctype'])

	y = rightHeaderBlock(c, ctx, y = 27.2*cm)
	y = addressHorizDoubleBox(c, ctx, lhs='INVOICE ADDRESS', y=y-vpad)
	y = accountSection(c, ctx, y=y-vpad)

	# 8 column section, individual widths
	y = y - vpad
	h = 11*cm
	(x, y0) = topBox(c, 0, y, w=2.4*cm, h=h, ht=0.9*cm, title="PRODUCT CODE", content=ctx['prod_code'], pad=0.2*cm, align='c', font='Courier');
	(x, y0) = topBox(c, x, y, w=6.8*cm, h=h, ht=0.9*cm, title="PRODUCT DESCRIPTION", content=ctx['prod_desc'], pad=0.1*cm, align='c', font='Courier')
	(x, y0) = topBox(c, x, y, w=1.7*cm, h=h, ht=0.9*cm, title="QTY", content=ctx['prod_qty'], pad=0.1*cm, align='c', colfmt='dr', font='Courier')
	(x, y0) = topBox(c, x, y, w=2.0*cm, h=h, ht=0.9*cm, title="PRICE", content=ctx['prod_price'], pad=0.1*cm, align='c', colfmt='dr', font='Courier')
	(x, y0) = topBox(c, x, y, w=1.7*cm, h=h, ht=0.9*cm, title="UNIT", content=ctx['prod_unit'], pad=0.1*cm, align='c', font='Courier')
	(x, y0) = topBox(c, x, y, w=1.5*cm, h=h, ht=0.9*cm, title="", content=ctx['prod_blank'], pad=0.1*cm, align='c', font='Courier')
	(x, y0) = topBox(c, x, y, w=2.5*cm, h=h, ht=0.9*cm, title="NET AMOUNT", content=ctx['prod_net'], pad=0.8*cm, align='c', colfmt='da', font='Courier')
	(x, y0) = topBox(c, x, y, w=pagewidth-x, h=h, ht=0.9*cm, title="VAT\nCODE", content=ctx['prod_vcode'], pad=0.1*cm, align='c', colfmt='dc', font='Courier')

	w = 8.0*cm
	(x, y) = leftBox(c, pagewidth-w, y0, w=w, title='TOTAL NET', content=ctx['tot_net'], colfmt='dr')
	(x, y) = leftBox(c, pagewidth-w, y,  w=w, title='TOTAL VAT', content=ctx['tot_vat'], colfmt='dr')
	(x, y) = leftBox(c, pagewidth-w, y,  w=w, title='AMOUNT DUE', content=ctx['tot_due'], colfmt='dr')

	y = y0 - vpad
	h = 2.4*cm
	(x, y0) = topBox(c, 0, y, w=2.5*cm, h=h, title="VAT CODE", content=ctx['summ_code'], pad=0.2*cm, align='c');
	(x, y0) = topBox(c, x, y, w=2.8*cm, h=h, title="NET", content=ctx['summ_netamt'], pad=0.2*cm, align='c', colfmt='dr')
	(x, y0) = topBox(c, x, y, w=2.8*cm, h=h, title="VAT RATE", content=ctx['summ_rate'], pad=0.2*cm, align='c', colfmt='dr')
	(x, y)  = topBox(c, x, y, w=2.8*cm, h=h, title="VAT", content=ctx['summ_vat'], pad=0.2*cm, align='c', colfmt='dr')

	(x, y0) = topBox(c, 0, y-vpad, w=x, h=h, title="", content=ctx['summ_box'].strip(), ht=0)

	c.showPage()

def remittancePage(c, ctx, mark):

	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)

	watermark(c, mark=mark)
	headerDetails(c, ctx, doctype='REMITTANCE ADVICE')

	y = rightHeaderBlock(c, ctx, y = 27.2*cm)
	y = addressHorizDoubleBox(c, ctx, lhs='INVOICE ADDRESS', y=y-vpad)

	# 6 column section, individual widths
	y = y - vpad
	h = 15.5*cm
	(x, y0) = topBox(c, 0, y, w=4.1*cm, h=h, title="TRANSACTION", content=ctx['rem_desc'], pad=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=3.3*cm, h=h, title="OUR REFERENCE", content=ctx['rem_ourref'], pad=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=3.3*cm, h=h, title="YOUR REFERENCE", content=ctx['rem_yourref'], pad=0.2*cm, align='c')
	x3 = x
	(x, y0) = topBox(c, x, y, w=2.8*cm, h=h, title="NET", content=ctx['rem_net'], pad=0.2*cm, align='c', colfmt='dr')
	(x, y0) = topBox(c, x, y, w=2.8*cm, h=h, title="VAT", content=ctx['rem_vat'], pad=0.2*cm, align='c', colfmt='dr')
	(x, y0) = topBox(c, x, y, w=pagewidth-x, h=h, title="GROSS", content=ctx['rem_gross'], pad=0.2*cm, align='c', colfmt='dr')

	w = 10.0*cm
	(x, y) = leftBox(c, x3, y0, w=pagewidth-x3, title='LESS DISCOUNT', content=ctx['amt_discount'], colfmt='dr')
	(x, y) = leftBox(c, x3, y,  w=pagewidth-x3, title='AMOUNT ENCLOSED', content=ctx['amt_encl'], colfmt='dr')

	(x, y0) = topBox(c, 0, y-vpad, w=x, h=1.6*cm, title="", content=ctx['instructions'], ht=0)

	c.showPage()

def purchasePage(c, ctx, mark):
	price_col, price_tot = ('', '')
	if 'MASTER' in mark or 'BOOKING IN' in mark:
		price_col = ctx['prod_price']
		price_tot = ctx['tot_net']

	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)

	watermark(c, mark=mark, x=6.7*cm, fontsz=36)
	headerDetails(c, ctx, doctype='PURCHASE ORDER', terms_key='terms_purch')

	y = rightHeaderBlock(c, ctx, y = 27.2*cm)
	y = addressHorizDoubleBox(c, ctx, lhs='ORDER TO', y=y-vpad)

	# 8 column section, individual widths
	y = y - vpad
	h = 1.25*cm
	w = pagewidth/3.0
	(x, y0) = topBox(c, 0, y, w=w, h=h, title="ACCOUNT", content=ctx['accno'], pad=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=w, h=h, title="YOUR REFERENCE", content=ctx['custref'], pad=0.2*cm, align='c')
	(x, y) = topBox(c, x, y, w=w, h=h, title="YOUR CONTACT", content=ctx['ourref'], pad=0.2*cm, align='c')
	x3 = x
	(x, y0) = topBox(c, 0, y, w=w, h=h, title="OUR CONTACT", content=ctx['ourcontact'], pad=0.2*cm, align='c')
	(x, y0) = topBox(c, x, y, w=3.1*cm, h=h, title="ORDER DATE", content=ctx['orderdate'], pad=0.2*cm, align='c')
	(x, y) = topBox(c, x, y, w=pagewidth-x, h=h, title="INSTRUCTIONS", content=ctx['instructions'], pad=0.2*cm, align='c')

	w = 10.0*cm

	# 6 column section, individual widths
	y = y - vpad
	h = 12.4*cm
	ht = 0.9*cm
	(x, y0) = topBox(c, 0, y, w=2.4*cm, h=h, ht=ht, title="PRODUCT\nCODE", content=ctx['prod_code'], pad=0.2*cm, align='c', font='Courier',fontsz=9.5)
	(x, y0) = topBox(c, x, y, w=6.5*cm, h=h, ht=ht, title="PRODUCT DESCRIPTION", content=ctx['prod_desc'], pad=0.2*cm, align='c', font='Courier',fontsz=9.5)
	(x, y0) = topBox(c, x, y, w=1.4*cm, h=h, ht=ht, title="QTY", content=ctx['prod_qty'], pad=0.2*cm, align='c', colfmt='dr', font='Courier',fontsz=9.5)
	(x, y0) = topBox(c, x, y, w=1.9*cm, h=h, ht=ht, title="PRICE", content=price_col, pad=0.2*cm, align='c', font='Courier',fontsz=9.5)
	(x, y0) = topBox(c, x, y, w=1.2*cm, h=h, ht=ht, title="UNIT", content=ctx['prod_unit'], pad=0.2*cm, align='c', font='Courier',fontsz=9.5)
	w = pagewidth-vpad-x
	(x0,y1) = topBox(c, x+vpad, y, w=w, ht=ht, title="COLLECTION DELIVERY\nDATE REQUIRED BY", content='', align='c')
	(x0,y1) = topBox(c, x+vpad, y1-vpad, w=w, ht=ht, title="THIS SECTION TO BE COMPLETED\nAND FAXED BACK BY SUPPLIER", content='', align='c')
	(x0,y1) = topBox(c, x+vpad, y1, w=w, ht=ht, title="DATE OF AVAILABILITY", content='', align='c')
	(x0,y1) = topBox(c, x+vpad, y1, w=w, ht=ht, title="ACTUAL COLLECTION DATE", content='', align='c')
	(x0,y1) = topBox(c, x+vpad, y1, w=w, ht=ht, h=h-(y-y1), title="IMPORTANT NOTES", content='', align='c')

	x = 10.67*cm
	(x, y1) = leftBox(c, x, y0-vpad, w=pagewidth-x, title='TOTAL NET', content=price_tot, colfmt='dr')

	w = 10.4*cm
	(x, y) = topBox(c, 0, y0-vpad, w=w, h=2.1*cm, pad=0.2*cm, title="THIS INSTRUCTION IS MANDATORY", align='c', content=config.get('Printing', 'purch_instruction_fr').replace("\\n", '\n'))
	(x, y) = topBox(c, 0, y, w=w, h=1.6*cm, title="", pad=0.2*cm, ht=0, content=config.get('Printing', 'purch_instruction_en').replace("\\n", '\n'))

	c.showPage()

def statementPage(c, ctx, mark):

	# move the origin up and to the left
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)

	# entire page breaks at 12cm, LHS is tear off (originally perferated)
        watermark(c, mark=mark, x=6*cm, fontsz=36)
        watermark(c, mark=mark, x=16*cm, fontsz=20)

	headerDetails(c, ctx, 'Statement')

	divide = 12*cm

	textobject = c.beginText()
	textobject.setTextOrigin(divide+vpad, top-vpad)
	textobject.setFont("Helvetica", 8)
	textobject.textLines('PLEASE DETACH AND RETURN\nWITH YOUR REMITTANCE TO:')
	textobject.textLines(config.get('Printing', 'address').replace("\\n", '\n'))
	textobject.textLines(config.get('Printing', 'fax1'))
	c.drawText(textobject)

	h = 0.85*cm
	y = 24.6*cm
        (x,y0) = topBox(c, 0*cm, y, h=3.8*cm, w=8.2*cm, title='TO', content=ctx['addr_invoice'])
	w = divide - vpad - (x + vpad)
	(x0,y) = topBox(c, x+vpad, y, h=1.25*cm, w=w, title='ACCOUNT NO.', content=ctx['accno'])
	(x0,y) = topBox(c, x+vpad, y, h=1.25*cm, w=w, title='DATE', content=ctx['date'])
	(x0,y) = topBox(c, x+vpad, y, h=y-y0, w=w, title='PAGE No.', content=ctx['page'])

	x = divide+vpad; y = 24.6*cm; w=(pagewidth-x)/2
	(x0,y0) = topBox(c, x, y, h=1.25*cm, w=w, title='ACCOUNT NO.', content=ctx['accno'])
	(x0,y)  = topBox(c, x0,y, h=1.25*cm, w=w, title='DATE', content=ctx['date'])
	(x0,y0) = topBox(c, x, y, h=1.25*cm, w=w, title='PAGE No.', content=ctx['page'])
	(x0,y)  = topBox(c, x0,y, h=1.25*cm, w=w, title='DATE RECEIVED', content=ctx['date_recv'])
	(x0,y)  = topBox(c, x, y, h=1.25*cm, w=2*w, title='FROM', content=ctx['addr_invoice'].split('\n')[0])

	#y = accountSection(c, ctx, y=y-vpad)

	# 8 column section, individual widths
	y = y - vpad
	h = 15.5*cm; hs=0.8*cm
	(x, y0) = stTopBox(c, 0, y, w=1.3*cm, h=h, title="DATE", content=ctx['prod_date']);
	(x, y0) = stTopBox(c, x, y, w=4.1*cm, h=h, title="OUR REF.                DETAILS", content=ctx['prod_code'])
	(x, y0) = stTopBox(c, x, y, w=1.0*cm, h=h, title="TRANS", content=ctx['prod_trans'])
	(x1,y0) = stTopBox(c, x, y, w=1.6*cm, h=h, title="DEBT", content=ctx['prod_debt'], colfmt='dr')
	(x1,y1) = stTopBox(c, x, y0,w=1.6*cm, h=hs,title="", content=ctx['tot_debt'], ht=0, colfmt='dr')

	(x2,y0) = stTopBox(c, x1, y, w=1.6*cm, h=h, title="CREDIT", content=ctx['prod_credit'], colfmt='dr')
	(x2,y1) = stTopBox(c, x1, y0,w=1.6*cm, h=hs,title="", content=ctx['tot_credit'], ht=0, colfmt='dr')

	w = divide - vpad - x2
	(x3,y0) = stTopBox(c, x2, y, w=w, h=h, title="BALANCE", content=ctx['prod_bal'], colfmt='da', pad=0.85*cm)
	(x3,y1) = stTopBox(c, x2, y0,w=w, h=hs,title="", content=ctx['tot_bal'], ht=0, colfmt='dr')

	x = divide+vpad
	(x, y0) = stTopBox(c, x, y, w=1.6*cm, h=h, title="DATE", content=ctx['prod_date'])
	(x, y0) = stTopBox(c, x, y, w=1.8*cm, h=h, title="OUR REF.", content=ctx['prod_ref'])
	(x, y0) = stTopBox(c, x, y, w=2.5*cm, h=h, title="OUTSTANDING", content=ctx['prod_total'], colfmt='da', pad=0.85*cm)
	(x, y0) = stTopBox(c, x, y, w=pagewidth-x, h=h, title="TICK", content='')

	c.setFont("Helvetica", 8)
	c.drawString(0, y0-vpad, ctx['summ_box'].strip())

	w=(divide-vpad)/4; x=0; y=3.95*cm; h=1.3*cm;
	(x, y0) = stTopBox(c, x, y, w=w, h=h, title="CURRENT", content=ctx['age_curr'], colfmt='dr')
	(x, y0) = stTopBox(c, x, y, w=w, h=h, title="ONE MONTH", content=ctx['age_1m'], colfmt='dr')
	(x, y0) = stTopBox(c, x, y, w=w, h=h, title="TWO MONTHS", content=ctx['age_2m'], colfmt='dr')
	(x, y0) = stTopBox(c, x, y, w=w, h=h, title="THREE MONTHS", content=ctx['age_3m'], colfmt='dr')

	y=y0-vpad; x=0; w=4.5*cm;
	(x, y0) = stTopBox(c, x, y, w=w, h=h, title="CURRENCY", content='')
	(x, y0) = stTopBox(c, x+vpad, y, w=w, h=h, title="AMOUNT DUE", content=ctx['age_due'], colfmt='dr')

	(x, y0) = stTopBox(c, divide+vpad, y, w=4.5*cm, h=h, title="TOTAL TO BE PAID", content=ctx['tot_topay'], colfmt='dr')

	c.saveState()
	c.setDash(array=[5,5])
	c.line(divide,0.9*cm,divide,28*cm)
	c.restoreState()

	c.showPage()

def genericPage(c, data, title=None, fontsz=7, landsc=False, overlay=None, decorate_fn=None):
	# move the origin up and to the left
	pagesize = landscape(A4) if landsc else A4
	c.setPageSize( pagesize )
	c.setFillColorRGB(0,0,0)
	c.translate(0.8*cm,0.8*cm)
	y = pagesize[1] - 1.6*cm

	if title:
		c.setFont("Helvetica", 18)
		c.drawRightString(pagewidth, top, title)
		c.drawImage(os.path.expanduser(config.get('Printing', 'logo')) , 0.0*cm, top-1.1*cm, width=7.0*cm,height=1.8*cm, preserveAspectRatio=True, anchor='sw')
		y = y - 2.0*cm

	textobject = c.beginText()
	textobject.setTextOrigin(0, y)
	textobject.setFont("Courier-Bold", fontsz)
	for line in data.split('\n'):
		textobject.textLine(line.rstrip())
	c.drawText(textobject)

	if overlay:
		c.setFont("Helvetica", 18)
		c.drawRightString(pagesize[0]/2.0, pagesize[1]/2.0, overlay)
	if decorate_fn:
		decorate_fn(c)
	c.showPage()

class DocFormatter(object):
	def __init__(self, pdfdir):
		self.jobdir = pdfdir
		try:
			os.makedirs(jobdir)
		except:
			pass

	def format(self, ctx):
		mname = 'write' + ctx['templ'].title()
		sys.stdout.write('   formatting %s with %s ' % (ctx['name'], mname))

		x = getattr(self, mname)( ctx )
		sys.stdout.write('\n')
		print('      %s' % x[0])
		return x

	def plainFormat(self, ctx):
		return self.writeRaw( ctx )

	def writeInvoice(self, ctx ):
		rendered_pdfs = {}

		for (acc,v) in ctx['parsed'].iteritems():
			p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), acc, "%s-%s.pdf" % (ctx['name'], acc))
			self.create_dirs(p)
			c = canvas.Canvas(p, pagesize=A4)

			for page in v:
				accountNotePage(c, page, 'CUSTOMER COPY')

			c.save()
			rendered_pdfs[ (acc,) ] = os.path.relpath(p, self.jobdir)

		p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), 'accounts', "%s-%s.pdf" % (ctx['name'], 'accounts'))
		self.create_dirs(p)
		c = canvas.Canvas(p, pagesize=A4)

		pages_by_docnum = dict()
		for (acc,v) in ctx['parsed'].iteritems():
			for page in v:
				pages_by_docnum.setdefault(page['doc_num'], []).append(page)
		for k in reversed(sorted(pages_by_docnum.keys())):
			for page in pages_by_docnum[k]:
				accountNotePage(c, page, 'ACCOUNTS COPY')

	 	c.save()
		rendered_pdfs[ ('accounts',) ] = os.path.relpath(p, self.jobdir)

		return rendered_pdfs, ('Group',)

	def writePicklist(self, ctx):
		rendered_pdfs = {}
		p = os.path.join(self.jobdir, 'raw', ctx['ts'].strftime('%Y%m'), "%s-%s.pdf" % (ctx['name'], 'pick'))
		self.create_dirs(p)
		c = canvas.Canvas(p, pagesize=A4)

		for (acc,v) in ctx['parsed'].iteritems():
			for page in v:
				data = page['data']

				def decorate(c):
					c.setFont("Helvetica", 13)
					c.drawCentredString(A4[0]/2.0, 27*cm, page['hdr'] + page['dt'] + '  ' + page['page'])
					if 'TOTAL FOR' in page['data']:
						c.drawString(0*cm, 2*cm, 'Total weight _______________  Picked by _________________  Time in  ____________')
						c.drawString(0*cm, 1*cm, 'Total cases  _______________  Checked by _______________  Time out ____________')

				#data = '\n'.join(line for line in page['data'].split('\n') if line.rstrip())
				genericPage(c, data, title='Picking list', fontsz=9, decorate_fn=decorate)

		c.save()
		rendered_pdfs[ ('pick',) ] = os.path.relpath(p, self.jobdir)
		return rendered_pdfs, ('Group',)

	def create_dirs(self, path):
		head, tail = os.path.split(path)
		try:
			os.makedirs(head)
		except OSError:
			pass

	def writeRaw(self, ctx):
		rendered_pdfs = {}
		p = os.path.join(self.jobdir, 'raw', ctx['ts'].strftime('%Y%m'), "%s-%s.pdf" % (ctx['name'], 'plain'))
		self.create_dirs(p)
		c = canvas.Canvas(p, pagesize=A4)
		landsc, fontsz, row, cols = ctx['autofmt']

		pages = filter(None, ctx['plain'].strip().split("\f"))
		for page in pages:
			genericPage(c, page, title=None, fontsz=fontsz, landsc=landsc)

		c.save()
		rendered_pdfs[ ('plain',) ] = os.path.relpath(p, self.jobdir)
		return rendered_pdfs, ('Type',)

	def writeCalibrate(self, ctx):
		rendered_pdfs = {}
		p = os.path.join(self.jobdir, "%s-%s.pdf" % (ctx['name'], 'test'))
		self.create_dirs(p)
		c = canvas.Canvas(p, pagesize=A4)

		for landsc in (True, False):
			for fs in range(6,14):
				v = [ctx['data']]
				for page in v:
					genericPage(c, page, title=None, fontsz=fs, landsc=landsc, overlay='landscape=%d fontsz=%d' % (landsc, fs) )

		c.save()
		rendered_pdfs[ ('test',) ] = os.path.relpath(p, self.jobdir)
		return rendered_pdfs, ('Group',)

	def writeCrednote(self, ctx):
		return self.writeInvoice(ctx)

	def writeStatement(self, ctx):
		rendered_pdfs = {}

		for (acc,v) in ctx['parsed'].iteritems():
			p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), acc, "%s-%s.pdf" % (ctx['name'], acc))
			self.create_dirs(p)
			c = canvas.Canvas(p, pagesize=A4)

		 	for page in v:
				statementPage(c, page, 'CUSTOMER COPY')

	 		c.save()
			rendered_pdfs[ (acc,) ] = os.path.relpath(p, self.jobdir)

		p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), 'accounts', "%s-%s.pdf" % (ctx['name'], 'accounts'))
		self.create_dirs(p)
		c = canvas.Canvas(p, pagesize=A4)

		for (acc,v) in ctx['parsed'].iteritems():
		 	for page in v:
				statementPage(c, page, 'ACCOUNTS COPY')

	 	c.save()
		rendered_pdfs[ ('accounts',) ] = os.path.relpath(p, self.jobdir)

		# protocol: key tuples must all be same length, second tuple is key descriptions
		return rendered_pdfs, ('Group',)

	def writeDelnote(self, ctx):
		rendered_pdfs = {}
		p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), 'accounts', "%s-%s.pdf" % (ctx['name'], 'accounts'))
		self.create_dirs(p)
		c = canvas.Canvas(p, pagesize=A4)

		for (acc,v) in ctx['parsed'].iteritems():
			for mark in ['CUSTOMER COPY', 'ACCOUNTS COPY']:
				for page in v:
					deliveryNotePage(c, page, mark)

	 	c.save()
		rendered_pdfs[ ('accounts',) ] = os.path.relpath(p, self.jobdir)
		return rendered_pdfs, ('type',)

	def writeRemittance(self, ctx):

		rendered_pdfs = {}

		for (acc,v) in ctx['parsed'].iteritems():

			p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), acc, "%s-%s.pdf" % (ctx['name'], acc))
			self.create_dirs(p)
			c = canvas.Canvas(p, pagesize=A4)

		 	for page in v:
				remittancePage(c, page, 'CUSTOMER COPY')

	 		c.save()
			rendered_pdfs[ (acc,) ] = os.path.relpath(p, self.jobdir)

		p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), 'accounts', "%s-%s.pdf" % (ctx['name'], 'accounts'))
		self.create_dirs(p)
		c = canvas.Canvas(p, pagesize=A4)

		for (acc,v) in ctx['parsed'].iteritems():

		 	for page in v:
				remittancePage(c, page, 'ACCOUNTS COPY')

	 	c.save()
		rendered_pdfs[ ('accounts',) ] =  os.path.relpath(p, self.jobdir)

		# protocol: key tuples must all be same length, second tuple is key descriptions
		return rendered_pdfs, ('Group',)

	def writePurchase(self, ctx):

		rendered_pdfs = {}

		for (acc,v) in ctx['parsed'].iteritems():
			for (bundle, marks) in [ ( '', ['SUPPLIER COPY']), ('-transport', ['TRANSPORTER COPY']), ('-admin', ['MASTER COPY', 'BOOKING IN COPY', 'PRE LOCATION COPY']) ]:

				p = os.path.join(self.jobdir, ctx['ts'].strftime('%Y'), acc, "%s-%s%s.pdf" % (ctx['name'], acc, bundle))
				self.create_dirs(p)
				c = canvas.Canvas(p, pagesize=A4)

				for mark in marks:
		 			for page in v:
						purchasePage(c, page, mark)

		 		c.save()
				rendered_pdfs[ ("%s%s" % (acc, bundle),) ] = os.path.relpath(p, self.jobdir)

		return rendered_pdfs, ('type', )

	# from calibrate-test.pdf
	# orient sz   rows  cols
	# land   6    78    224
	# land   7    66    192
	# land   8    58    167
	# land   9    52    148
	# land   10   46    133
	# land   11   42    120
	# land   12   38    111
	# land   13   35    102
	# port   6    112   156
	# port   7    95    133
	# port   8    83    115
	# port   9    74    112
	# port   10   66    92
	# port   11   60    84
	# port   12   55    76
	# port   13   51    71
	def getBestPageFormat(self, plaintext):
		pages = filter(None, plaintext.strip().split("\f"))

		worst_rows, worst_cols = 0, 0
		for pi, page in enumerate(pages):
			lines = page.splitlines()
			(rows, cols) = (len(lines), max([len(line) for line in lines]))
			# print (' page %d rows %d cols %d' % (pi, rows, cols))
			worst_cols = max(worst_cols, cols)
			worst_rows = max(worst_rows, rows)

		# A4: (landscape, sz, rows, cols) lookup table. Orded by font size, return the first
		# onto which the document fits
		a4_cand = [
			(False, 13,  51 , 71),
			(True, 13,   35,  102),
			(False, 12,  55 , 76),
			(True, 12,   38,  111),
			(False, 11,  60 , 84),
			(True, 11,   42,  120),
			(False, 10,  66 , 92),
			(True, 10,   46,  133),
			(False, 9 ,  74 , 112),
			(True, 9 ,   52,  148),
			(False, 8 ,  83 , 115),
			(True, 8 ,   58,  167),
			(False, 7 ,  95 , 133),
			(True, 7 ,   66,  192),
			(False, 6 ,  112, 156),
			(True, 6 ,   78,  224),
		]

		soln = filter( lambda x: x[2] > worst_rows and x[3] > worst_cols, a4_cand)
		if len(soln):
			sol = soln[0]
			# print(' solution for pages=%d worst r=%d c=%d is %s' % (len(pages), worst_rows, worst_cols, sol))
			return sol
		return a4_cand[-1]

import unittest
from datetime import datetime
class TestStationary(unittest.TestCase):

	def setUp(self):
		pdir = os.path.expanduser("~/printerface/")
		jobdir = pdir + 'pdf/'
		self.formatter = DocFormatter(jobdir)

		self.chuff = dict(date='04/10/12',
			doc_num='731/289073',
			addr_invoice='SAMPLE ACCOUNT\nCHRIS SHUCKSMITH',
			addr_delivery='CHRIS SHUCKSMITH\nFLAT 999 MIDNIGHT TERRACE\n32 GREAT NOWHERE ST. LONDON SE1 W1J\nIF OUT PSE LEAVE WITH THE\nCAT',
			accno='MULTI-21',
			custref='OSCAR FOX',
			ourref='289073',
			ord_date='04/10/12',
			req_date='05/10/12',
			salesperson='SAMPLE ACCOUNT',
			instructions='TO BE DELIVERED LDN0510',
			doctype='DOCTYPE XX',
			tot_net='12345.00',
		)

	def test_delnote(self):
		ctx = {}
		ctx['templ'] = 'delnote'
		ctx['name'] = 'blahdel'
		ctx['doctype'] = 'doctype'
		ctx['ts'] = datetime(2014, 3, 4, 20, 53, 0, 0)
		s = []
		for page,sz in enumerate([18,3]):
			order = dict(
				page=str(page+1),
				prod_code="B1815102\n"*sz,
				prod_desc="CH CHEESY BOISES Bordea Sec 07\n"*sz,
				prod_qty="3\n"*sz,
				prod_price="4\n"*sz,
				prod_blank="\n"*18,
				prod_net="1499.40\n"*18,
				prod_unit="BOTT\n"*sz,
				prod_vcode="5\n"*18,
				# for p/o
				ourcontact="ABC",
				orderdate="78979879",
				# for remittance
				rem_desc='rem_desc',
				rem_ourref='rem_ourref',
				rem_yourref='rem_yourref',
				rem_net='rem_net',
				rem_vat='rem_vat',
				rem_gross='rem_gross',
				amt_discount='amt_discount',
				amt_encl='amt_encl',
			)

			s.append( dict(order.items() + self.chuff.items()))
		ctx['parsed'] = { 'SMP109': s}

		p = self.formatter.format(ctx)
		self.assertEquals( ({('accounts',): '2014/accounts/blahdel-accounts.pdf'}, ('type',) ),  p)

		ctx['templ'] = 'purchase'
		ctx['name'] = 'blahpurch'
		p = self.formatter.format(ctx)
		self.assertEquals( ({	('SMP109',):           '2014/SMP109/blahpurch-SMP109.pdf',
								('SMP109-admin',):     '2014/SMP109/blahpurch-SMP109-admin.pdf',
								('SMP109-transport',): '2014/SMP109/blahpurch-SMP109-transport.pdf'}, ('type',) ),  p)

		ctx['templ'] = 'remittance'
		ctx['name'] = 'blahremit'
		p = self.formatter.format(ctx)
		self.assertEquals( ({('SMP109',): '2014/SMP109/blahremit-SMP109.pdf',
							('accounts',): '2014/accounts/blahremit-accounts.pdf'}, ('Group',) ),  p)

	def test_statement(self):
		ctx = {}
		ctx['templ'] = 'statement'
		ctx['name'] = 'blahstate'
		ctx['doctype'] = 'doctype'
		ctx['ts'] = datetime(2014, 3, 4, 20, 53, 0, 0)
		s = []
		for page,sz in enumerate([18,3]):
			order = dict(
				page=str(page+1),
				prod_code="SMP109\n"*sz,
				prod_ref="REF\n"*sz,
				prod_desc="CH CHEESY BOISES Bord Sec   07\n"*sz,
				prod_qty="3\n"*sz,
				prod_price="4\n"*sz,
				prod_blank="\n"*sz,
				prod_credit="1499.40\n"*sz,
				prod_bal="1499.40\n"*sz,
				prod_debt="1499.40\n"*sz,
				prod_unit="BOTT\n"*sz,
				prod_total="5\n"*sz,
				prod_date="30/10/15\n"*sz,
				prod_trans="T",
				date_recv="20140101",
				tot_debt="34.34",
				tot_credit="34.34",
				tot_bal="12.00",
				tot_topay="16.00",
				summ_box="blah",
				age_curr="12.00",
				age_1m="13.00",
				age_2m="14.00",
				age_3m="15.00",
				age_due="16.00"
			)

			s.append( dict(order.items() + self.chuff.items()))
		ctx['parsed'] = { 'SMP109': s}

		p = self.formatter.format(ctx)
		self.assertEquals( ({('SMP109',): '2014/SMP109/blahstate-SMP109.pdf', ('accounts',): '2014/accounts/blahstate-accounts.pdf'}, ('Group',) ),  p)

	def test_cnote(self):
	 	# CREDIT NOTE / INVOICE paperwork
		extra = dict( doctype='CREDIT NOTE',
			summ_code='5\n'*4,
			summ_netamt='12345.67\n'*4,
			summ_rate='0.00\n'*4,
			summ_vat='0.00\n'*4,
			tot_net='12345.00',
			tot_vat='0.00',
			tot_due='12345.00',
			summ_box='xyz'
		)
		ctx = {}
		ctx['templ'] = 'invoice'
		ctx['name'] = 'blahcn'
		ctx['doctype'] = 'doctype'
		ctx['ts'] = datetime(2014, 1, 4, 20, 53, 0, 0)
		s = []
		for page,sz in enumerate([18,3]):
			order = dict(
				page=str(page+1),
				prod_code="SMP109\n"*sz,
				prod_desc="CH CHEESY BOISES Bord Sec   07\n"*sz,
				prod_qty="3\n"*sz,
				prod_unit="BOTT\n"*sz,
				prod_price="200.00\n"*sz,
				prod_blank="\n"*sz,
				prod_net="1499.40\n"*sz,
				prod_vcode="5\n"*sz
			)
			s.append( dict(order.items() + self.chuff.items() + extra.items()))
		ctx['parsed'] = { 'SMP109': s}
		p = self.formatter.format(ctx)
		self.assertEquals( ({('SMP109',): '2014/SMP109/blahcn-SMP109.pdf', ('accounts',): '2014/accounts/blahcn-accounts.pdf'}, ('Group',) ),  p)

	def test_picklist(self):
		ctx = {}
		ctx['templ'] = 'picklist'
		ctx['name'] = 'pick-a'
		ctx['doctype'] = 'doctype'
		ctx['ts'] = datetime(2014, 3, 4, 20, 53, 0, 0)
		ctx['parsed'] = {'a': [{'data': 'blah '*26 }, {'data': 'fluff '*22 }]}
		p = self.formatter.format(ctx)
		self.assertEquals( ({('pick',): 'raw/201403/pick-a-pick.pdf'}, ('Group',) ),  p)

	def test_calibrate(self):
		# test document to calibrate width/height fontsize matrix
		cols = 240
		rows = 120

		import StringIO
		chunks10 = (cols+9)/10
		f = StringIO.StringIO()
		f.write('' +  ''.join(["%-10d" % (d*10) for d in range(chunks10)]))
		f.write('\n' + ('0123456789' * chunks10))
		for row in range(2,rows):
			f.write('\n%-4d' % row)

		ctx = {}
		ctx['templ'] = 'calibrate'
		ctx['name'] = 'calibrate'
		ctx['doctype'] = 'doctype'
		ctx['data'] = f.getvalue()
		p = self.formatter.format(ctx)

	def test_rawformat(self):
		self.assertEquals( (False, 13,51,71),  self.formatter.getBestPageFormat('ABCDEF') )
		self.assertEquals( (True,  13,35,102), self.formatter.getBestPageFormat('test'*20) )
		self.assertEquals( (False, 8, 83,115), self.formatter.getBestPageFormat('ABCDEF\n'*80) )

		ctx = {}
		ctx['templ'] = 'raw'
		ctx['name'] = 'rawtest'
		ctx['doctype'] = 'doctype'
		ctx['ts'] = datetime(2014, 2, 4, 20, 53, 0, 0)
		ctx['plain'] = 'test12 ' * 20
		ctx['autofmt'] = self.formatter.getBestPageFormat(ctx['plain'])
		p = self.formatter.format(ctx)
		self.assertEquals( ({('plain',): 'raw/201402/rawtest-plain.pdf'}, ('Type',) ),  p)

	def test_plainformat(self):
		ctx = {}
		ctx['name'] = 'rawtest2'
		ctx['plain'] = 'test 1234 ' * 20
		ctx['ts'] = datetime(2014, 3, 4, 20, 53, 0, 0)
		ctx['autofmt'] = self.formatter.getBestPageFormat(ctx['plain'])
		p = self.formatter.plainFormat(ctx)
		self.assertEquals( ({('plain',): 'raw/201403/rawtest2-plain.pdf'}, ('Type',) ),  p)

if __name__=="__main__":
	unittest.main()