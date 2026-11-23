import sys, openpyxl
def fmt(c): f=c.font; return (f.name,f.sz,c.number_format,c.alignment.horizontal)
t=openpyxl.load_workbook(sys.argv[2],data_only=True)["transients"]
print("TRANSIENTS max_row",t.max_row)
rows=[r for r in range(6112,t.max_row+1) if t.cell(r,1).value in (6116,6117,6118)]
print("rows:",rows)
for r in rows[1:]:
    print("\n sheet row",r)
    for c in range(1,13): print("   col%-2d %-9s %-76s %s"%(c,type(t.cell(r,c).value).__name__,repr(t.cell(r,c).value)[:76],fmt(t.cell(r,c))))
print("\n ref row %d fmts:"%rows[0],[fmt(t.cell(rows[0],c)) for c in (2,4,5,6)])
for n in (6117,6118): print(" # %d occurrences:"%n,[x for x in range(2,t.max_row+1) if t.cell(x,1).value==n])
w=openpyxl.load_workbook(sys.argv[1],data_only=True)["data"]
print("\nACTIONS max_row",w.max_row)
rr=[r for r in range(13058,13072) if w.cell(r,1).value in (13062,13063,13064)]
print("rows:",rr)
for r in rr[1:]:
    print("\n sheet row",r)
    for c in range(1,12): print("   col%-2d %-9s %-80s %s"%(c,type(w.cell(r,c).value).__name__,repr(w.cell(r,c).value)[:80],fmt(w.cell(r,c))))
print("\n ref row %d fmts:"%rr[0],[fmt(w.cell(rr[0],c)) for c in range(1,8)])
print("\nneighbourhood (A,C,D,F,G,H,K):")
for r in range(13062,13069): print(r,[("" if w.cell(r,c).value is None else str(w.cell(r,c).value)[:30]) for c in (1,3,4,6,7,8,11)])
for n in (13063,13064): print(" A %d occurrences:"%n,[x for x in range(2,w.max_row+1) if w.cell(x,1).value==n])
print(" descriptions identical across sheets:",{w.cell(r,5).value for r in rr[1:]}=={t.cell(r,6).value for r in rows[1:]})
