import h5py
from loki.RingData import DiffCorr
from loki.utils.postproc_helper import *
from loki.utils import stable
import os
from loki.make_tag_pairs import MakeTagPairs

import numpy.ma as ma

import argparse
import numpy as np

import matplotlib.pyplot as plt


parser = argparse.ArgumentParser(description='Compute difference correlation by consecutive pairing.')
parser.add_argument('-r','--run', type=int,
                   help='run number')
parser.add_argument('-t','--samp_type', type=int,
                   help='type of data/n \
# Sample IDs\n\
# -1: Silver Behenate smaller angle\n\
# -2: Silver Behenate wider angle\n\
# 0: GDP buffer\n\
# 1: ALF BUffer\n\
# 2: GDP protein\n\
# 3: ALF protein\n\
# 4: Water \n\
# 5: Helium\n\
# 6: 3-to-1 Recovered GDP')

parser.add_argument('-o','--out_dir', type=str,default = None,
                   help='output dir to save in, overwrites the sample type dir')

parser.add_argument('-d','--data_dir', type=str, default = '/reg/d/psdm/cxi/cxilp6715/scratch/combined_tables/',
                   help='where to look for the polar data')

parser.add_argument('-sa','--save_autocorr', type=bool, default = False,
                    help='if True save all the individual auto corrs')

def sample_type(x):
    return {-1:'AgB_sml',
    -2:'AgB_wid',
     0:'GDP_buf',
     1:'ALF_buf',
     2:'GDP_pro',
     3:'ALF_pro',
     4:'h2o',
     5:'he',
     6:'3to1_rec_GDP_pro'}[x]

def make_streak_mask(test_shot,mask, num_bins=100):
    masked_average = np.sum(test_shot*mask)/mask.sum()
    masked_std = np.sqrt(np.sum( (test_shot- masked_average)**2*mask)/mask.sum() )

    outliers=np.where(test_shot>masked_average+masked_std*1)[0]

    res=int(test_shot.size/num_bins)/2
    num,bins =np.histogram(outliers,bins=num_bins)
    labels=np.digitize(outliers,bins)
    unique_labels=list(set(labels))
    # print outliers[labels==10]

    masked_ranges=[]

    for ll in unique_labels:
        points = outliers[labels==ll]
        if len(points)==0:
            continue
        else:
            ss = np.max( (int(np.min(points))-res ,0 ) )
            ee = np.min( (int(np.max(points) )+res, test_shot.size) )
            masked_ranges.append( range(ss,ee) )

    streak_mask=np.ones_like(test_shot)
    for cc in masked_ranges:
        cc=np.array(cc)
        cc=cc[cc<streak_mask.size]
        streak_mask[cc] =  0
    return streak_mask.astype(bool)

def pair_diff_PI(norm_shots, interp_rps, qs):
    print("doing corr pairing...")
    #dummy qs
    num_phi=norm_shots.shape[-1]
    
    eps = distance.cdist(interp_rps,interp_rps, metric='euclidean')
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
    diff_norm = np.zeros( (norm_shots.shape[0]/2, 
        qs.size, 
        norm_shots.shape[-1]), 
        dtype=np.float64 )

    for index, pp in enumerate( pairing ):
        diff_norm[index] = norm_shots[pp[0]]-norm_shots[pp[1]]

    return diff_norm, pairing


args = parser.parse_args()

# in this script, I will cluster by 1st PC of the radial profile and then pair by 2nd PC
run_num = args.run

if args.samp_type not in [-1,-2,0,1,2,3,4,5,6]:
    print("Error!!!! type of sample does not exist")
    sys.exit()
else:
    sample = sample_type(args.samp_type)

# import run file


data_dir = args.data_dir
if args.out_dir is None:
    save_dir = '/reg/d/psdm/cxi/cxilp6715/scratch/rp_clusters/dif_cor/%s'%sample
else:
    save_dir = os.path.join( args.out_dir, sample)

