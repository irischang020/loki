import h5py
from loki.RingData import DiffCorr
from loki.utils.postproc_helper import *
from loki.utils import stable
from loki.make_tag_pairs import MakeTagPairs
import os

import numpy.ma as ma

import argparse
import numpy as np

import matplotlib.pyplot as plt



def pair_diff_PI(max_pos_cluster_shots, mask,
    degree = 15, 
    qidx_pair = 25):
    print("doing cheby pairing...")
    if max_pos_cluster_shots.shape[0]%2>0:
        max_pos_cluster_shots = max_pos_cluster_shots[:-1]
    # cheby pair within each 
    # pairing with chebyfit polynomials
    # I am going to use the qidx = 25 for pairing
    print("fitting to polynomials....")
    fits = np.zeros( (max_pos_cluster_shots.shape[0],
        max_pos_cluster_shots.shape[-1])
        ,dtype = np.float64 )

    for ii in range(max_pos_cluster_shots.shape[0]):
        shot,_,_ = remove_peaks(max_pos_cluster_shots[ii,qidx_pair].copy(),
            mask[qidx_pair])

        _,_,yfit = fit_periodic(shot, 
            mask=mask[qidx_pair],
                deg=degree,overlap=0.1)
        fits[ii] = yfit
    
    eps = distance.cdist(fits, fits, metric='euclidean')
    # do this so the diagonals are not the minimum, i.e. don't pair shot with itself
    epsI = 1.1 * eps.max(1) * np.identity(eps.shape[0])
    eps += epsI

    shot_preference = np.roll(eps.argsort(1), 1, axis=1)
    pref_dict = {str(E[0]): list(E[1:])
             for E in shot_preference.astype(str)}

    print("stable roommate pair....")
    pairs_dict = stable.stableroomate(prefs=pref_dict)

    pairing = np.array(MakeTagPairs._remove_duplicate_pairs(pairs_dict) )

    print("computing difference intensities...")
    diff_norm = np.zeros( (max_pos_cluster_shots.shape[0]/2, 
        max_pos_cluster_shots.shape[1], 
        max_pos_cluster_shots.shape[-1]), 
        dtype=np.float64 )

    for index, pp in enumerate( pairing ):
        diff_norm[index] = max_pos_cluster_shots[pp[0]]-max_pos_cluster_shots[pp[1]]

    return diff_norm


# load the water run
qidx4pairing = int(sys.argv[1])
f = h5py.File('/reg/d/psdm/cxi/cxilp6715/scratch/combined_tables/finer_q/higher_q/run94.tbl','r')
f_out = h5py.File('/reg/d/psdm/cxi/cxilp6715/scratch/water_data/run94_cheby_corr_%d_.h5'%qidx4pairing,'w')
#######################
use_basic_mask= True

pmask_basic = np.load('/reg/d/psdm/cxi/cxilp6715/scratch/water_data/binned_pmask_basic_higherq.npy')
#######################
PI = f['polar_imgs']

# get pulse energy, max pos, max height
print("getting pulse energy per shot...")
pulse_energy =np.nan_to_num( \
(f['gas_detector']['f_21_ENRC'].value + f['gas_detector']['f_22_ENRC'].value)/2.)

# extract radial profile max and max pos
print("getting rad prof max pos and max height vals...")
num_shots = f['radial_profs'].shape[0]
max_val = np.zeros(num_shots)
max_pos = np.zeros(num_shots)
for idx in range(num_shots):
    y = f['radial_profs'][idx]
    y_interp = smooth(y, beta=0.1,window_size=50)
    max_val[idx]=y_interp.max()
    max_pos[idx]=y_interp.argmax()
# cluster by pulse energy

print("clustering by pulse energy...")
bins = np.histogram(pulse_energy, bins=200)
pulse_energy_clusters = np.digitize(pulse_energy,bins[1])

