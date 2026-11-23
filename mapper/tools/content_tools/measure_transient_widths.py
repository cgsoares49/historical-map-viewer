import sys, math, statistics as st
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X
X.DATA_DIR=r"C:\My stuff\mapper"
from shapely.geometry import Polygon
KX=111.32*math.cos(math.radians(39.0)); KY=110.57
fw=lambda p:(p[0]*KX,p[1]*KY)
rows=[]
for tile in ("025","030"):
    T=X.load_tile("125",tile); pol=T["pol_by_index"]; uses={}
    for e in T["par_entries"]:
        for r,f in e["polyRefs"]:
            if r>1000: uses.setdefault(r-1000,[]).append(e)
    for n,p in pol.items():
        if p["dateRanges"]!=[(-9999.0,-9998.0)] or len(p["points"])<8 or n not in uses: continue
        names=[d for e in uses[n] for d in e["dateRanges"][:1]]
        nm=names[0]["name"] if names else ""
        if "Army" not in nm and "army" not in nm: continue
        P=Polygon([fw(q) for q in p["points"]]).buffer(0)
        if P.is_empty or P.length==0: continue
        L=P.length/2; w=2*P.area/P.length*1.0     # mean width ~ 2A/P for a long thin shape
        # chord widths at tile line
        ed=[q for q in p["points"] if abs(q[0]-30.0)<0.0005]
        chord=abs(ed[0][1]-ed[1][1])*110.57 if len(ed)>=2 else None
        y=names[0]["from"]
        rows.append((tile,n,nm[:38],y,L,w,chord,P.area))
print("army-type transient POLs measured: %d (tiles 125/025 + 125/030)"%len(rows))
def stats(sel,label):
    if not sel: return
    ws=[r[5] for r in sel]; print("%-46s n=%3d  width km: median %.1f | quartiles %.1f-%.1f | min %.1f max %.1f"%(label,len(sel),st.median(ws),sorted(ws)[len(ws)//4],sorted(ws)[3*len(ws)//4],min(ws),max(ws)))
stats(rows,"all")
stats([r for r in rows if r[4]>=150],"long ones (>=150 km half-perimeter)")
stats([r for r in rows if 60<=r[4]<150],"medium (60-150 km)")
stats([r for r in rows if -330<=r[3]<=-230],"Hellenistic era (-330..-230)")
stats([r for r in rows if r[3]>=-330 and r[3]<=-270 and ("Celt" in r[2] or "Gala" in r[2])],"Celtic/Galatian armies -330..-270")
print("\ntile-line chord widths (30.0E) of army transients, for comparison:")
ch=[r for r in rows if r[6]]
for r in sorted(ch,key=lambda r:r[3])[-14:]: print("   tile 125/%s POL %-4d %-38s %7.1f  chord %.1f km | mean width %.1f km | length ~%.0f km"%(r[0],r[1],r[2],r[3],r[6],r[5],r[4]))
print("median chord width: %.1f km (n=%d)"%(st.median([r[6] for r in ch]),len(ch)))
print("\nrecent (>= -300) long transients, width vs length:")
for r in sorted([r for r in rows if r[3]>=-300 and r[4]>=100],key=lambda r:r[3])[-12:]: print("   tile 125/%s POL %-4d %-38s %7.1f  width %.1f km  length ~%.0f km"%(r[0],r[1],r[2],r[3],r[5],r[4]))
print("\nmy Ancyra snakes for comparison: Seleucus ~4.6 km, Hierax ~5.8 km; Caicus first draft: Tolistoagii ~4.6 km (12 km at the pair), Attalus ~5.6 km")
