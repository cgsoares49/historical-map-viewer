import sys, math, heapq, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
from iwa_lib import parse_iwa
import export_polity_polygons as X
X.DATA_DIR=r"C:\My stuff\mapper"
import shapely, numpy as np
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union, transform
LAT0=39.0; KX=111.32*math.cos(math.radians(LAT0)); KY=110.57
fw=lambda p:((p[0]-26.0)*KX,(p[1]-37.5)*KY); bw=lambda p:(p[0]/KX+26.0,p[1]/KY+37.5)
BB=(26.2,37.9,33.2,40.4)
lakes=[]
for f in ("IWA025.PRN","IWA030.PRN"):
    for rings in parse_iwa(r"C:\My stuff\mapper\inwaters\125\%s"%f):
        if len(rings[0]["pts"])<3: continue
        p=Polygon(rings[0]["pts"]).buffer(0); b=p.bounds
        if b[2]>BB[0] and b[0]<BB[2] and b[3]>BB[1] and b[1]<BB[3]: lakes.append(Polygon([fw(q) for q in p.exterior.coords]).buffer(0))
LAK=unary_union(lakes); OBS=LAK.buffer(3.0); shapely.prepare(OBS)
# sea mask from tile coast? keep simple: block a coarse box over the Marmara/Aegean via CST polygons is skipped; check result visually
CELL=1.5; x0,y0=fw((BB[0],BB[1])); x1,y1=fw((BB[2],BB[3])); nx=int((x1-x0)/CELL)+1; ny=int((y1-y0)/CELL)+1
xs=x0+np.arange(nx)*CELL; ys=y0+np.arange(ny)*CELL; XX,YY=np.meshgrid(xs,ys)
blk=shapely.contains_xy(OBS,XX.ravel(),YY.ravel()).reshape(ny,nx)
cell=lambda p:(int(round((fw(p)[0]-x0)/CELL)),int(round((fw(p)[1]-y0)/CELL)))
def astar(a,b):
    s=cell(a); g=cell(b); blk[s[1],s[0]]=False; blk[g[1],g[0]]=False
    q=[(0,s)]; came={}; cost={s:0}; nb=[(1,0,1),(-1,0,1),(0,1,1),(0,-1,1),(1,1,1.4142),(1,-1,1.4142),(-1,1,1.4142),(-1,-1,1.4142)]
    while q:
        _,u=heapq.heappop(q)
        if u==g: break
        for dx,dy,w in nb:
            v=(u[0]+dx,u[1]+dy)
            if not(0<=v[0]<nx and 0<=v[1]<ny) or blk[v[1],v[0]]: continue
            c=cost[u]+w
            if c<cost.get(v,1e18): cost[v]=c; came[v]=u; heapq.heappush(q,(c+math.hypot(v[0]-g[0],v[1]-g[1]),v))
    path=[g]
    while path[-1]!=s: path.append(came[path[-1]])
    pts=[(x0+c[0]*CELL,y0+c[1]*CELL) for c in path[::-1]]; pts[0]=fw(a); pts[-1]=fw(b)
    out=[pts[0]]; i=0
    while i<len(pts)-1:
        j=len(pts)-1
        while j>i+1 and LineString([pts[i],pts[j]]).intersects(OBS.buffer(-0.01)): j-=1
        out.append(pts[j]); i=j
    return out
PESS=(31.5836,39.3329); GORD=(31.9883,39.652); PERG=(27.1844,39.1328); SRC=(27.93,39.21)
print("source of the Caicus (27.93, 39.21) lake clearance km: %.1f"%Point(fw(SRC)).distance(LAK))
for nm,a,b in (("Tolistoagii: Pessinus -> Caicus source",PESS,SRC),("Tolistoagii: Gordion -> Caicus source",GORD,SRC),("Attalus: Pergamum -> Caicus source",PERG,SRC)):
    w=astar(a,b); L=sum(math.dist(p,q) for p,q in zip(w,w[1:]))
    print("%-42s %4.0f km (%3.0f mi) -> %4.1f days at 10 mi/day = %.3f yr | straight %.0f km"%(nm,L,L/1.609,L/16.09,L/16.09/365.25,math.dist(fw(a),fw(b))))
    if nm.startswith("Tolistoagii: Pessinus"):
        cr=[(bw(p),bw(q)) for p,q in zip(w,w[1:]) if (bw(p)[0]-30.0)*(bw(q)[0]-30.0)<0]
        for p,q in cr: 
            t=(30.0-p[0])/(q[0]-p[0]); print("   crosses 30.0E at lat %.3f"%(p[1]+t*(q[1]-p[1])))
# existing transient tile-crossing pairs at lon 30.0 between lat 38.9 and 39.8
print("\nexisting transient pairs on lon 30.0 (tile 125/025 POLs; both vertices at exactly 30.0), lat 38.9-39.8:")
T=X.load_tile("125","025"); pol=T["pol_by_index"]; uses={}
for e in T["par_entries"]:
    for r,f in e["polyRefs"]:
        if r>1000: uses.setdefault(r-1000,[]).append(e)
for n,p in pol.items():
    if p["dateRanges"]!=[(-9999.0,-9998.0)]: continue
    ed=[q for q in p["points"] if abs(q[0]-30.0)<0.0005]
    if len(ed)>=2 and all(38.9<=q[1]<=39.8 for q in ed):
        nm=uses.get(n,[None])[0]; nm=(nm["dateRanges"][0]["name"],nm["dateRanges"][0]["from"]) if nm else None
        print("   POL %d pair lat %.4f / %.4f (width %.1f km)  %s"%(n,ed[0][1],ed[1][1],abs(ed[0][1]-ed[1][1])*110.57,nm))
