import sys, os, pickle, math, difflib
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X
from shapely.geometry import Polygon
M=r"C:\My stuff\mapper"; EXP=r"C:\My stuff\ClaudeTest\mapper\exports"
R=pickle.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"caicus_rings_wide.pkl"),"rb")); Wr,Er,Ar=R["Wr"],R["Er"],R["Ar"]
def digin(name,ring): open(EXP+"\\"+name+".txt","w",newline="").write("%d\n"%len(ring)+"".join("%.4f , %.4f\n"%q for q in ring))
digin("galatians0239_1a",Wr); digin("galatians0239_1b",Er); digin("pergamon0239_1",Ar)
def replace_blocks(tile,dst,newblocks):
    src=M+r"\pols\125\POL%s.PRN"%tile; raw=open(src,"rb").read(); assert raw.endswith(b"\r\n\x1a")
    body=raw[:-1].split(b"\r\n")[:-1]; first=min(newblocks)
    i0=[i for i,l in enumerate(body) if l.strip().split()==[b"1",str(first).encode()]]; assert len(i0)==1
    cnt=int(body[0]); assert max(newblocks)==cnt and sorted(newblocks)==list(range(first,cnt+1)),"blocks must be the LAST ones in the file"
    new=[]
    for n in sorted(newblocks): rg=newblocks[n]; new+=[b" 1             %d "%n,b" 1 ",b" -9999.0  ,   -9998.0",b"%d"%len(rg)]+[("%.4f , %.4f"%q).encode() for q in rg]
    open(dst,"wb").write(b"\r\n".join(body[:i0[0]]+new)+b"\r\n\x1a")
replace_blocks("025",EXP+r"\POL025_caicus_draft2.PRN",{674:Wr,675:Ar}); replace_blocks("030",EXP+r"\POL030_caicus_draft2.PRN",{382:Er})
KX=111.32*math.cos(math.radians(39.0)); KY=110.57; fw=lambda p:(p[0]*KX,p[1]*KY)
print("== verification (drafts vs the canonical files you saved at 8:33)")
for tile,dst,news in (("025",EXP+r"\POL025_caicus_draft2.PRN",(674,675)),("030",EXP+r"\POL030_caicus_draft2.PRN",(382,))):
    A=X.parse_cst_pol_full(X.read_lines(M+r"\pols\125\POL%s.PRN"%tile)); B=X.parse_cst_pol_full(X.read_lines(dst)); d=open(dst,"rb").read()
    print("tile 125/%s: POLs %d -> %d | all other POLs identical %s | CRLF %d bareLF %d last byte %d"%(tile,len(A),len(B),all(A[k]==B[k] for k in A if k not in news),d.count(b"\r\n"),d.count(b"\n")-d.count(b"\r\n"),d[-1]))
    for k in news:
        P=Polygon([fw(q) for q in B[k]["points"]]).buffer(0)
        print("   POL %d: ranges %s | %d pts (was %d) | valid %s | area %.0f km2 | mean width ~%.1f km (was ~%.1f)"%(k,B[k]["dateRanges"],len(B[k]["points"]),len(A[k]["points"]),P.is_valid,P.area,2*P.area/P.length,2*Polygon([fw(q) for q in A[k]["points"]]).buffer(0).area/Polygon([fw(q) for q in A[k]["points"]]).buffer(0).length))
p25=X.parse_cst_pol_full(X.read_lines(EXP+r"\POL025_caicus_draft2.PRN")); p30=X.parse_cst_pol_full(X.read_lines(EXP+r"\POL030_caicus_draft2.PRN"))
w=sorted(q for q in p25[674]["points"] if q[0]==30.0); e=sorted(q for q in p30[382]["points"] if q[0]==30.0)
print("crossing vertices: POL 674 %s | POL 382 %s | equal %s | = POL 529 pair: %s"%(w,e,w==e,w==sorted([(30.0,39.4838),(30.0,39.5924)])))
print("PAR files need no change (same POL numbers 674/675/382, same refs 1674/1675/1382).")
