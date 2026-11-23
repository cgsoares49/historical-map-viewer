import sys, re
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X
X.DATA_DIR=r"C:\My stuff\mapper"
from shapely.geometry import Point
BAL=(66.90,36.76); AIK=(69.40,37.16); SAM=(66.96,39.65)   # Balkh/Bactra, Ai Khanoum, Samarkand
print("Names mentioning Bactria in tiles 125/055-125/075 (any date range) and the owner of Balkh/Ai Khanoum at -241,-239.5,-237:")
for lo in ("060","065","070","075"):
    try: T=X.load_tile("125",lo)
    except Exception as e: print("tile",lo,"skip",e); continue
    pol=T["pol_by_index"]; cst=T["cst_by_index"]; rl=[0]
    for e in T["par_entries"]:
        names=[d["name"] for d in e["dateRanges"]]
        if any(re.search(r"Bactri|Diodot|Sogdi",n,re.I) for n in names):
            print("  125/%s PAR#%d type%d | %s"%(lo,e["entryIndex"],e["areaType"],[(d["from"],d["to"],d["name"],d["colorIndex"]) for d in e["dateRanges"] if d["to"]>-320 and d["from"]<-150][:8]))
    for nm,pt in (("Balkh",BAL),("Ai Khanoum",AIK),("Samarkand",SAM)):
        lon=int(pt[0]//5*5)
        if "%03d"%lon!=lo: continue
        for y in (-241,-239.5,-237):
            hit=[]
            for e in T["par_entries"]:
                if e["areaType"] not in (1,2) or e["dotPoint"] or not e["polyRefs"]: continue
                dr=X.match_date(e["dateRanges"],y)
                if not dr: continue
                try:
                    ring,_=X.build_combined_ring(e["polyRefs"],cst,pol); g=X.ring_to_polygon(ring,rl)
                except Exception: continue
                if g is not None and g.buffer(0).contains(Point(pt)): hit.append("#%d %s (col %s)"%(e["entryIndex"],dr["name"],dr["colorIndex"]))
            print("     %s at %.1f: %s"%(nm,y,hit))
