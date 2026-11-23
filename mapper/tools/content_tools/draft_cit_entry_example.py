import sys, difflib
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X
SRC=r"C:\My stuff\mapper\cities\125\CIT025.TXT"; DST=r"C:\My stuff\ClaudeTest\mapper\exports\CIT025_draft.TXT"
raw=open(SRC,"rb").read(); assert raw.endswith(b"\r\n\x1a")
C=X.parse_cit_full(X.read_lines(SRC)); cnt=len(C); assert [e["entryIndex"] for e in C]==list(range(1,cnt+1))
body=raw[:-1].split(b"\r\n")[:-1]; assert body[0].strip()==str(cnt).encode()
body[0]=body[0].replace(str(cnt).encode(),str(cnt+1).encode())
n=cnt+1
entry=[" %d"%n," 1","  -239.6  ,    -219.6","Caicus River","1039"," -1 ","   7 ","1","27.93\t39.21"]
out=b"\r\n".join(body+[l.encode() for l in entry])+b"\r\n\x1a"
open(DST,"wb").write(out)
B=X.parse_cit_full(X.read_lines(DST)); d=open(DST,"rb").read()
print("entries",cnt,"->",len(B),"| first %d unchanged: %s"%(cnt,C==B[:cnt]))
print("new entry:",B[-1])
print("header %r | bytes %d -> %d | CRLF %d bareLF %d | last bytes %r"%(d.split(b"\r\n")[0],len(raw),len(d),d.count(b"\r\n"),d.count(b"\n")-d.count(b"\r\n"),d[-6:]))
o=raw.split(b"\r\n"); nw=d.split(b"\r\n")
for tag,i1,i2,j1,j2 in difflib.SequenceMatcher(None,o,nw,autojunk=False).get_opcodes():
    if tag!="equal": print("DIFF",tag,"orig line",i1+1,"-",i2,"|",[x.decode('latin-1').replace("\t","<TAB>") for x in o[i1:i2]],"->",[x.decode('latin-1').replace("\t","<TAB>") for x in nw[j1:j2]])
