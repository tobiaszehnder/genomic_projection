import numpy as np, pandas as pd, sys, os, glob, heapq, heapq_max, re, itertools
if 'functions' in sys.modules:
  del sys.modules['functions'] # deletes previously imported module so that potential changes will be loaded
from functions import *

# function for computing cosine similarity of 8-mers of reference vs all query projections
def compute_cosine_similarity_ref_qry(seqs):
  
  # compute possible kmers
  ks = [4,6,8]
  possible_kmers = [''.join(p) for k in ks for p in itertools.product(list('ACGT'), repeat=k)]
  kmer_ids = {kmer : get_kmer_id(kmer) for kmer in possible_kmers}
  
  # compute repeat_score for k 4, 6 and 8 and take mean
  # here, taking multiple k is somewhat important to reflect repetitiveness on different scales (e.g. ATATATATATAT vs ACCGTTACCGTTACCGTT)
  rep_scores = pd.DataFrame({i : {j : np.mean([compute_repeat_score(seqs.loc[i,j], possible_kmers, kmer_ids, k=k) for k in ks]) for j in seqs.columns} for i in seqs.index}).T
  rep_scores = rep_scores.loc[:,seqs.columns] # put columns in right order
  
  # count kmers
  k = 8
  kmer_counts_dict_ref = {i : count_kmers(seqs.ref[i], kmer_ids, ks=[8]) for i in seqs.index}
  kmer_counts_dict_qry = {i : {j : count_kmers(seqs.loc[i,j], kmer_ids, ks=[8]) for j in seqs.columns[1:]} for i in seqs.index}
  
  # compute similarity scores
  sim = np.array([[compute_similarity(kmer_counts_dict_ref[i], kmer_counts_dict_qry[i][j], 'cosine') for j in seqs.columns[1:]] for i in seqs.index])
  sim = pd.DataFrame(sim, columns=seqs.columns[1:])
  return sim, rep_scores

# precompute poisson_estimate for computation of repeat_score
def compute_poisson_estimate(seq_len, k):
  nuc_freq = .25
  try:
    return ((seq_len-int(k)+1) * nuc_freq**int(k))**2
  except ValueError:
    return np.nan

def compute_repeat_score(seq, possible_kmers, kmer_ids, k):
  l = len(seq)
  try:
    d = count_kmers(seq, kmer_ids, [int(k)])
    return sum([x * (x-1) / 2. - compute_poisson_estimate(l,k) for x in d.values()]) / (l * (l-1) / 2.)
  except ValueError:
    return np.nan

def read_genome_size(filename):
  return float(pd.read_csv(filename, sep='\t', usecols=[1]).values.sum())

def get_ce_path(cne_dir, s1, s2):
  try:
    return glob.glob(cne_dir + '/ce_*' + s1 + '*' + s2 + '*')[0]
  except IndexError:
    return None

def read_ce_file(filename):
  with open(filename, 'r') as f:
    lines = f.readlines()
  df = pd.DataFrame(np.array([l.strip().split('\t')[:4] for l in lines]), columns=['ref_chrom','ref_start','ref_end','qry'])
  df = df.astype({'ref_start': int, 'ref_end': int})
  df.insert(1, 'ref_center', ((df.ref_start + df.ref_end) / 2).astype(int))
  df['qry_chrom'] = df.qry.apply(lambda x: x.split(':')[0])
  df['qry_center'] = df.qry.apply(lambda x: np.array(x.split(':')[1].split('-')).astype(int).sum() / 2).astype(int)
  return(df.loc[:,['ref_chrom', 'ref_center', 'qry_chrom', 'qry_center']])

def read_cne(ref, qry, grb):
  filename = '/project/wig/tobias/reg_evo/data/CNEs/CNEr/cne_%s_%s_35_50.bed' %(ref,qry)
  df = pd.read_csv(filename, sep='\t', header=None, names=['chrom','start','end'], usecols=range(3))
  df['center'] = pd.Series((df.start + df.end) / 2, dtype=int)
  df = df.loc[(df.chrom == grb.chrom) & (df.center > grb.start) & (df.center < grb.end), ('chrom', 'center')]
  df['qry'] = qry
  return(df)

