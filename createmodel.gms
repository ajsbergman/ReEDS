$include b_inputs.gms

$ifthene.finito_link %GSw_FINITO_Link% == 1
$include finito/model/finito_input.gms
$endif.finito_link

$ifthene.finito_link %GSw_FINITO_Link% == 1
$include finito/model/finito_vars_eqs.gms
$endif.finito_link

$include c_supplymodel.gms

$ifthene.finito_link %GSw_FINITO_Link% == 1
$include finito/model/finito_model.gms
$endif.finito_link

$include c_supplyobjective.gms
$include c_mga.gms
$include d_solveprep.gms
