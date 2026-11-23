import sys, re, openpyxl
wb=openpyxl.load_workbook(sys.argv[1],read_only=True,data_only=True); ws=wb['data']
rows=list(ws.iter_rows(values_only=True))
print("total rows",len(rows))
def yr(k):
    m=re.match(r"\s*\(\s*(-?\d+(?:\.\d+)?)",k or ""); return float(m.group(1)) if m else None
nums=[(i,r[0]) for i,r in enumerate(rows,start=1) if isinstance(r[0],(int,float))]
print("last numbered A row: sheet row",nums[-1][0],"A =",nums[-1][1])
print("\nK cells in the -240..-238 zone and any mentioning Hierax/Bactria/Galatian/Agron/Attalus/Demetrian (current sheet rows):")
for i,r in enumerate(rows,start=1):
    k=r[10] if len(r)>10 else None
    if isinstance(k,str) and 13040<i<13200:
        y=yr(k)
        if (y is not None and -240.5<=y<=-237.5 and re.search(r"Hierax|Bactria|Diod|Galatian|Agron|Ardiaea|Attalus|Demetrian|Pergamum",k)) or re.search(r"Hierax",k):
            print("\nK row",i,"| A-J filled:",any(c not in (None,"") for c in r[:10]),"\n   ",k[:560])