def longest_sorted_subsequence(l):
  res = [longest_increasingly_sorted_subsequence(l, -np.inf), [y*-1 for y in longest_increasingly_sorted_subsequence([x*-1 for x in l], -np.inf)]]
  return np.array(res[np.argmax([len(x) for x in res])])

def longest_increasingly_sorted_subsequence(l, last_taken):
  # returns the longest sorted subsequence of any given list of numbers
  l = list(l)
  if not len(l):
    # No more items in the list.
    return []

  # remove l[0]
  remove0 = longest_increasingly_sorted_subsequence(l[1:], last_taken)

  if last_taken < l[0]:
    # keep l[0]
    keep0 = longest_increasingly_sorted_subsequence(l[1:], l[0])
    keep0 = [l[0]] + keep0
    if len(keep0) > len(remove0):
      return keep0

  return remove0

# function to determine anchors of a given genomic coordinate
# pwaln: if x lies within an alignment, return the coordinate itself as both anchors
def get_anchors(df, chrom, x):
  # df contains the pwalns
  # if x lies within an alignment, return its exact position as both anchors
  anchor_cols = ['ref_chrom','ref_coord','qry_chrom','qry_coord']
  ov_aln = df.loc[(df.ref_chrom == chrom) & (df.ref_start < x) & (df.ref_end > x),].reset_index(drop=True) # x lies in an alignment. return x itself as both anchors
  ov_aln['qry_coord'] = (ov_aln.qry_start + ov_aln.qry_end) / 2 # add the center of the alignment as the `qry_coord` column in order to check for collinearity with up- and downstream anchors later

  # first define anchors upstream downstream and ov_aln, then do major_chrom / collinearity test, then do if/else ov_aln.shape[0] == 1
  # take orientation into account for the anchor definition. if the start > end, then the aln is to the '-' strand.
  # in that scenario, if we are looking for the downstream anchor, we are interested in the smaller value, i.e. the end coordinate.
  # remember that the REF coords are always on the '+' strand, so for slicing the df we don't need to check for the smaller/bigger value of start/end, it will always be start < end
  # only select the first 100. the rest just takes longer to compute min / max and most likely will (and should) not be an anchor anyways. (and they are sorted by distance to x, so this is fine)
  anchors_upstream = df.loc[abs(df.loc[(df.ref_chrom == chrom) & (df.ref_end < x),].ref_end - x).sort_values().index,['ref_chrom','ref_end','qry_chrom','qry_start','qry_end']].iloc[:100,:].reset_index(drop=True) # keeping the index makes creating a new column later very slow
  anchors_downstream = df.loc[abs(df.loc[(df.ref_chrom == chrom) & (df.ref_start > x),].ref_start - x).sort_values().index,['ref_chrom','ref_start','qry_chrom','qry_start','qry_end']].iloc[:100,:].reset_index(drop=True) # keeping the index makes creating a new column later very slow
  anchors_upstream.columns = anchors_downstream.columns = ['ref_chrom','ref_coord','qry_chrom','qry_start','qry_end']
  # abort if less than 5 pwalns to each side (too sparse, not able to ensure collinearity)
  if min(anchors_upstream.shape[0], anchors_downstream.shape[0]) < 5:
    return pd.DataFrame(columns=anchor_cols)
  # set the corresponding start or end coordinate that is closer to the projected coordinate (choosing the max/min assures correct handling of inverted alignments)
  anchors_upstream['qry_coord'] = anchors_upstream.loc[:,('qry_start','qry_end')].apply(max, axis=1)
  anchors_downstream['qry_coord'] = anchors_downstream.loc[:,('qry_start','qry_end')].apply(min, axis=1)
  # MAJOR CHROMOSOME: retain anchors that point to the majority chromosome in top ten of both up- and downstream anchors
  try:
    major_chrom = pd.concat([anchors_upstream[:10], ov_aln, anchors_downstream[:10]], axis=0, sort=False).qry_chrom.value_counts().idxmax()
  except ValueError:
    print(anchors_upstream.head(2))
    print(anchors_upstream.shape)
    print(anchors_downstream.head(2))
    print(anchors_downstream.shape)
  ov_aln[ov_aln.qry_chrom == major_chrom]
  anchors_upstream = anchors_upstream[anchors_upstream.qry_chrom == major_chrom]
  anchors_downstream = anchors_downstream[anchors_downstream.qry_chrom == major_chrom]
  
  # COLLINEARITY: remove pwalns pointing to outliers by getting the longest sorted subsequence of the top 10 of both up- and downstream anchors.
  # top 10 produced many locally collinear pwalns that were still non-collinear outliers in the global view of the GRB (is that really true?). problem: increasing n leads to exponentially growing computing time
  # e.g. collinearity check for top 9 takes < 1sec, top10 ~2-3 sec, top11 > 10sec, ...
  # check resulting spanning range in ref vs qry
  topn = 8
  closest_anchors = pd.concat([anchors_upstream[:topn][::-1], ov_aln, anchors_downstream[:topn]], axis=0, sort=False).reset_index(drop=True) # reset_index necessary, otherwise working with duplicate indices messing things up
  idx_collinear = closest_anchors.index[np.intersect1d(closest_anchors.qry_coord.values, longest_sorted_subsequence(closest_anchors.qry_coord.values.astype(int)), return_indices=True)[1]] # this step takes 2 sec
  closest_anchors = closest_anchors.loc[idx_collinear,].dropna(axis=1, how='all') # drop columns if it only contains NaNs (see explanation below)
  # if ov_aln is still present in closest_anchors (not filtered out by major_chrom / collinearity test), take it and return it. otherwise identify up- and downstream anchors.
  # this is tested by checking wether the column `ref_start` is still present (it was only present in the row from ov_aln, and NaN otherwise.)
  # If the ov_aln row was removed during the collinearity test, the final `dropna()` will get rid of the ref_start column. If there never was an ov_aln, the column will not exist either.
  if ('ref_start' in closest_anchors.columns):
    idx_ov_aln = np.where(~np.isnan(closest_anchors.ref_start))[0]
    ov_aln = closest_anchors.iloc[idx_ov_aln].reset_index(drop=True)
    x_relative_to_upstream = x - ov_aln.ref_start[0]
    strand = '+' if ov_aln.qry_start[0] < ov_aln.qry_end[0] else '-'
    if strand == '+':
      vals = [chrom, x, ov_aln.qry_chrom[0], ov_aln.qry_start[0]+x_relative_to_upstream]
    else:
      vals = [chrom, x, ov_aln.qry_chrom[0], ov_aln.qry_start[0]-x_relative_to_upstream]
    anchors = pd.DataFrame.from_dict({'upstream': vals, 'downstream': vals}, orient='index', columns=anchor_cols)
  else:
    anchor_upstream = closest_anchors.loc[abs(closest_anchors.loc[closest_anchors.ref_coord < x,].ref_coord - x).sort_values().index,].head(1).rename(index=lambda x:'upstream')
    anchor_downstream = closest_anchors.loc[abs(closest_anchors.loc[closest_anchors.ref_coord > x,].ref_coord - x).sort_values().index,].head(1).rename(index=lambda x:'downstream')
    anchors = pd.concat([anchor_upstream, anchor_downstream]).loc[:,anchor_cols]
  return anchors