if not os.path.exists(save_dir):
    os.makedirs(save_dir)

run_file = "run%d.tbl"%run_num

# load the run
f = h5py.File(os.path.join(data_dir, run_file), 'r')

# output file to save data
out_file = run_file.replace('.tbl','_cor.h5')
f_out = h5py.File(os.path.join(save_dir, out_file),'w')


if 'polar_mask_binned' in f.keys():
    mask = np.array(f['polar_mask_binned'].value==f['polar_mask_binned'].value.max(), dtype = int)
else:
    mask = np.load('/reg/d/psdm/cxi/cxilp6715/scratch/water_data/binned_pmask_basic.npy')

PI = f['polar_imgs']

qs = np.linspace(0.2,0.88,35)

# get pulse energy, max pos, max height
print("getting pulse energy per shot...")
ave_shot_energy =PI[:,:4].mean(-1).mean(-1)
# extract radial profile max and max pos
print("getting rad prof max height vals, pos, and interpolating rad profs...")
num_shots = f['radial_profs'].shape[0]

interp_rps = np.zeros( (num_shots,f['radial_profs'].shape[-1]) )
max_pos = np.zeros(num_shots)
for idx in range(num_shots):
    y = f['radial_profs'][idx]
    y_interp = smooth(y, beta=0.1,window_size=30)

    interp_rps[idx]=y_interp
    max_pos[idx] = y_interp.argmax()

# cluster by pulse energy

print("clustering by average shot energy...")
bins = np.histogram(ave_shot_energy, bins=200)
ave_shot_energy_clusters = np.digitize(ave_shot_energy,bins[1])

