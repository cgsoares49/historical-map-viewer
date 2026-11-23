import sys, math, heapq, os, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
from iwa_lib import parse_iwa
import export_polity_polygons as X
X.DATA_DIR=r"C:\My stuff\mapper"
import shapely, numpy as np
from shapely.geometry import Polygon, LineString, Point, box
from shapely.ops import unary_union
LAT0=39.2; KX=111.32*math.cos(math.radians(LAT0)); KY=110.57
fw=lambda p:((p[0]-26.0)*KX,(p[1]-37.5)*KY); bw=lambda p:(p[0]/KX+26.0,p[1]/KY+37.5)
def km(a,b): return math.dist(a,b)
BB=(26.0,38.0,32.6,40.4)
lakes=[]
for f in ("IWA025.PRN","IWA030.PRN"):
    for rings in parse_iwa(r"C:\My stuff\mapper\inwaters\125\%s"%f):
        if len(rings[0]["pts"])<3: continue
        p=Polygon(rings[0]["pts"]).buffer(0); b=p.bounds
        if b[2]>BB[0] and b[0]<BB[2] and b[3]>BB[1] and b[1]<BB[3]: lakes.append(Polygon([fw(q) for q in p.exterior.coords]).buffer(0))
LAK=unary_union(lakes); OBS=LAK.buffer(3.2); shapely.prepare(OBS)
CELL=1.5; x0,y0=fw((BB[0],BB[1])); x1,y1=fw((BB[2],BB[3])); nx=int((x1-x0)/CELL)+1; ny=int((y1-y0)/CELL)+1
XX,YY=np.meshgrid(x0+np.arange(nx)*CELL,y0+np.arange(ny)*CELL)
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
def chain(w):
    out=[]
    for a,b in zip(w,w[1:]):
        s=astar(a,b); out+= s if not out else s[1:]
    return out
def densify(w,step=0.5):
    pts=[w[0]]
    for a,b in zip(w,w[1:]):
        d=km(a,b); n=max(1,int(d/step))
        for k in range(1,n+1): pts.append((a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n))
    return pts
PESS=(31.5836,39.3329); PERG=(27.1844,39.1328); PC=(27.93,39.21); PAIR_N,PAIR_S=39.5924,39.4838; CROSS=(30.0,(PAIR_N+PAIR_S)/2)
def build(w,amp,wl,ph,r0,wob,head,pin=None,rpin=None,seed=0):
    pts=densify(chain(w)); n=len(pts); cum=[0]
    for a,b in zip(pts,pts[1:]): cum.append(cum[-1]+km(a,b))
    L=cum[-1]; kx=min(range(n),key=lambda i:km(pts[i],fw(pin))) if pin else None
    out=[]
    for i,p in enumerate(pts):
        a=pts[max(i-1,0)]; b=pts[min(i+1,n-1)]; dx,dy=b[0]-a[0],b[1]-a[1]; d=math.hypot(dx,dy) or 1
        env=math.sin(math.pi*cum[i]/L)**0.5
        if pin: env*=1-math.exp(-((cum[i]-cum[kx])/9.0)**2)
        off=amp*env*(math.sin(2*math.pi*cum[i]/wl+ph)+0.5*math.sin(2*math.pi*cum[i]/(wl*0.37)+ph*2.1))/1.5
        q=(p[0]-dy/d*off,p[1]+dx/d*off)
        out.append(q if Point(q).distance(LAK)>=3.2*0.8+0.4 else p)
    for _ in range(4): out=[out[0]]+[((out[i-1][0]+2*out[i][0]+out[i+1][0])/4,(out[i-1][1]+2*out[i][1]+out[i+1][1])/4) for i in range(1,n-1)]+[out[-1]]
    out[-1]=fw(PC)
    cum=[0]
    for a,b in zip(out,out[1:]): cum.append(cum[-1]+km(a,b))
    L=cum[-1]; r=[]
    for i,q in enumerate(out):
        s=cum[i]/L; base=r0+wob*math.sin(2*math.pi*(4*s)+ph)+0.5*wob*math.sin(2*math.pi*(11*s)+1.7)
        r.append(max(1.3,min(base,Point(q).distance(LAK)-0.9)))
    for _ in range(8): r=[r[0]]+[(r[i-1]+2*r[i]+r[i+1])/4 for i in range(1,n-1)]+[r[-1]]
    if pin:
        for i in range(n):
            wt=math.exp(-((cum[i]-cum[kx])/9.0)**2); r[i]=r[i]*(1-wt)+rpin*wt
    for i in range(n): r[i]=max(1.3,min(r[i],Point(out[i]).distance(LAK)-0.9))
    for i in range(n):
        de=L-cum[i]
        if de<6: f=1-de/6; r[i]=r[i]*(1-f)+head*f
    r[-1]=head
    g=unary_union([Point(q).buffer(rr,resolution=10) for q,rr in zip(out,r)]); assert g.geom_type=="Polygon",g.geom_type
    return g,L
