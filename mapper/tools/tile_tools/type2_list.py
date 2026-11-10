import sys, math
sys.path.insert(0, r'C:\My stuff\ClaudeTest\mapper')
import export_polity_polygons as X
T = X.load_tile('120','110'); pol=T['pol_by_index']; cst=T['cst_by_index']
rl=[0]
ents=T['par_entries']
polys={}
for e in ents:
    if e['areaType']==1 and not e['dotPoint'] and e['polyRefs'] and not X.is_transient(e['polyRefs'],pol):
        ring,_=X.build_combined_ring(e['polyRefs'],cst,pol)
        p=X.ring_to_polygon(ring,rl) if ring else None
        if p is not None and not p.is_empty: polys[e['entryIndex']]=(e,p)
for e in ents:
    if e['areaType']!=2: continue
    ring,_=X.build_combined_ring(e['polyRefs'],cst,pol) if e['polyRefs'] else (None,0)
    p=X.ring_to_polygon(ring,rl) if ring else None
    ranges=[(d['from'],d['to'],d['name']) for d in e['dateRanges']]
    if p is None or p.is_empty:
        print('#%d dot/none %s'%(e['entryIndex'],ranges[:2]), e['dotPoint']); continue
    ar=X.area_km2(p); comp=4*math.pi*p.area/(p.length**2) if p.length else 0
    host=[]
    for i,(e2,q) in polys.items():
        if q.contains(p.representative_point()): 
            dr=[(d['from'],d['to']) for d in e2['dateRanges']]
            host.append((i,e2['dateRanges'][0]['name'][:12]))
    print('#%d %.0f km2 compact %.2f  %s  inside:%s'%(e['entryIndex'],ar,comp,ranges[:3],host[:4]))
