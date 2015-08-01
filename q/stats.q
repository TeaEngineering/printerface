#!/usr/bin/env q
\c 80 120
\l data

show `$"cheapest";
show 50# `trade xasc select from pr where stock > 0.001, grp <> 98, grp <> 99;
show `$"dearest";
show 50# `trade xdesc select from pr where stock > 0.001;

pivot:{[t]
 u:`$string asc distinct last f:flip key t;
 pf:{x#(`$string y)!z};
 p:?[t;();g!g:-1_ k;(pf;`u;last k:key f;last key flip value t)];
 p}

\c 600 400
show pivot select sum netr by acct, 3 xbar odate.month from invo;
show pivot select sum netr by salesp, 3 xbar odate.month from invo;

