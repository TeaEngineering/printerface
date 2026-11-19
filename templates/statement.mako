## Email text offered when emailing a statement. See invoice.mako for the variables available.
## Statement fields include doc.accno, doc.date, doc.tot_topay, doc.age_curr, doc.age_1m, doc.age_2m, doc.age_3m.
To ${email.name}

Please find attached your statement dated ${doc.date} for account ${doc.accno}.

The balance to pay is £${doc.tot_topay}.

Kind regards
${company.name}
