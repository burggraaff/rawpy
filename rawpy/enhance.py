from __future__ import division, print_function, absolute_import

import time
import os
import warnings
from functools import partial
import numpy as np

from skimage.filter.rank import median
try:
    import cv2
except ImportError:
    warnings.warn('OpenCV not found, install for faster processing')
    cv2 = None

import rawpy

# TODO handle non-Bayer images

def findBadPixels(paths, find_hot=True, find_dead=True):
    assert find_hot or find_dead
    coords = []
    width = None
    for path in paths:
        t0 = time.time()
        # TODO this is a bit slow, try RawSpeed
        raw = rawpy.imread(path)
        if width is None:
            # we need the width later for counting
            width = raw.raw_image.shape[1]
        print('imread:', time.time()-t0, 's')
    
        # TODO ignore border pixels
        
        rawimg = raw.raw_image
        thresh = max(np.max(rawimg)//150, 20)
        print('threshold:', thresh)
        
        t0 = time.time()
        
        def isCandidate(rawarr, med):
            if find_hot and find_dead:
                np.subtract(rawarr, med, out=med)
                np.abs(med, out=med)
                candidates = med > thresh
            elif find_hot:
                med += thresh
                candidates = rawarr > med
            elif find_dead:
                med -= thresh
                candidates = rawarr < med
            return candidates
        
        pattern = raw.rawpattern
        if pattern.shape[0] == 2:
            # optimized code path for common 2x2 pattern
            # create a view for each color, do 3x3 median on it, find bad pixels, correct coordinates          
            r = 3
            
            if cv2 is not None:
                median_ = partial(cv2.medianBlur, ksize=r)
            else:
                kernel = np.ones((r,r))
                median_ = median(selem=kernel)
            
            # we have 4 colors (two greens are always seen as two colors)
            for offset_y in [0,1]:
                for offset_x in [0,1]:
                    rawslice = rawimg[offset_y::2,offset_x::2]

                    t1 = time.time()
                    med = median_(rawslice)
                    print('median:', time.time()-t1, 's')
                    
                    # detect possible bad pixels
                    candidates = isCandidate(rawslice, med)
                    
                    # convert to coordinates and correct for slicing
                    y,x = np.nonzero(candidates)
                    # note: the following is much faster than np.transpose((y,x))
                    candidates = np.empty((len(y),2), dtype=y.dtype)
                    candidates[:,0] = y
                    candidates[:,1] = x

                    candidates *= 2
                    candidates[:,0] += offset_y
                    candidates[:,1] += offset_x
                    
                    coords.append(candidates)                    
        else:
            # step 1: get color mask for each color
            color_masks = colormasks(raw)
            
            # step 2: median filtering for each channel    
            r = 5
            kernel = np.ones((r,r))
            for mask in color_masks:
                t1 = time.time()
                # skimage's median is quite slow, it uses an O(r) filtering algorithm.
                # There exist O(log(r)) and O(1) algorithms, see https://nomis80.org/ctmf.pdf.
                # Also, we only need the median values for the masked pixels.
                # Currently, they are calculated for all pixels for each color.
                med = median(rawimg, kernel, mask=mask)
                print('median:', time.time()-t1, 's')
                
                # step 3: detect possible bad pixels
                candidates = isCandidate(rawimg, med)
                candidates &= mask
                
                y,x = np.nonzero(candidates)
                # note: the following is much faster than np.transpose((y,x))
                candidates = np.empty((len(y),2), dtype=y.dtype)
                candidates[:,0] = y
                candidates[:,1] = x
                
                coords.append(candidates)
                
        print('badpixel candidates:', time.time()-t0, 's')
    
    # step 4: select candidates that appear on most input images
    # count how many times a coordinate appears
    coords = np.vstack(coords)
    
    # first we convert y,x to array offset such that we have an array of integers
    offset = coords[:,0]*width
    offset += coords[:,1]
    
    # now we count how many times each offset occurs
    t0 = time.time()
    counts = groupcount(offset)
    print('groupcount:', time.time()-t0, 's')
    
    print('found', len(counts), 'bad pixel candidates, cross-checking images..')
    
    # we select the ones whose count is high
    is_bad = counts[:,1] >= 0.9*len(paths)
        
    # and convert back to y,x
    bad_offsets = counts[is_bad,0]
    bad_coords = np.transpose([bad_offsets // width, bad_offsets % width])
    
    print(len(bad_coords), 'bad pixels remaining after cross-checking images')
    
    return bad_coords

def repairBadPixels(raw, coords, method='median'):
    print('repairing', len(coords), 'bad pixels')
    
    # TODO this can be done way more efficiently
    #  -> only interpolate at bad pixels instead of whole image
    #  -> cython? would likely involve for-loops
    #  see libraw/internal/dcraw_fileio.cpp
    
    t0 = time.time()
    
    color_masks = colormasks(raw)
        
    rawimg = raw.raw_image
    r = 5
    kernel = np.ones((r,r))
    for color_mask in color_masks:       
        mask = np.zeros_like(color_mask)
        mask[coords[:,0],coords[:,1]] = True
        mask &= color_mask
        
        # interpolate all bad pixels belonging to this color
        if method == 'mean':
            # FIXME could lead to invalid values if bad pixels are clustered
            raise NotImplementedError
        elif method == 'median':
            # bad pixels won't influence the median and just using
            # the color mask prevents bad pixel clusters from producing
            # bad interpolated values (NaNs)
            smooth = median(rawimg, kernel, mask=color_mask)
        else:
            raise ValueError
        
        rawimg[mask] = smooth[mask]
    
    print('badpixel repair:', time.time()-t0, 's')  
    
    # TODO check how many detected bad pixels are false positives
    #raw.raw_image[coords[:,0], coords[:,1]] = 0

def colormasks(raw):
    colors = raw.rawcolors
    if raw.num_colors == 3 and raw.color_desc == 'RGBG':
        color_masks = [colors == 0,
                       (colors == 1) | (colors == 3),
                       colors == 2]
    else:
        color_masks = [colors == i for i in range(len(raw.color_desc))]
    return color_masks

def groupcount(values):
    """
    :see: https://stackoverflow.com/a/4652265
    """
    values.sort()
    diff = np.concatenate(([1],np.diff(values)))
    idx = np.concatenate((np.where(diff)[0],[len(values)]))
    # note: the following is faster than np.transpose([vals,cnt])
    vals = values[idx[:-1]]
    cnt = np.diff(idx)
    res = np.empty((len(vals),2), dtype=vals.dtype)
    res[:,0] = vals
    res[:,1] = cnt
    return res

if __name__ == '__main__':
    prefix = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'test')
    testfiles = ['iss030e122639.NEF', 'iss030e122659.NEF', 'iss030e122679.NEF',
                 'iss030e122699.NEF', 'iss030e122719.NEF']
    paths = [os.path.join(prefix, f) for f in testfiles]
    coords = findBadPixels(paths)
    print(coords)
    
#     import imageio
#     raw = rawpy.imread(paths[0])
#     if not os.path.exists('test_original.png'):
#         rgb = raw.postprocess()
#         imageio.imsave('test_original.png', rgb)
#     repairBadPixels(raw, coords)
#     rgb = raw.postprocess()
#     imageio.imsave('test_hotpixels_repaired.png', rgb)
    