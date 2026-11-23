import re
def lines_of(p):
    return [l.strip() for l in open(p,encoding="latin-1").read().replace("\x1a","").splitlines() if l.strip()!=""]
def parse_iwa(p):
    L=lines_of(p); i=0; gc=int(L[i]); i+=1; groups=[]
    for g in range(gc):
        nr=int(L[i]); i+=1; rings=[]
        for r in range(nr):
            h=L[i].split(); i+=1
            nd=int(L[i]); i+=1
            for d in range(nd): i+=1
            i+=1
            n=int(L[i]); i+=1; pts=[]; lp=0
            while lp<n:
                raw=[t for t in re.split(r"[\s,]+",L[i]) if t]; i+=1
                rep=1; off=0
                if raw and raw[0].startswith("["):
                    m=re.match(r"\[x(\d+)\]",raw[0],re.I); rep=int(m.group(1)) if m else 1; off=1
                if len(raw)-off>=2:
                    for k in range(rep):
                        if lp<n: pts.append((float(raw[off]),float(raw[off+1]))); lp+=1
                else: lp+=1
            rings.append({"pts":pts})
        groups.append(rings)
    return groups
