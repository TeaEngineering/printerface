## Email text offered when emailing an invoice. Copy changes into ~/printerface/templates/invoice.mako
## (or use Settings > Email Templates); this file is the default until you do.
##
## Available: ${doc.<field>} for the invoice (doc.ourref, doc.doc_num, doc.accno, doc.tot_due, doc.customer ...),
## ${email.name}, ${job.name}, ${company.name}. If the account has several invoices in the print run,
## doc is the last one and "% for d in docs:" ... "% endfor" visits each of them.
To ${email.name}

Please find your latest invoice ${doc.ourref} attached for account ${doc.accno}, for £${doc.tot_due}.