def projection_score(x, anchors, genome_size):
  # anchors must be the locations of the up- and downstream anchors, not the data frame with ref and qry coordinates.
  # the scaling factor determines how fast the function falls when moving away from an anchor.
  # ideally, we define a half-life X_half, i.e. at a distance of X_half, the model is at 0.5.
  # with a scaling factor of 50 kb, X_half is at 20 kb (with 100 kb at 10 kb)
  scaling_factor = 5e4
  d = min([abs(x-y) for y in anchors])
  return np.exp(-d / (genome_size / scaling_factor))

### the function takes the input from shortest_path[ref] and returns the values to put into orange
def project_genomic_location(ref, qry, ref_coords, score, pwaln, genome_size):
  ref_chrom = ref_coords.split(':')[0]
  ref_loc = int(ref_coords.split(':')[1])
  anchors = get_anchors(pwaln[ref][qry], ref_chrom, ref_loc)
  if anchors.shape[0] < 2: # if only one anchor is found because of border region, return 0 score and empty coordinate string
    return 0., '', (), ()
  ref_anchors = tuple(anchors.apply(lambda x: x['ref_chrom'] + ':' + str(x['ref_coord']), axis=1))
  qry_anchors = tuple(anchors.apply(lambda x: x['qry_chrom'] + ':' + str(x['qry_coord']), axis=1))
  x_relative_to_upstream = (ref_loc - anchors.ref_coord['upstream']) / max(np.diff(anchors.ref_coord)[0], 1) # the max statement prevents potential zero division when anchors are the same (i.e. when the coord is on an alignment)
  qry_loc = int(anchors.qry_coord['upstream'] + np.diff(anchors.qry_coord)[0] * x_relative_to_upstream)
  qry_chrom = anchors.qry_chrom['upstream']
  # ONLY USE DISTANCE TO CLOSE ANCHOR AT REF SPECIES, because at the qry species it should be roughly the same as it is a projection of the reference.
  score *= projection_score(ref_loc, anchors.ref_coord, genome_size[ref]) # * projection_score(qry_loc, anchors.qry_coord, genome_size[qry]))
  qry_coords = qry_chrom + ':' + str(qry_loc)
  return score, qry_coords, ref_anchors, qry_anchors

