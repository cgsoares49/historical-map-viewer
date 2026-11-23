import sys, os, openpyxl
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X
M=r"C:\My stuff\mapper"; S=os.path.dirname(os.path.abspath(__file__))
print("== PAR files (expected: #342 -239.5..-239.3 | #343 and #803 -239.4..-239.2)")
for tile,ids in (("025",(803,)),("030",(342,343))):
    raw=open(M+r"\polareas\125\PAR%s.ASC"%tile,"rb").read()
    E=X.parse_par_full(X.read_lines(M+r"\polareas\125\PAR%s.ASC"%tile)); byi={e["entryIndex"]:e for e in E}
    print(" tile 125/%s: header %r, %d entries, CRLF %d bareLF %d, last byte %d"%(tile,raw.split(b"\r\n")[0],len(E),raw.count(b"\r\n"),raw.count(b"\n")-raw.count(b"\r\n"),raw[-1]))
    for n in ids:
        e=byi[n]; print("   #%d refs %s %s"%(n,e["polyRefs"],[(r["from"],r["to"],r["name"],r["colorIndex"]) for r in e["dateRanges"]]))
print("\n== CIT030 (expected entry 41: -239.4..-219.4)")
raw=open(M+r"\cities\125\CIT030.TXT","rb").read(); C=X.parse_cit_full(X.read_lines(M+r"\cities\125\CIT030.TXT"))
print(" header %r | entries %d | CRLF %d bareLF %d | last bytes %r"%(raw.split(b"\r\n")[0],len(C),raw.count(b"\r\n"),raw.count(b"\n")-raw.count(b"\r\n"),raw[-6:]))
print("  entry 41:",C[-1])
wb=openpyxl.load_workbook(S+r"\ct.xlsx",data_only=True)
w=wb["cities"]; r=[x for x in range(1030,w.max_row+1) if w.cell(x,4).value=="Ancyra (battle)"][0]
print("\n== cities row %d:"%r,[w.cell(r,c).value for c in (1,4,5,6,7,11,12,14,15,16)])
c=wb["cards"]; y=[x for x in range(600,c.max_row+1) if c.cell(x,8).value=="Ancyra (battle)"][0]
print("== card row %d:"%y,[c.cell(y,k).value for k in range(1,12)])
print("\n== ancient index > transients (expected #6115: -239.5..-239.3 ; #6116: -239.4..-239.2)")
t=openpyxl.load_workbook(S+r"\ai.xlsx",data_only=True)["transients"]
for x in range(6112,t.max_row+1):
    if t.cell(x,1).value in (6115,6116): print("  row",x,[t.cell(x,k).value for k in (1,2,3,4,5,6,7,8,9,10,11,12)])
print("\n== animation actions (expected A=13061: -239.5..-239.3 ; A=13062: -239.4..-239.2)")
a=openpyxl.load_workbook(S+r"\aa4.xlsx",data_only=True)["data"]
for x in range(13055,13075):
    if a.cell(x,1).value in (13061,13062): print("  sheet row",x,[a.cell(x,k).value for k in (1,2,3,4,5,6,7,8)])
