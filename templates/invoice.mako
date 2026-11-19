New Invoice${all.s} ${all.numbers}

To ${email.name},

% if all.many:
Please find your latest invoices attached for account ${doc.accno}, for a total of £${all.total}:

% for d in docs:
${d.doc_num}   £${d.tot_due}
% endfor
% else:
Please find your latest invoice ${doc.doc_num} attached for account ${doc.accno}, for £${doc.tot_due}.
% endif

Kind regards
${company.name}