def get_shortest_path_to_qry(x, shortest_path):
  l = [x]
  while x: # x='' at ref species, condition gets False, loop stops
    x = shortest_path[x][1]
    if x:
      l.append(x)
  return pd.DataFrame({k : shortest_path[k] for k in l[::-1]}, index=['score','from','coords','ref_anchors', 'qry_anchors']).T.loc[:,['from','score','coords','ref_anchors', 'qry_anchors']]

def get_shortest_path(ref, qry, ref_coords, species, pwaln, genome_size, verbose=False):
  if verbose:
    print('current species: (might be a dead end)')
  shortest_path = {}
  orange = []
  heapq_max.heappush_max(orange, (1, ref, ref_coords))
  shortest_path[ref] = (1.0, '', ref_coords, (), ())

  while len(orange) > 0:
    (current_score, current_species, current_coords) = heapq_max.heappop_max(orange)
    if shortest_path.get(current_species,(0,))[0] > current_score:
        continue # the current species was already reached by a faster path, ignore this path and go to the next species
    if verbose:
      print(current_species, current_score) # remember: this is not necessarily going to the shortest path as it might be a dead end that doesn't lead to the qry. not all printed species are part of the shortest path!
    if current_species == qry:
      break # qry species reached, stop
    for nxt_species in species[species!=current_species]:
      nxt_best_score = shortest_path.get(nxt_species,(0,))[0] # current score entry for nxt_species in shortest_path
      if current_score <= nxt_best_score:
        continue # if the score to current_species was lower than any previous path to nxt_species, nxt_species won't be reached faster through current_species. ignore and move on to the next species
      else:
        nxt_score, nxt_coords, current_anchors, nxt_anchors = project_genomic_location(current_species, nxt_species, current_coords, current_score, pwaln, genome_size)
      if nxt_score <= nxt_best_score:
        continue # only save the current path to nxt_species if it was indeed faster than any previous path to it
      else:
        shortest_path[nxt_species] = (nxt_score, current_species, nxt_coords, current_anchors, nxt_anchors)
        heapq_max.heappush_max(orange, (nxt_score, nxt_species, nxt_coords))
  shortest_path_to_qry = get_shortest_path_to_qry(qry, shortest_path)
  return shortest_path_to_qry, shortest_path, orange
