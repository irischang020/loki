import h5py
from loki.utils.postproc_helper import *
import os

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

def make_streak_mask(shots, num_bins=100):
    
    # find all the outlier positions
    outlier_pos=[]
    for ss in shots:
        outlier_pos.extend(np.where( is_outlier(ss) )[0])
    outlier_pos = np.array(outlier_pos)
    # statitistics
    bins=np.histogram( outlier_pos, bins=num_bins)
    edges=(bins[1][1:]+bins[1][:-1])/2
    floor = int(shots.shape[0]/num_bins)
    
    # find the peaks
    cutoffs=bins[0]>floor
    indices = np.nonzero(cutoffs[1:] != cutoffs[:-1])[0] + 1
    b = np.split(edges, indices)
    b = np.array( b[0::2] if cutoffs[0] else b[1::2] )
    
    # chunks of indices to mask
    chunks = [range(int(np.floor(bb[0])),int(np.ceil(bb[-1]) )+1 ) for bb in b]
    
    streak_mask=np.ones_like(shots[0])
    for cc in chunks:
        
        cc=np.array(cc)
        cc=cc[cc<streak_mask.size]
        streak_mask[cc] =  0
    return streak_mask.astype(bool)

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
out_file = run_file.replace('.tbl','_streaks.h5')
f_out = h5py.File(os.path.join(save_dir, out_file),'w')


if 'polar_mask_binned' in f.keys():
    mask = np.array(f['polar_mask_binned'].value==f['polar_mask_binned'].value.max(), dtype = int)[:1,:]
else:
    mask = np.load('/reg/d/psdm/cxi/cxilp6715/scratch/water_data/binned_pmask_basic.npy')[:1,:]

PI = f['polar_imgs']

qs = np.array([0.2])

# find streaks
# get pulse energy, max pos, max height
print("getting pulse energy per shot...")
ave_shot_energy =PI[:,:1].mean(-1).mean(-1)

energy_treshold = 25000 # arbitrary units after polar interpolation 
# shots going to be used
tags = np.array(sorted(np.where(ave_shot_energy>energy_treshold)[0]))

# divide and find streaks
chunk_size=10000
num_chunks = int(tags.size/chunk_size)+1

print('finding streaks...')
for nc in range(num_chunks):
    chunk_tags=tags[nc*chunk_size:(nc+1)*chunk_size]
    # print chunk_tags
    shots=PI[sorted(chunk_tags)][:,:1,:]

    streak_masks = np.zeros( (shots.shape[0],shots.shape[-1]), dtype = bool )
        
    for idx, ss in enumerate(shots):
        ss*=mask
        sm = make_streak_mask(ss[None,0,:].copy())
        streak_masks[idx] = sm


    f_out.create_dataset('streak_masks_%d'%nc, data = streak_masks)

# consolidate chunks
sm_keys = [kk for kk in f_out.keys() if kk.startswith('streak')]
all_streak_masks=[]
# Consolidate and delete individual datasets
for key in sm_keys:
  all_streak_masks.append(f_out[key].value)

  f_out.__delitem__(key)

all_streak_masks=np.concatenate(all_streak_masks)
print all_streak_masks.shape,tags.size
assert(all_streak_masks.shape[0]==tags.size)
f_out.create_dataset('all_streak_masks',data=all_streak_masks)
f_out.create_dataset('shot_tags',data=tags)

# some stats about the streaks
print('doing stats with the results...')
dists=[]
centers=[]
streak_widths=[]

for ii in range(all_streak_masks.shape[0]):
    X=np.where(all_streak_masks[ii]==0)[0]
    if X.size>1:
        lls,bins=np.histogram(X,bins=2)
        x1=X[X<bins[1]]
        x2=X[X>bins[1]]
        dist=np.abs(x1.mean()-x2.mean())
        center=[x1.mean(),x2.mean()]
        width=[x1.size,x2.size]
    elif X.size==0:
        dist=0
        center=[0,0]
        width=[0,0]
    else:
        dist=0
        center=[X[0],0]
        width=[1,0]

    dists.append(dist)
    centers.append(center)
    streak_widths.append(width)
    
dists=np.array(dists)
centers=np.array(centers)
streak_widths=np.array(streak_widths)

f_out.create_dataset('streak_widths',data=streak_widths)
f_out.create_dataset('streak_centers',data=centers)
f_out.create_dataset('streak_dists',data=dists)

f_out.close()
