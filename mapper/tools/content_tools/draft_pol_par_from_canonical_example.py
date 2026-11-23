import sys, os, pickle, difflib, time
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X
M=r"C:\My stuff\mapper"; EXP=r"C:\My stuff\ClaudeTest\mapper\exports"
R=pickle.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"caicus_rings.pkl"),"rb")); Wr,Er,Ar=R["Wr"],R["Er"],R["Ar"]
assert [q for q in Wr if q[0]==30.0]==[(30.0,39.5924),(30.0,39.4838)] or sorted(q for q in Wr if q[0]==30.0)==sorted([(30.0,39.5924),(30.0,39.4838)])
assert sorted(q for q in Er if q[0]==30.0)==sorted(q for q in Wr if q[0]==30.0)
def digin(name,ring): open(EXP+"\\"+name+".txt","w",newline="").write("%d\n"%len(ring)+"".join("%.4f , %.4f\n"%q for q in ring))
digin("galatians0239_1a",Wr); digin("galatians0239_1b",Er); digin("pergamon0239_1",Ar)
def pol_draft(tile,dst,rings):
    src=M+r"\pols\125\POL%s.PRN"%tile; raw=open(src,"rb").read(); assert raw.endswith(b"\r\n\x1a")
    body=raw[:-1].split(b"\r\n")[:-1]; cnt=int(body[0]); body[0]=body[0].replace(str(cnt).encode(),str(cnt+len(rings)).encode()); new=[]
    for k,rg in enumerate(rings,start=1): new+=[b" 1             %d "%(cnt+k),b" 1 ",b" -9999.0  ,   -9998.0",b"%d"%len(rg)]+[("%.4f , %.4f"%q).encode() for q in rg]
    open(dst,"wb").write(b"\r\n".join(body+new)+b"\r\n\x1a"); return cnt
c25=pol_draft("025",EXP+r"\POL025_caicus_draft.PRN",[Wr,Ar]); c30=pol_draft("030",EXP+r"\POL030_caicus_draft.PRN",[Er])
print("POL numbers: 125/025 -> %d (Tolistoagii W), %d (Attalus) | 125/030 -> %d (Tolistoagii E)"%(c25+1,c25+2,c30+1))
def par_draft(tile,dst,entries):
    src=M+r"\polareas\125\PAR%s.ASC"%tile; raw=open(src,"rb").read(); assert raw.endswith(b"\r\n\x1a")
    E=X.parse_par_full(X.read_lines(src)); cnt=len(E); assert max(e["entryIndex"] for e in E)==cnt
    body=raw[:-1].split(b"\r\n")[:-1]; assert body[0].strip()==str(cnt).encode(); body[0]=body[0].replace(str(cnt).encode(),str(cnt+len(entries)).encode()); new=[]
    for k,(a,b,name,col,pol) in enumerate(entries,start=1): new+=[" %d "%(cnt+k),"   1"," 1 ","%.1f   ,   %.1f"%(a,b),name,"%d"%col," 1 ","   %d  ,  0"%(1000+pol)]
    open(dst,"wb").write(b"\r\n".join(body+[l.encode() for l in new])+b"\r\n\x1a"); return cnt
TOSN="Galatians - Army of the Tolistoagii"; ATTN="Pergamon - Army of Attalus"
p25=par_draft("025",EXP+r"\PAR025_caicus_draft.ASC",[(-239.7,-239.5,TOSN,4,c25+1),(-239.6,-239.4,ATTN,2,c25+2)])
p30=par_draft("030",EXP+r"\PAR030_caicus_draft.ASC",[(-239.7,-239.5,TOSN,4,c30+1)])
print("PAR numbers: 125/025 -> #%d (Tolistoagii W), #%d (Attalus) | 125/030 -> #%d (Tolistoagii E)"%(p25+1,p25+2,p30+1))
print("\n== verification")
for tile,pd,rd,pp in (("025",EXP+r"\POL025_caicus_draft.PRN",EXP+r"\PAR025_caicus_draft.ASC",M+r"\polareas\125\PAR025.ASC"),("030",EXP+r"\POL030_caicus_draft.PRN",EXP+r"\PAR030_caicus_draft.ASC",M+r"\polareas\125\PAR030.ASC")):
    ps=M+r"\pols\125\POL%s.PRN"%tile
    A=X.parse_cst_pol_full(X.read_lines(ps)); B=X.parse_cst_pol_full(X.read_lines(pd)); d=open(pd,"rb").read()
    new=[k for k in B if k not in A]
    print("tile 125/%s POL: %d -> %d | old unchanged %s | new %s | CRLF %d bareLF %d last byte %d"%(tile,len(A),len(B),all(A[k]==B[k] for k in A),[(k,B[k]["dateRanges"],len(B[k]["points"])) for k in new],d.count(b"\r\n"),d.count(b"\n")-d.count(b"\r\n"),d[-1]))
    Ea=X.parse_par_full(X.read_lines(pp)); Eb=X.parse_par_full(X.read_lines(rd)); d2=open(rd,"rb").read()
    print("tile 125/%s PAR: %d -> %d | old unchanged %s | CRLF %d bareLF %d last byte %d"%(tile,len(Ea),len(Eb),Ea==Eb[:len(Ea)],d2.count(b"\r\n"),d2.count(b"\n")-d2.count(b"\r\n"),d2[-1]))
    for e in Eb[len(Ea):]: print("   #%d refs %s %s | POL resolves %s | transient %s"%(e["entryIndex"],e["polyRefs"],[(r["from"],r["to"],r["name"],r["colorIndex"]) for r in e["dateRanges"]],all((r-1000) in B for r,f in e["polyRefs"]),all(B[r-1000]["dateRanges"]==[(-9999.0,-9998.0)] for r,f in e["polyRefs"])))