TOS,Lt=build([PESS,CROSS,PC],3.0,70,1.1,5.0,0.5,5.0,pin=CROSS,rpin=6.0)
ATT,La=build([PERG,PC],1.5,40,2.3,5.4,0.5,7.0)
print("Tolistoagii: centreline %.0f km (%.0f mi, %.1f days at 10 mi/day), area %.0f km2, valid %s"%(Lt,Lt/1.609,Lt/16.09,TOS.area,TOS.is_valid))
print("Attalus:     centreline %.0f km (%.0f mi, %.1f days), area %.0f km2, valid %s"%(La,La/1.609,La/16.09,ATT.area,ATT.is_valid))
xb=fw((30.0,37.5))[0]
Wp=TOS.intersection(box(-1e5,-1e5,xb,1e5)); Ep=TOS.intersection(box(xb,-1e5,1e5,1e5)); assert Wp.geom_type=="Polygon" and Ep.geom_type=="Polygon"
def arc_ring(g,tol,chord=True):
    coords=list(g.exterior.coords)[:-1]; n=len(coords)
    if not chord: return [bw(q) for q in list(g.simplify(tol).exterior.coords)[:-1]]
    on=[i for i,q in enumerate(coords) if abs(q[0]-xb)<1e-6]; k=next(k for k in range(n) if k in on and (k+1)%n in on)
    arc=coords[(k+1)%n:]+coords[:k+1] if (k+1)%n!=0 else coords[:]
    return [bw(q) for q in LineString(arc).simplify(tol).coords]
def snap(ring):
    i0,i1=0,len(ring)-1                       # an arc ring starts and ends on the cut line
    assert abs(fw(ring[i0])[0]-xb)<0.05 and abs(fw(ring[i1])[0]-xb)<0.05,"arc ends are not on the tile line"
    lo,hi=sorted((i0,i1),key=lambda i:ring[i][1]); cb=(ring[lo][1],ring[hi][1]); ring[lo]=(30.0,PAIR_S); ring[hi]=(30.0,PAIR_N); return cb
def rot(ring,pt):
    k=min(range(len(ring)),key=lambda i:km(fw(ring[i]),fw(pt))); return ring[k:]+ring[:k]
tol=0.4
Wr=arc_ring(Wp,tol); Er=arc_ring(Ep,tol); Ar=arc_ring(ATT,tol,chord=False)
print("chord before snapping: W %.4f-%.4f | E %.4f-%.4f -> pair %.4f-%.4f"%(*snap(Wr),*snap(Er),PAIR_S,PAIR_N))
Wr=rot(Wr,PC); Er=rot(Er,PESS); Ar=rot(Ar,PERG)
rnd=lambda ring:[(round(x,4),round(y,4)) for x,y in ring]
Wr,Er,Ar=rnd(Wr),rnd(Er),rnd(Ar)
G={nm:Polygon([fw(q) for q in rg]) for nm,rg in (("Tosti W",Wr),("Tosti E",Er),("Attalus",Ar))}
for nm,g in G.items(): print("%-8s pts %3d | valid %s | area %5.0f km2 | lake overlap %.3f | min dist to lakes %.2f km"%(nm,len(g.exterior.coords)-1,g.is_valid,g.area,g.intersection(LAK).area,g.distance(LAK)))
TT=unary_union([G["Tosti W"],G["Tosti E"]])
print("Tosti W+E vs unsplit area diff %.1f km2 (%.2f%%)"%(abs(TT.area-TOS.area),100*abs(TT.area-TOS.area)/TOS.area))
print("Attalus head covers Tosti head disc (r 5.0 km):",G["Attalus"].buffer(0).contains(Point(fw(PC)).buffer(2.3)),"| both contain P:",G["Attalus"].contains(Point(fw(PC))),G["Tosti W"].contains(Point(fw(PC))))
print("chord vertices W:",[q for q in Wr if q[0]==30.0],"| E:",[q for q in Er if q[0]==30.0])
pickle.dump({"Wr":Wr,"Er":Er,"Ar":Ar},open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"caicus_rings_wide.pkl"),"wb"))
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig,ax=plt.subplots(figsize=(14,6))
for p in lakes: xx,yy=zip(*[bw(q) for q in p.exterior.coords]); ax.fill(xx,yy,color="#9ecae1",alpha=.7)
for ring,c,l in ((Wr,"#ff7f0e","Tolistoagii W (125/025)"),(Er,"#9467bd","Tolistoagii E (125/030)"),(Ar,"#2ca02c","Attalus (125/025)")):
    xx=[q[0] for q in ring]+[ring[0][0]]; yy=[q[1] for q in ring]+[ring[0][1]]; ax.fill(xx,yy,color=c,alpha=.35); ax.plot(xx,yy,color=c,lw=1,label=l)
ax.axvline(30.0,color="k",ls="--",lw=.8)
for nm,p in (("Pessinus",PESS),("Pergamum",PERG),("Caicus source",PC)): ax.plot(*p,"ko",ms=4); ax.annotate(nm,p,xytext=(3,3),textcoords="offset points",fontsize=8)
ax.set_xlim(26.6,32.2); ax.set_ylim(38.7,40.0); ax.set_aspect(1/math.cos(math.radians(39.3))); ax.grid(alpha=.25); ax.legend(loc="lower right"); plt.tight_layout()
plt.savefig(r"C:\My stuff\ClaudeTest\mapper\exports\caicus_armies_wide_preview.png",dpi=95)