print "number of clusters: %d" % len ( list(set(pulse_energy_clusters) ) )
unique_clusters = np.array( sorted( list(set(pulse_energy_clusters)) ) )
#do not use shots when pulse energy is too low
pulse_treshold = 1.5 #mJ
for cc in unique_clusters:
    mean_pulse = np.mean ( pulse_energy[pulse_energy_clusters==cc] )
    if mean_pulse<pulse_treshold:
        continue
    else:
        cluster_to_use = unique_clusters[unique_clusters>=cc]
        break

# sub cluster by max height
shot_set_num = 0
norm_corrs = []
shot_nums_per_set = []

print("sorting shots into clusters...")
for cluster_num in cluster_to_use:
    shot_tags = np.where(pulse_energy_clusters==cluster_num)[0]
    if len(shot_tags)<2:
        print "skipping big cluster %d"%cluster_num
        continue

    cluster_max_pos = max_pos[pulse_energy_clusters==cluster_num]
    
    
    bins = np.histogram(cluster_max_pos,bins='fd')
    num_shots = np.where(pulse_energy_clusters==cluster_num)[0].shape[0]
    print "number of shots in cluster: %d"% num_shots
    max_pos_clusters = np.digitize(cluster_max_pos,bins[1])
    unique_clusters = np.array(sorted(list(set(max_pos_clusters))) )

    for cc in unique_clusters:
        cluster_shot_tags = shot_tags[max_pos_clusters==cc]
        if len(cluster_shot_tags)<2:
            print "skipping little cluster %d in big cluster %d"%(cc,cluster_num)
            continue

        order = np.argsort(cluster_shot_tags)
        shots = PI[sorted(cluster_shot_tags)]
        print "number of shots in pairing cluster: %d"% len(cluster_shot_tags)
        # mask and normalize the shots
        if shots.dtype != 'float64':
            # shots need to be float64 or more. 
            # float32 resulted in quite a bit of numerical error 
            shots = shots.astype(np.float64)
        
        norm_shots = np.zeros_like(shots)
        
        for idx, ss in enumerate(shots):
            if use_basic_mask:
                mask = pmask_basic
            else:
                mask = make_mask(ss,zero_sigma=0.0)
            ss *=mask
            
            mean_ss = ss.sum(-1)/mask.sum(-1) 

            ss = ss-mean_ss[:,None]
            norm_shots[idx] = np.nan_to_num(ss*mask)

        #clean up a bit
        del shots
        # for sanity check only
        # if norm_shots.shape[0]%2>0:
        #     norm_shots = norm_shots[:-1]
        # diff_norm=norm_shots[::2]-norm_shots[1::2]
        
        diff_norm = pair_diff_PI(norm_shots, pmask_basic,
                qidx_pair = qidx4pairing)

        # dummy qvalues
        qs = np.linspace(0.1,1.0, diff_norm.shape[1])
        dc = DiffCorr(diff_norm, qs, 0,pre_dif=True)
        ac = dc.autocorr().mean(0)
        norm_corrs.append(ac)
        shot_nums_per_set.append(diff_norm.shape[0])

        # save difference int
        # f_out.create_dataset('norm_diff_%d'%shot_set_num, data = diff_norm)
        # 
        # shot_set_num+=1
    ##############
    # Dubgging
    # break
    ##############
ave_norm_corr = (norm_corrs * \
    (np.array(shot_nums_per_set)/float(np.sum(shot_nums_per_set)))[:,None,None]).sum(0)
if use_basic_mask:
    qs = np.linspace(0.1,1.0, diff_norm.shape[1])
    mask_dc = DiffCorr(mask[None,:], qs, 0, pre_dif=True)
    mask_corr = mask_dc.autocorr().mean(0)
    ave_norm_corr /= mask_corr

f_out.create_dataset('ave_norm_corr',data=ave_norm_corr)
f_out.create_dataset('num_shots',data=np.sum(shot_nums_per_set))

f_out.close()



