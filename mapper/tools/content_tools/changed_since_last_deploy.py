import sys, os, hashlib, time, collections
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X
CAN=r"C:\My stuff\mapper"; DIST=r"C:\My stuff\ClaudeTest\dist\mapper"
print("dist data copy exists:",os.path.isdir(DIST))
kinds={"polareas":"PAR","pols":"POL","coasts":"CST","cities":"CIT","niw":"NIW","inwaters":"IWA"}
changed=collections.defaultdict(list)
for d,k in kinds.items():
    for root,_,files in os.walk(os.path.join(CAN,d)):
        for f in files:
            a=os.path.join(root,f); rel=os.path.relpath(a,CAN); b=os.path.join(DIST,rel)
            if not os.path.exists(b): changed[k].append((rel,"NEW")); continue
            if hashlib.md5(open(a,"rb").read()).digest()!=hashlib.md5(open(b,"rb").read()).digest(): changed[k].append((rel,"changed"))
print("Files differing from last deploy:",{k:len(v) for k,v in changed.items()})
for k,v in changed.items():
    for rel,st in v: print("  %-5s %s (%s)"%(k,rel,st))
# which POLITY (non-transient) entries differ in the changed PAR files
tot=0
for rel,_ in changed.get("PAR",[]):
    lo=os.path.basename(rel)[3:6]; lat=os.path.basename(os.path.dirname(rel))
    A=X.parse_par_full(X.read_lines(os.path.join(DIST,rel))); B=X.parse_par_full(X.read_lines(os.path.join(CAN,rel)))
    byA={e["entryIndex"]:e for e in A}
    pol=X.parse_cst_pol_full(X.read_lines(os.path.join(CAN,"pols",lat,"POL%s.PRN"%lo)))
    trans=lambda e: bool(e["polyRefs"]) and all(r>1000 and pol.get(r-1000,{}).get("dateRanges")==[(-9999.0,-9998.0)] for r,f in e["polyRefs"])
    d_pol=[];d_tr=[]
    for e in B:
        o=byA.get(e["entryIndex"])
        if o is None or o!=e:
            (d_tr if trans(e) else d_pol).append((e["entryIndex"],"new" if o is None else "edited",X.owner_name(e["dateRanges"][-1]["name"]) if e["dateRanges"] else "?"))
    print("\n%s: %d polity entries new/edited, %d transient entries new/edited"%(rel,len(d_pol),len(d_tr)))
    for x in d_pol[:12]: print("     polity #%d %s -> %s"%x)
