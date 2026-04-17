gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_AdvNG_AdvRE/g00files/mattest_all_AdvNG_AdvRE_2050i0.g00 --case=AdvNG_AdvRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_AdvNG_ConRE/g00files/mattest_all_AdvNG_ConRE_2050i0.g00 --case=AdvNG_ConRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_AdvRE/g00files/mattest_all_AdvRE_2050i0.g00 --case=AdvRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_ConNG/g00files/mattest_all_ConNG_2050i0.g00 --case=ConNG
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_ConNG_AdvRE/g00files/mattest_all_ConNG_AdvRE_2050i0.g00 --case=ConNG_AdvRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_ConNG_ConRE/g00files/mattest_all_ConNG_ConRE_2050i0.g00 --case=ConNG_ConRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_ConRE/g00files/mattest_all_ConRE_2050i1.g11 --case=ConRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_Mid_Case/g00files/mattest_all_Mid_Case_2050i0.g00 --case=Mid_Case
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_AdvNG/g00files/mattest_all_restrict_AdvNG_2050i0.g00 --case=restrict_AdvNG
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_AdvNG_AdvRE/g00files/mattest_all_restrict_AdvNG_AdvRE_2050i0.g00 --case=restrict_AdvNG_AdvRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_AdvNG_ConRE/g00files/mattest_all_restrict_AdvNG_ConRE_2050i0.g00 --case=restrict_AdvNG_ConRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_AdvRE/g00files/mattest_all_restrict_AdvRE_2050i0.g00 --case=restrict_AdvRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_ConNG/g00files/mattest_all_restrict_ConNG_2050i0.g00 --case=restrict_ConNG
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_ConNG_AdvRE/g00files/mattest_all_restrict_ConNG_AdvRE_2050i0.g00 --case=restrict_ConNG_AdvRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_ConNG_ConRE/g00files/mattest_all_restrict_ConNG_ConRE_2050i0.g00 --case=restrict_ConNG_ConRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_ConRE/g00files/mattest_all_restrict_ConRE_2050i0.g00 --case=restrict_ConRE
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_all_restrict_Mid_Case/g00files/mattest_all_restrict_Mid_Case_2050i0.g00 --case=restrict_Mid_Case
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_Norestrict_Mid_Case/g00files/mattest_Norestrict_Mid_Case_2050i0.g00 --case=Norestrict_Mid_Case
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_Restrict_Mid_Case_50pct/g00files/mattest_Restrict_Mid_Case_50pct_2050i0.g00 --case=Restrict_Mid_Case_50pct
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_Restrict_Mid_Case_100pct/g00files/mattest_Restrict_Mid_Case_100pct_2050i0.g00 --case=Restrict_Mid_Case_100pct
gams cmm_custom_report.gms r=/projects/finitoreeds/kpitman/ReEDS-2.0/runs/mattest_Restrict_Mid_Case_150pct/g00files/mattest_Restrict_Mid_Case_150pct_2050i0.g00 --case=Restrict_Mid_Case_150pct
gdxmerge o=runs/cmm_custom_2026/merged_materials.gdx runs/cmm_custom_2026/*.gdx 
gdxdump runs/cmm_custom_2026/merged_materials.gdx output=runs/cmm_custom_2026/material_demand.csv symb=material_demand format=csv header="scen,tcat,material,state,year,value"
gdxdump runs/cmm_custom_2026/merged_materials.gdx output=runs/cmm_custom_2026/rep_mat.csv symb=rep_mat format=csv header="scen,material,year,parameter,value"
gdxdump runs/cmm_custom_2026/merged_materials.gdx output=runs/cmm_custom_2026/steel_demand.csv symb=steel_demand format=csv header="scen,tcat,steeltype,year,value"
gdxdump runs/cmm_custom_2026/merged_materials.gdx output=runs/cmm_custom_2026/steel_int_i.csv symb=steel_int_i format=csv header="scen,i,steeltype,value"
gdxdump runs/cmm_custom_2026/merged_materials.gdx output=runs/cmm_custom_2026/steel_int_tcat.csv symb=steel_int_tcat format=csv header="scen,tcat,steeltype,value"