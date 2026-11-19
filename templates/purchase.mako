## Email text offered when emailing a purchase order. See invoice.mako for the variables available.
## Purchase order fields include doc.doc_num, doc.accno, doc.orderdate, doc.custref, doc.ourcontact.
To ${email.name}

Please find attached purchase order ${doc.doc_num}, dated ${doc.orderdate}, for account ${doc.accno}.

Please confirm receipt and let us know when it will be ready for collection.

Kind regards
${company.name}
