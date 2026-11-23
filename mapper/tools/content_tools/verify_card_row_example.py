import sys, openpyxl
new=openpyxl.load_workbook(sys.argv[1],data_only=True); old=openpyxl.load_workbook(sys.argv[2],data_only=True)
c=new["cards"]; o=old["cards"]
print("cards max_row",c.max_row,"(previous copy",o.max_row,")")
hit=[y for y in range(2,c.max_row+1) if c.cell(y,8).value=="Caicus River"]
print("card rows named 'Caicus River':",hit)
if hit:
    y=hit[0]
    def fmt(cell): return (type(cell.value).__name__,repr(cell.value),cell.number_format,bool(cell.font.b))
    for k in range(1,12): print("  col%-2d %s"%(k,fmt(c.cell(y,k))))
    print("  cols L-V empty:",all(c.cell(y,k).value in (None,"") for k in range(12,23)))
    print("  above:",[c.cell(y-1,k).value for k in (1,2,8)],"| below:",[c.cell(y+1,k).value for k in (1,2,3)])
    tile=[r for r in range(2,c.max_row+1) if c.cell(r,1).value=="125/025"]; fns=[int(c.cell(r,2).value) for r in tile]
    print("  125/025 FN contiguous:",fns==list(range(1,len(fns)+1)),"N =",len(fns),"rows",tile[0],"-",tile[-1])
    shift=[r for r in range(2,o.max_row+1) if [o.cell(r,k).value for k in range(1,12)]!=[c.cell(r+(1 if r>=y else 0),k).value for k in range(1,12)]]
    print("  rows differing from previous copy after allowing for the one inserted row:",shift[:8] if shift else "none")
    w=new["cities"]; x=[r for r in range(1030,w.max_row+1) if w.cell(r,4).value=="Caicus River"][0]
    print("  card == cities row %d (name, offset, lon, lat, start):"%x,(c.cell(y,8).value,c.cell(y,9).value,c.cell(y,3).value,c.cell(y,4).value,c.cell(y,6).value)==(w.cell(x,4).value,w.cell(x,5).value,w.cell(x,6).value,w.cell(x,7).value,w.cell(x,14).value),"| stop:",repr(c.cell(y,7).value),"vs",repr(w.cell(x,15).value))
    print("  Ancyra card still intact:",[c.cell(r,k).value for r in range(2,c.max_row+1) if c.cell(r,8).value=="Ancyra (battle)" for k in (1,2,6,7,8,9,10,11)])
