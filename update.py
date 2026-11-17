#!/usr/bin/env python3
"""Occupation monitor updater. Runs on GitHub Actions; needs no other machine.

1. Looks at the Census Bureau's Current Population Survey folder for monthly public-use files not yet processed.
2. Reads each new file and writes two small tables: jobs by occupation and age (data/monthly), and jobs by state and
   occupation group (data/monthly_state).
3. Rebuilds the site's data files in docs/ from those tables.
Exits without changes when there is no new month. Python standard library only.

usage: update.py [--local DIR]   (DIR: a folder of already-downloaded <mon><yy>pub.dat.gz files, searched recursively)
"""
import collections, csv, datetime, glob, io, json, os, re, subprocess, sys, tempfile, urllib.request
ROOT = os.path.dirname(os.path.abspath(__file__)); D = f'{ROOT}/data'; DOCS = f'{ROOT}/docs'
BASE = 'https://www2.census.gov/programs-surveys/cps/datasets'; FIRST_YEAR = 2011; BASE_MONTH = '2022-11'
MON = dict(jan=1, feb=2, mar=3, apr=4, may=5, jun=6, jul=7, aug=8, sep=9, oct=10, nov=11, dec=12)
FIPS = {1:('AL','Alabama','South'),2:('AK','Alaska','West'),4:('AZ','Arizona','West'),5:('AR','Arkansas','South'),6:('CA','California','West'),8:('CO','Colorado','West'),9:('CT','Connecticut','Northeast'),10:('DE','Delaware','South'),11:('DC','District of Columbia','South'),12:('FL','Florida','South'),13:('GA','Georgia','South'),15:('HI','Hawaii','West'),16:('ID','Idaho','West'),17:('IL','Illinois','Midwest'),18:('IN','Indiana','Midwest'),19:('IA','Iowa','Midwest'),20:('KS','Kansas','Midwest'),21:('KY','Kentucky','South'),22:('LA','Louisiana','South'),23:('ME','Maine','Northeast'),24:('MD','Maryland','South'),25:('MA','Massachusetts','Northeast'),26:('MI','Michigan','Midwest'),27:('MN','Minnesota','Midwest'),28:('MS','Mississippi','South'),29:('MO','Missouri','Midwest'),30:('MT','Montana','West'),31:('NE','Nebraska','Midwest'),32:('NV','Nevada','West'),33:('NH','New Hampshire','Northeast'),34:('NJ','New Jersey','Northeast'),35:('NM','New Mexico','West'),36:('NY','New York','Northeast'),37:('NC','North Carolina','South'),38:('ND','North Dakota','Midwest'),39:('OH','Ohio','Midwest'),40:('OK','Oklahoma','South'),41:('OR','Oregon','West'),42:('PA','Pennsylvania','Northeast'),44:('RI','Rhode Island','Northeast'),45:('SC','South Carolina','South'),46:('SD','South Dakota','Midwest'),47:('TN','Tennessee','South'),48:('TX','Texas','South'),49:('UT','Utah','West'),50:('VT','Vermont','Northeast'),51:('VA','Virginia','South'),53:('WA','Washington','West'),54:('WV','West Virginia','South'),55:('WI','Wisconsin','Midwest'),56:('WY','Wyoming','West')}

def codeset(ym): return '2010' if ym < '2020-01' else '2018'
def load_map():
    m = {}
    for r in csv.DictReader(open(f'{D}/code_to_occupation.csv')): m[(r['codeset'], r['occ'].zfill(4))] = (r['gid'], r['group'])
    return m
def age_group(a): return '16-21' if a < 22 else '22-25' if a < 26 else '26-30' if a < 31 else '31-34' if a < 35 else '35-40' if a < 41 else '41-49' if a < 50 else '50+'

