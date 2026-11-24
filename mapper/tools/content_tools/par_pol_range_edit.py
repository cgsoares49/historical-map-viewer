r"""Line-accurate range editors for canonical PAR and POL files (CRLF + trailing Ctrl-Z preserved).
Usage (import): from par_pol_range_edit import load, par_set_ranges, pol_set_ranges, save
 - PAR entry ranges are (from,to,name,colorIndex); POL block ranges are (from,to).
 - Unchanged ranges keep their ORIGINAL lines; changed/new ones use the file's usual formatting.
 - Entries are located by walking the file exactly like export_polity_polygons.parse_*: blank lines are skipped for
   parsing but preserved in the output.
Never writes to C:\My stuff\mapper itself: callers write drafts to mapper/exports/."""
import re, sys
sys.path.insert(0, r"C:\My stuff\ClaudeTest\mapper")
import export_polity_polygons as X

def load(path):
    raw = open(path, "rb").read()
    assert raw.endswith(b"\r\n\x1a"), "file must end with CRLF + Ctrl-Z"
    lines = raw.split(b"\r\n")           # last element is b'\x1a'
    ctrlz = lines.pop()
    assert ctrlz == b"\x1a"
    return lines                         # list of byte lines (no CRLF)

def save(path, lines):
    open(path, "wb").write(b"\r\n".join(lines) + b"\r\n\x1a")

def _dec(b): return b.decode("latin-1")

def _nonblank(lines):
    idx = [i for i, l in enumerate(lines) if _dec(l).strip() and _dec(l).strip() != "\x1a"]
    return idx

def locate_par(lines):
    """-> {entryIndex: dict(start, nrange_line, ranges=[(from,to,name,color,(l1,l2,l3))], ranges_end)} (raw line indices)"""
    idx = _nonblank(lines); L = [_dec(lines[i]).strip() for i in idx]
    p = 0; n = int(L[p]); p += 1; out = {}
    for _ in range(n):
        start = idx[p]; entry = int(L[p]); p += 1
        atype = int(L[p]); p += 1
        nr_line = idx[p]; nr = int(L[p]); p += 1
        ranges = []
        for _ in range(nr):
            frm, to = X.parse_date_range(L[p]); l1 = idx[p]; p += 1
            name = L[p]; l2 = idx[p]; p += 1
            col = int(L[p]); l3 = idx[p]; p += 1
            ranges.append((frm, to, name, col, (l1, l2, l3)))
        nrefs = float(L[p]); p += 1
        if nrefs < 0: p += 1
        else: p += int(nrefs)
        assert entry not in out, "duplicate entry label %d" % entry
        out[entry] = dict(start=start, nr_line=nr_line, ranges=ranges, atype=atype, end=idx[p-1])
    return out

def _fmt_range(a, b):  # matches the common "-550.5   ,   -240.5" style
    return ("%.1f   ,   %.1f" % (a, b)).encode()

def par_set_ranges(lines, entry, new_ranges):
    """Replace the date-range block of PAR entry label `entry`. new_ranges = [(from,to,name,color),...]"""
    loc = locate_par(lines)[entry]; old = loc["ranges"]
    keep = {(r[0], r[1], r[2], r[3]): r[4] for r in old}
    new_block = []
    for (a, b, name, col) in new_ranges:
        key = (float(a), float(b), name, int(col))
        if key in keep:
            l1, l2, l3 = keep[key]; new_block += [lines[l1], lines[l2], lines[l3]]
        else:
            new_block += [_fmt_range(a, b), name.encode("latin-1"), (" %d " % col).encode() if col >= 10 else (b"%d" % col)]
    first = old[0][4][0]; last = old[-1][4][2]
    assert lines[loc["nr_line"]] is not None
    out = lines[:loc["nr_line"]] + [(" %d " % len(new_ranges)).encode()] + new_block + lines[last + 1:]
    return out

def locate_pol(lines):
    idx = _nonblank(lines); L = [_dec(lines[i]).strip() for i in idx]
    p = 0; n = int(L[p]); p += 1; out = {}
    for _ in range(n):
        header = L[p].split(); hl = idx[p]; p += 1
        pidx = int(header[1]) if len(header) > 1 else 1
        nd_line = idx[p]; nd = int(L[p]); p += 1
        rl = []
        for _ in range(nd):
            frm, to = X.parse_date_range(L[p]); rl.append((frm, to, idx[p])); p += 1
        pc = int(L[p]); p += 1
        lp = 0
        while lp < pc and p < len(L):
            raw = [t for t in re.split(r"[\s,]+", L[p]) if t]; p += 1
            off, rep = 0, 1
            if raw and raw[0].startswith("["):
                m = re.match(r"\[x(\d+)\]", raw[0], re.I)
                if m: rep = int(m.group(1))
                off = 1
            lp += rep if len(raw) - off >= 2 else 1
        out[pidx] = dict(header=hl, nd_line=nd_line, ranges=rl)
    return out

def _fmt_pol_range(a, b):  # '  -550.5  ,    -1.0' style: first value width 8, then '  ,' and second value width 8
    return ("%8s  ,%8s" % ("%.1f" % a, "%.1f" % b)).encode()

def pol_set_ranges(lines, pol, new_ranges):
    """Replace the date ranges of POL block `pol` (includes the leading (-9998,-9997) marker range). new_ranges = [(from,to),...]"""
    loc = locate_pol(lines)[pol]; old = loc["ranges"]
    keep = {(r[0], r[1]): lines[r[2]] for r in old}
    block = [keep.get((float(a), float(b)), _fmt_pol_range(a, b)) for (a, b) in new_ranges]
    first = old[0][2]; last = old[-1][2]
    return lines[:loc["nd_line"]] + [(" %d " % len(new_ranges)).encode()] + block + lines[last + 1:]


def par_insert_after(lines, after_entry, label, ranges, refs, atype=1):
    """Insert a NEW PAR entry physically right after entry `after_entry` (draw order: polity entries go under their parent),
    label it `label` (next free number), and bump the header count. ranges=[(from,to,name,color)], refs=[(1000+POL,flag)]."""
    loc = locate_par(lines)
    assert label not in loc, "label already used"
    block = [(" %d " % label).encode(), (b"   %d" % atype)]
    block += [(" %d " % len(ranges)).encode()]
    for (a, b, name, col) in ranges:
        block += [_fmt_range(a, b), name.encode("latin-1"), (b"%d" % col)]
    block += [(" %d " % len(refs)).encode()] + [(b"   %d  ,  %d" % (r, f)) for (r, f) in refs]
    at = loc[after_entry]["end"] + 1
    out = lines[:at] + block + lines[at:]
    first = _nonblank(out)[0]
    cnt = int(_dec(out[first]).strip())
    out[first] = out[first].replace(str(cnt).encode(), str(cnt + 1).encode(), 1)
    return out
