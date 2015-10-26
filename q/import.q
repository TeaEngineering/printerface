#!/usr/bin/env q
\c 80 120

/ groups
gr:flip `n`descr!("H S";3 1 40)0:`$"/tmp/groups";
show gr;

/ product list
pr:flip `grp`n`bc`descr`sz`grow`trade`case20`case50`stock!("HH S S S SFFFF ";2 5 1 8 1 30 1 5 1 10 8 7 7 7 36)0:`$"/tmp/pr1";

/invoices (uk date format)
\z 1
invo:flip `docn`onum`acct`custref`salesp`odate`netr`gross!("I I S S S D F F";6 1 6 1 7 1 12 1 20 1 8 1 10 1 10)0:`$"/tmp/inv";
show invo

invline:flip `docn`onum`acct`bc`descr`unitnum`unitcost`unitsz`unitsub!("I I S S S H F S F";6 1 6 1 7 1 10 1 30 1 6 1 8 1 6 1 9)0:`$"/tmp/invline";
show invline

\/bin/mkdir -p data
\cd data
`:pr set pr
`:gr set gr
`:invline set invline
`:invo set invo
\\