def parse(path, ym, cmap):
    """Fixed-width record, 1-based columns: HRMONTH 16-17, HRYEAR4 18-21, GESTFIPS 93-94, PRTAGE 122-123, PEMLR 180-181,
    PWCMPWGT 846-855 (4 implied decimals), PEIO1OCD 860-863. Employed = PEMLR 1,2. Unemployed = PEMLR 3,4."""
    E = collections.defaultdict(float); U = collections.defaultdict(float); N = collections.defaultdict(int)
    SE = collections.defaultdict(float); SU = collections.defaultdict(float); SN = collections.defaultdict(int); cs = codeset(ym); recs = 0
    pr = subprocess.Popen(['gzip', '-dcq', path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    with io.TextIOWrapper(pr.stdout, encoding='latin-1') as fh:
        for L in fh:
            recs += 1
            try: ml = int(L[179:181]); a = int(L[121:123]); w = int(L[845:855]) / 1e4; st = int(L[92:94])
            except ValueError: continue
            if ml not in (1, 2, 3, 4) or a < 16 or w <= 0: continue
            if L[17:21] + '-' + L[15:17].strip().zfill(2) != ym: raise SystemExit(f'{path}: record dated {L[15:21]!r}, expected {ym}')
            occ = L[859:863].strip(); k = (occ, age_group(a)); N[k] += 1
            grp = cmap.get((cs, occ.zfill(4)), (None, 'Unclassified'))[1] if occ.lstrip('-').isdigit() and not occ.startswith('-') else 'No previous job'
            s = (FIPS.get(st, ('??',))[0], grp); SN[s] += 1
            if ml < 3: E[k] += w; SE[s] += w
            else: U[k] += w; SU[s] += w
    emp = sum(E.values())
    if recs < 80000 or not 120e6 < emp < 200e6: raise SystemExit(f'{path}: {recs} records, {emp:,.0f} employed. The file layout may have changed; nothing written.')
    for name, keys, cols, tabs in (('monthly', sorted(N), 'month,occ,age,employed,unemployed,n', (E, U, N)), ('monthly_state', sorted(SN), 'month,state,group,employed,unemployed,n', (SE, SU, SN))):
        os.makedirs(f'{D}/{name}', exist_ok=True); out = f'{D}/{name}/{ym}.csv'
        with open(out + '.tmp', 'w') as o:
            o.write(cols + '\n')
            wr = csv.writer(o, lineterminator='\n')
            for k in keys: wr.writerow([ym, k[0], k[1], f'{tabs[0][k]:.1f}', f'{tabs[1][k]:.1f}', tabs[2][k]])
        os.replace(out + '.tmp', out)
    print(f'parsed {ym}: {recs:,} records, {emp / 1e6:.1f} million employed')

def ym_of(name):
    m = re.match(r'^([a-z]{3})(\d\d)pub\.dat\.gz$', name)
    return f'20{m.group(2)}-{MON[m.group(1)]:02d}' if m and m.group(1) in MON else None
def have(): return {os.path.basename(f)[:7] for f in glob.glob(f'{D}/monthly/*.csv')} & {os.path.basename(f)[:7] for f in glob.glob(f'{D}/monthly_state/*.csv')}

def fetch_new(cmap):
    done = have(); this = datetime.date.today().year; last = max(int(max(done)[:4]), FIRST_YEAR) if done else FIRST_YEAR; n = 0
    for y in range(last, this + 1):
        try: html = urllib.request.urlopen(urllib.request.Request(f'{BASE}/{y}/basic/', headers={'User-Agent': 'occupation-monitor'}), timeout=60).read().decode('latin-1')
        except Exception as e: print(f'{y}: listing not available ({e})'); continue
        for name in sorted(set(re.findall(r'href="([a-z]{3}\d\dpub\.dat\.gz)"', html)), key=ym_of):
            ym = ym_of(name)
            if ym in done: continue
            with tempfile.TemporaryDirectory() as t:
                p = f'{t}/{name}'; subprocess.run(['curl', '-sSL', '--retry', '3', '-m', '900', '-o', p, f'{BASE}/{y}/basic/{name}'], check=True); parse(p, ym, cmap); n += 1
    return n
def parse_local(folder, cmap):
    done = have(); n = 0
    for p in sorted(glob.glob(f'{folder}/**/*pub.dat.gz', recursive=True)):
        ym = ym_of(os.path.basename(p))
        if ym and ym not in done: parse(p, ym, cmap); n += 1; done.add(ym)
        if n and '--limit' in sys.argv and n >= int(sys.argv[sys.argv.index('--limit') + 1]): break
    return n

def months_between(a, b):
    y, m = map(int, a.split('-')); out = []
    while f'{y}-{m:02d}' <= b: out.append(f'{y}-{m:02d}'); y, m = (y, m + 1) if m < 12 else (y + 1, 1)
    return out
def roll12(vals):
    """12-month average; 11 of the 12 months are enough (October 2025 was never collected)."""
    out = []
    for i in range(len(vals)):
        w = [v for v in vals[max(0, i - 11):i + 1] if v is not None]
        out.append(sum(w) / len(w) if i >= 11 and len(w) >= 11 else None)
    return out
def pct(a, b): return None if not a or not b else round((a / b - 1) * 100, 1)
def k(v): return None if v is None else round(v / 1e3)

def build(cmap):
    done = sorted(have()); idx = months_between(done[0], done[-1]); pos = {m: i for i, m in enumerate(idx)}; last = len(idx) - 1; yago = last - 12; bi = pos[BASE_MONTH]; first = 11
    occs = list(csv.DictReader(open(f'{D}/occupations.csv'))); ids = {o['gid'] for o in occs}
    z = lambda: [None] * len(idx); E = collections.defaultdict(z); U = collections.defaultdict(z); Y = collections.defaultdict(z); N = collections.defaultdict(z); TOT = z()
    def add(tab, key, i, v): tab[key][i] = (tab[key][i] or 0) + v
    for ym in done:
        i = pos[ym]; cs = codeset(ym); TOT[i] = 0
        for r in csv.DictReader(open(f'{D}/monthly/{ym}.csv')):
            g = cmap.get((cs, r['occ'].zfill(4)), ('other:Unclassified',))[0] if r['occ'] and not r['occ'].startswith('-') else None
            e = float(r['employed']); u = float(r['unemployed'])
            if g is None:
                if e: g = 'other:Unclassified'
                else: continue
            if g not in ids: g = 'other:Unclassified'
            add(E, g, i, e); add(U, g, i, u); add(N, g, i, int(r['n'])); TOT[i] += e
            if r['age'] in ('16-21', '22-25', '26-30'): add(Y, g, i, e)
    for tab in (E, U, Y):
        for g in list(tab):
            for ym in done:
                if tab[g][pos[ym]] is None: tab[g][pos[ym]] = 0.0
    out = []; tot12 = roll12(TOT)
    for o in occs:
        g = o['gid']
        if g not in E: continue
        e = roll12(E[g]); u = roll12(U[g]); y = roll12(Y[g]) if g in Y else z()
        if not e[last]: continue
        fl = lambda s: None if s in ('', 'nan') else round(float(s), 2)
        out.append(dict(id=g, title=o['title'], group=o['group'], pooled=int(o['pooled']), fifth=int(float(o['fifth'])), eloundou=fl(o['eloundou_beta']), anthropic=fl(o['anthropic_exposure']), jobs=k(e[last]),
            chg1y=pct(e[last], e[yago]), chgBase=pct(e[last], e[bi]), chg1yJobs=k(e[last] - e[yago]), chgBaseJobs=k(e[last] - e[bi]),
            youngNow=round((y[last] or 0) / e[last] * 100, 1), youngBase=round((y[bi] or 0) / e[bi] * 100, 1) if e[bi] else None, unemp=k(u[last]), series=[k(v) for v in e[first:]]))
    covered = sum(E[o['id']][last] for o in out) / TOT[last] * 100
    if covered < 99.9: raise SystemExit(f'occupations cover {covered:.2f}% of employment; expected 100%')
    # states and regions
    SE = collections.defaultdict(z); SU = collections.defaultdict(z); SN = collections.defaultdict(z); groups = set()
    for ym in done:
        i = pos[ym]
        for r in csv.DictReader(open(f'{D}/monthly_state/{ym}.csv')):
            e = float(r['employed']); u = float(r['unemployed']); n = int(r['n'])
            for key in ((r['state'], 'All'), (r['state'], r['group'])):
                add(SE, key, i, e); add(SU, key, i, u); add(SN, key, i, n)
            groups.add(r['group'])
    for tab in (SE, SU, SN):
        for key in list(tab):
            for ym in done:
                if tab[key][pos[ym]] is None: tab[key][pos[ym]] = 0.0
    groups = sorted(groups - {'No previous job', 'Unclassified'}); name = {v[0]: (v[1], v[2]) for v in FIPS.values()}
    def cell(e, u, n):
        e12 = roll12(e); u12 = roll12(u); nn = sum(v or 0 for v in n[last - 11:last + 1]) / 12
        if nn < 30 or not e12[last]: return None
        ur = lambda i: None if e12[i] is None or not (e12[i] + u12[i]) else round(u12[i] / (e12[i] + u12[i]) * 100, 1)
        return dict(jobs=k(e12[last]), chg1y=pct(e12[last], e12[yago]), chgBase=pct(e12[last], e12[bi]), chg1yJobs=k(e12[last] - e12[yago]), chgBaseJobs=k(e12[last] - e12[bi]), urate=ur(last), urateBase=ur(bi)), e12
    def area(keys_for):
        row = {}
        for g in ['All'] + groups:
            e = [sum(SE[kk][i] or 0 for kk in keys_for(g)) if idx[i] in done else None for i in range(len(idx))]; u = [sum(SU[kk][i] or 0 for kk in keys_for(g)) if idx[i] in done else None for i in range(len(idx))]; n = [sum(SN[kk][i] or 0 for kk in keys_for(g)) for i in range(len(idx))]
            c = cell(e, u, n)
            if c: row[g] = c[0]
            if g == 'All' and c: row['series'] = [k(v) for v in c[1][first:]]
        return row
    states = [dict(st=s, name=name[s][0], region=name[s][1], **area(lambda g, s=s: [(s, g)])) for s in sorted(name)]
    regions = [dict(region=rg, **area(lambda g, rg=rg: [(s, g) for s in name if name[s][1] == rg])) for rg in ('Northeast', 'Midwest', 'South', 'West')]
    os.makedirs(DOCS, exist_ok=True)
    def dump(fn, rows): open(f'{DOCS}/{fn}', 'w').write('[\n' + ',\n'.join(json.dumps(r, separators=(',', ':')) for r in rows) + '\n]\n')
    dump('occupations.json', out); dump('states.json', states); dump('regions.json', regions)
    meta = dict(through=idx[last], base=BASE_MONTH, first=idx[first], months=len(idx) - first, baseIndex=bi - first, totalJobs=k(tot12[last]), occupations=len(out), groups=groups, built=datetime.datetime.utcnow().strftime('%Y-%m-%d'))
    json.dump(meta, open(f'{DOCS}/meta.json', 'w'), indent=1); print('built', meta['through'], len(out), 'occupations,', f'{covered:.1f}% of employment,', meta['totalJobs'], 'thousand jobs')

if __name__ == '__main__':
    cmap = load_map()
    n = parse_local(sys.argv[sys.argv.index('--local') + 1], cmap) if '--local' in sys.argv else fetch_new(cmap)
    print('new months:', n)
    if n or '--rebuild' in sys.argv or not os.path.exists(f'{DOCS}/meta.json'): build(cmap)
