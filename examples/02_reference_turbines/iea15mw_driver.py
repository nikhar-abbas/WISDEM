import os
from wisdem.glue_code.runWISDEM import run_wisdem


## File management
mydir = os.path.dirname(os.path.realpath(__file__))  # get path to this file
fname_wt_input         = mydir + os.sep + 'IEA-15-240-RWT.yaml'
fname_modeling_options = mydir + os.sep + 'modeling_options.yaml'
fname_analysis_options = mydir + os.sep + 'analysis_options.yaml'

wt_opt, analysis_options, opt_options = run_wisdem(fname_wt_input, fname_modeling_options, fname_analysis_options)

print(wt_opt['sse.powercurve.rated_mech'])
print(wt_opt['rlds.frame.root_M'])
print(wt_opt['elastic.precomp.I_all_blades'])