print "number of clusters: %d" % len ( list(set(ave_shot_energy_clusters) ) )
unique_clusters = np.array( sorted( list(set(ave_shot_energy_clusters)) ) )
#do not use shots when pulse energy is too low
energy_treshold = 25000 # arbitrary units after polar interpolation 
for cc in unique_clusters:
    mean_energy = np.mean ( ave_shot_energy[ave_shot_energy_clusters==cc] )
    if mean_energy<energy_treshold:
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
    shot_tags = np.where(ave_shot_energy_clusters==cluster_num)[0]
    if len(shot_tags)<2:
        print "skipping big cluster %d"%cluster_num
        continue

    
    
    num_shots = np.where(ave_shot_energy_clusters==cluster_num)[0].shape[0]
    print "number of shots in cluster: %d"% num_shots


    cluster_max_pos = max_pos[ave_shot_energy_clusters==cluster_num]
    # print cluster_max_pos
    rad_profs=interp_rps[ave_shot_energy_clusters==cluster_num]

    bins = np.histogram(cluster_max_pos,bins='fd')
    max_pos_clusters = np.digitize(cluster_max_pos,bins[1])
    unique_clusters = np.array(sorted(list(set(max_pos_clusters))) )

    for cc in unique_clusters:
        cluster_shot_tags = shot_tags[max_pos_clusters==cc]
        if len(cluster_shot_tags)<2:
            print "skipping little cluster %d in big cluster %d"%(cc,cluster_num)
            continue

        order = np.argsort(cluster_shot_tags)
        shots = PI[sorted(cluster_shot_tags)]
        # print rad_profs[max_pos_clusters==cc].shape
        rad_profs_set = rad_profs[max_pos_clusters==cc][order]
        print rad_profs_set.shape, shots.shape

        print "number of shots in pairing cluster: %d"% len(cluster_shot_tags)
        # mask and normalize the shots
        if shots.dtype != 'float64':
            # shots need to be float64 or more. 
            # float32 resulted in quite a bit of numerical error 
            shots = shots.astype(np.float64)
        
        norm_shots = np.zeros_like(shots)
        streak_masks = np.zeros( (shots.shape[0],shots.shape[-1]), dtype = bool )
        
        for idx, ss in enumerate(shots):
            sm = make_streak_mask(ss[0].copy(),mask.copy() )
            streak_masks[idx] = sm
            this_mask=mask.copy()
            this_mask[:4,:] = this_mask[:4,:]*sm[None,:]
            
            ss *= this_mask
            
            mean_ss = ss.sum(-1)/this_mask.sum(-1) 

            ss = ss-mean_ss[:,None]
            norm_shots[idx] = np.nan_to_num(ss*this_mask)

        #clean up a bit
        del shots
        # for sanity check only
        if norm_shots.shape[0]%2>0:
            norm_shots = norm_shots[:-1]
            rad_profs_set=rad_profs_set[:-1]
            cluster_shot_tags=sorted(cluster_shot_tags)[:-1]
        # diff_norm=norm_shots[::2]-norm_shots[1::2]


        diff_norm, pairing = pair_diff_PI(norm_shots, rad_profs_set,qs)
        diff_pair = np.zeros( (diff_norm.shape[0] , 2 ))
        diff_streak_masks = np.zeros( (diff_norm.shape[0] , diff_norm.shape[-1] ),dtype=bool)

        for index, pp in enumerate( pairing ):
            diff_pair[index,0] = cluster_shot_tags[pp[0]]
            diff_pair[index,1] = cluster_shot_tags[pp[1]]
            diff_streak_masks[index] = streak_masks[pp[0]]*streak_masks[pp[1]]

        
        dc = DiffCorr(diff_norm, qs, 0,pre_dif=True)
        all_diff_masks=np.array([mask]*diff_norm.shape[0])
        all_diff_masks[:,:4,:]= diff_streak_masks[:,None,:]*all_diff_masks[:,:4,:]
        mask_dc= DiffCorr(all_diff_masks.copy(),qs,0,pre_dif=True)
        mask_corr = mask_dc.autocorr()
        print "mask corr shape:"
        print mask_corr.shape

        ac = dc.autocorr() / mask_corr
        norm_corrs.append(ac.mean(0))
        shot_nums_per_set.append(diff_norm.shape[0])
        f_out.create_dataset('pairing_%d'%shot_set_num, data = diff_pair)
        f_out.create_dataset('streak_masks_%d'%shot_set_num, data = streak_masks)

        if args.save_autocorr:
            f_out.create_dataset('autocorr_%d'%shot_set_num, data = ac)
        del streak_masks
        del ac

        shot_set_num+=1
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


f_out.create_dataset('ave_norm_corr',data=ave_norm_corr)
f_out.create_dataset('num_shots',data=np.sum(shot_nums_per_set))
f_out.create_dataset('qvalues',data=qs)
f_out.create_dataset('basic_mask',data=mask)

pair_keys = [kk for kk in f_out.keys() if kk.startswith('pairing')]
all_pairing=[]
# Consolidate and delete individual datasets
for key in pair_keys:
  all_pairing.append(f_out[key].value)

  f_out.__delitem__(key)

all_pairing=np.concatenate(all_pairing)
f_out.create_dataset('all_pairings',data=all_pairing)


sm_keys = [kk for kk in f_out.keys() if kk.startswith('streak')]
all_streak_masks=[]
# Consolidate and delete individual datasets
for key in sm_keys:
  all_streak_masks.append(f_out[key].value)

  f_out.__delitem__(key)

all_streak_masks=np.concatenate(all_streak_masks)
f_out.create_dataset('all_streak_masks',data=all_streak_masks)
# print all_pairing

if args.save_autocorr:
    print("cleaning up and closing file...")
    corr_keys = [kk for kk in f_out.keys() if kk.startswith('autocorr')]
    all_corrs=[]
    # Consolidate and delete individual datasets
    for key in corr_keys:
      all_corrs.append(f_out[key].value)

      f_out.__delitem__(key)

    all_corrs=np.concatenate(all_corrs)
    f_out.create_dataset('all_autocorrs',data=all_corrs)

f_out.close()