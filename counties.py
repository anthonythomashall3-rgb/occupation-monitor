#!/usr/bin/env python3
"""County data for the occupation monitor. Runs on GitHub Actions after update.py. Python standard library only.

Sources, each fetched only when something new exists:
  QCEW (BLS Quarterly Census of Employment and Wages): jobs, establishments and weekly pay by county, every quarter since
      2014 (the earliest the BLS file service offers), plus jobs by industry for the latest quarter and the same quarter a year earlier.
  ACS 5-year tables (Census bulk files): labor force, unemployment, occupations, commuting, income, poverty, education, age.
  Population estimates (Census): population by county, 2020 onward.
Writes data/county/* (compact source tables) and docs/counties/<ST>.json (one file per state for the site).
A source that cannot be reached is skipped and the previous copy is kept."""
import csv, datetime, glob, io, json, os, sys, urllib.request
ROOT = os.path.dirname(os.path.abspath(__file__)); C = f'{ROOT}/data/county'; OUT = f'{ROOT}/docs/counties'
UA = {'User-Agent': 'occupation-monitor'}; FIRST = (2014, 1); BASE_Q = (2022, 4)
SUPER = {'1011': 'Natural resources and mining', '1012': 'Construction', '1013': 'Manufacturing', '1021': 'Trade, transportation, utilities', '1022': 'Information', '1023': 'Financial activities', '1024': 'Professional and business services', '1025': 'Education and health services', '1026': 'Leisure and hospitality', '1027': 'Other services'}
ACS = dict(a='laborForcePct', b='unemploymentRate', c='occManagement', d='occService', e='occSalesOffice', f='occConstruction', g='occProduction', h='workFromHomePct', i='commuteMinutes', j='medianHouseholdIncome', k='perCapitaIncome', l='povertyPct', m='bachelorsPct', n='medianAge')
ST = {'01':'AL','02':'AK','04':'AZ','05':'AR','06':'CA','08':'CO','09':'CT','10':'DE','11':'DC','12':'FL','13':'GA','15':'HI','16':'ID','17':'IL','18':'IN','19':'IA','20':'KS','21':'KY','22':'LA','23':'ME','24':'MD','25':'MA','26':'MI','27':'MN','28':'MS','29':'MO','30':'MT','31':'NE','32':'NV','33':'NH','34':'NJ','35':'NM','36':'NY','37':'NC','38':'ND','39':'OH','40':'OK','41':'OR','42':'PA','44':'RI','45':'SC','46':'SD','47':'TN','48':'TX','49':'UT','50':'VT','51':'VA','53':'WA','54':'WV','55':'WI','56':'WY'}

def get(url, timeout=180): return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
def qs(a, b):
    y, q = a; out = []
    while (y, q) <= b: out.append((y, q)); y, q = (y, q + 1) if q < 4 else (y + 1, 1)
    return out
def qname(t): return f'{t[0]}Q{t[1]}'
def num(s):
    try: return float(s)
    except (TypeError, ValueError): return None

def qcew_fetch(t, codes):
    """One quarter, the given industry codes -> compact rows (fips, own, ind, estabs, emp = mean of the 3 months, weekly wage)."""
    rows = []
    for code in codes:
        r = csv.DictReader(io.StringIO(get(f'https://data.bls.gov/cew/data/api/{t[0]}/{t[1]}/industry/{code}.csv').decode('latin-1')))
        for x in r:
            f = x['area_fips']
            if x['agglvl_code'] not in ('70', '71', '73') or not f.isdigit() or f[2:] in ('000', '999') or f[:2] not in ST: continue
            if code != '10' and x['own_code'] != '5': continue
            sup = x['disclosure_code'].strip() == 'N'; e = [num(x[f'month{i}_emplvl']) for i in (1, 2, 3)]
            rows.append([f, x['own_code'], code, x['qtrly_estabs'], '' if sup else round(sum(e) / 3), '' if sup else x['avg_wkly_wage']])
    return rows
def qcew_update():
    os.makedirs(f'{C}/qcew', exist_ok=True); today = datetime.date.today(); end = (today.year, (today.month - 1) // 3 + 1); new = 0
    have = {os.path.basename(p)[:6] for p in glob.glob(f'{C}/qcew/*.csv')}
    for t in qs(FIRST, end):
        if qname(t) in have: continue
        if '--budget' in sys.argv and new >= int(sys.argv[sys.argv.index('--budget') + 1]): break
        try: rows = qcew_fetch(t, ['10'])
        except Exception as e:
            print(qname(t), 'not available:', str(e)[:60]); 
            if t > (today.year - 1, 1): break
            continue
        with open(f'{C}/qcew/{qname(t)}.csv', 'w', newline='') as o: w = csv.writer(o); w.writerow(['fips', 'own', 'ind', 'estabs', 'emp', 'wage']); w.writerows(rows)
        new += 1; print('QCEW', qname(t), len(rows))
    have = sorted(os.path.basename(p)[:6] for p in glob.glob(f'{C}/qcew/*.csv')); last = (int(have[-1][:4]), int(have[-1][5])); prev = (last[0] - 1, last[1])
    for t in (last, prev):
        p = f'{C}/qcew_industry_{qname(t)}.csv'
        if os.path.exists(p): continue
        try: rows = qcew_fetch(t, list(SUPER))
        except Exception as e: print('industry', qname(t), 'not available:', str(e)[:60]); continue
        with open(p, 'w', newline='') as o: w = csv.writer(o); w.writerow(['fips', 'own', 'ind', 'estabs', 'emp', 'wage']); w.writerows(rows)
        new += 1; print('QCEW industries', qname(t), len(rows))
    return new
ACS_TABLES = {'b23025': [1, 2, 3, 5], 'c24060': [1, 2, 3, 4, 5, 6], 'b19013': [1], 'b19301': [1], 'b01002': [1], 'b08301': [1, 21], 'b08013': [1], 'b17001': [1, 2], 'b15003': [1, 22, 23, 24, 25]}
def acs_update():
    """ACS 5-year detailed tables from the Census bulk files (no API key needed). County rows only (GEO_ID 0500000US...)."""
    base = 'https://www2.census.gov/programs-surveys/acs/summary_file'; y = datetime.date.today().year - 1; new = 0
    while y >= 2023:
        p = f'{C}/acs5_{y}.csv'
        if os.path.exists(p): return 0
        try:
            os.makedirs(f'{C}/acs_tables', exist_ok=True)  # download cache, not committed; V = {}
            for t, cols in ACS_TABLES.items():
                tp = f'{C}/acs_tables/{y}_{t}.csv'
                if not os.path.exists(tp):
                    r = urllib.request.urlopen(urllib.request.Request(f'{base}/{y}/table-based-SF/data/5YRData/acsdt5y{y}-{t}.dat', headers=UA), timeout=300)
                    head = r.readline().decode().strip().split('|'); ix = [head.index(f'{t.upper()}_E{c:03d}') for c in cols]; rows = []
                    for line in r:
                        if line.startswith(b'0500000US'):
                            x = line.decode('latin-1').strip().split('|'); rows.append([x[0][9:]] + [x[i] for i in ix])
                    with open(tp + '.tmp', 'w', newline='') as o: w = csv.writer(o); w.writerow(['fips'] + [f'{t}_{c:03d}' for c in cols]); w.writerows(rows)
                    os.replace(tp + '.tmp', tp); print('ACS table', y, t, len(rows))
                for x in csv.DictReader(open(tp)): V.setdefault(x['fips'], {}).update({k: num(v) for k, v in x.items() if k != 'fips'})
            def ratio(v, a, b, m=100):
                A = sum(v.get(k) or 0 for k in a) if isinstance(a, list) else v.get(a); B = v.get(b)
                return '' if A is None or not B or A < 0 or B <= 0 else round(A / B * m, 1)
            def val(v, k): return '' if v.get(k) is None or v[k] < 0 else v[k]
            with open(p, 'w', newline='') as o:
                w = csv.writer(o); w.writerow(['fips'] + list(ACS.values()))
                for f in sorted(V):
                    v = V[f]; away = (v.get('b08301_001') or 0) - (v.get('b08301_021') or 0)
                    w.writerow([f, ratio(v, 'b23025_002', 'b23025_001'), ratio(v, 'b23025_005', 'b23025_003'), ratio(v, 'c24060_002', 'c24060_001'), ratio(v, 'c24060_003', 'c24060_001'), ratio(v, 'c24060_004', 'c24060_001'), ratio(v, 'c24060_005', 'c24060_001'), ratio(v, 'c24060_006', 'c24060_001'),
                                ratio(v, 'b08301_021', 'b08301_001'), '' if not v.get('b08013_001') or v['b08013_001'] < 0 or away <= 0 else round(v['b08013_001'] / away, 1), val(v, 'b19013_001'), val(v, 'b19301_001'), ratio(v, 'b17001_002', 'b17001_001'), ratio(v, ['b15003_022', 'b15003_023', 'b15003_024', 'b15003_025'], 'b15003_001'), val(v, 'b01002_001')])
            print('ACS', y, len(V)); return 1
        except Exception as e: print('ACS', y, 'not available:', str(e)[:80]); y -= 1
    return new
def pop_update():
    y = datetime.date.today().year
    while y >= 2024:
        p = f'{C}/population_{y}.csv'
        if os.path.exists(p): return 0
        try:
            r = csv.DictReader(io.StringIO(get(f'https://www2.census.gov/programs-surveys/popest/datasets/2020-{y}/counties/totals/co-est{y}-alldata.csv').decode('latin-1')))
            rows = [[x['STATE'] + x['COUNTY'], x['CTYNAME'], x.get('ESTIMATESBASE2020', ''), x[f'POPESTIMATE{y}'], x.get(f'NETMIG{y}', '')] for x in r if x['COUNTY'] != '000']
            with open(p, 'w', newline='') as o: w = csv.writer(o); w.writerow(['fips', 'name', 'pop2020', 'pop', 'netMigration']); w.writerows(rows)
            print('population', y, len(rows)); return 1
        except Exception as e: print('population', y, 'not available:', str(e)[:60]); y -= 1
    return 0

def pct(a, b): return None if not a or not b else round((a / b - 1) * 100, 1)
def build():
    files = sorted(glob.glob(f'{C}/qcew/*.csv')); names = [os.path.basename(p)[:6] for p in files]; T = {}; GOV = {}; latest = {}
    for i, p in enumerate(files):
        for x in csv.DictReader(open(p)):
            if x['own'] == '0': T.setdefault(x['fips'], [None] * len(files))[i] = (num(x['emp']), num(x['estabs']), num(x['wage']))
            elif i == len(files) - 1 and x['own'] in ('1', '2', '3') and x['emp']: GOV[x['fips']] = GOV.get(x['fips'], 0) + float(x['emp'])
            elif i == len(files) - 5 and x['own'] in ('1', '2', '3') and x['emp']: latest.setdefault(x['fips'], {})['gov0'] = latest.get(x['fips'], {}).get('gov0', 0) + float(x['emp'])
    bi = names.index(qname(BASE_Q)); n = len(files); ind = {}
    for tag, t in (('now', names[-1]), ('ago', f'{int(names[-1][:4]) - 1}Q{names[-1][5]}')):
        p = f'{C}/qcew_industry_{t}.csv'
        if os.path.exists(p):
            for x in csv.DictReader(open(p)):
                if x['emp']: ind.setdefault(x['fips'], {}).setdefault(x['ind'], {})[tag] = float(x['emp'])
    acs = {}; pop = {}
    a = sorted(glob.glob(f'{C}/acs5_*.csv')); pp = sorted(glob.glob(f'{C}/population_*.csv'))
    if a:
        for x in csv.DictReader(open(a[-1])): acs[x['fips']] = {k: v for k, v in ((k, num(v)) for k, v in x.items() if k != 'fips') if v is not None and v > -1e6}
    if pp:
        for x in csv.DictReader(open(pp[-1])): pop[x['fips']] = x
    def avg4(s, i, j):
        w = [v[j] for v in s[i - 3:i + 1] if v and v[j] is not None]
        return sum(w) / len(w) if i >= 3 and len(w) == 4 else None
    by = {}
    for f, s in T.items():
        e = [avg4(s, i, 0) for i in range(n)]; wg = [avg4(s, i, 2) for i in range(n)]
        if e[-1] is None: continue
        r = dict(fips=f, name=pop.get(f, {}).get('name', ''), jobs=round(e[-1]), chg1y=pct(e[-1], e[-5]), chg1yJobs=None if e[-5] is None else round(e[-1] - e[-5]), chgBase=pct(e[-1], e[bi]), chgBaseJobs=None if e[bi] is None else round(e[-1] - e[bi]),
                 estabs=None if not s[-1] or s[-1][1] is None else round(s[-1][1]), wage=None if wg[-1] is None else round(wg[-1]), wageChg1y=pct(wg[-1], wg[-5]), series=[None if v is None else round(v) for v in e[3:]])
        ii = [[SUPER[c], round(v['now']), pct(v['now'], v.get('ago'))] for c, v in sorted(ind.get(f, {}).items()) if 'now' in v]
        if f in GOV: ii.append(['Government', round(GOV[f]), pct(GOV[f], latest.get(f, {}).get('gov0'))])
        if ii: r['industries'] = sorted(ii, key=lambda z: -z[1])
        if f in pop: r['pop'] = int(pop[f]['pop']); r['popChg'] = pct(num(pop[f]['pop']), num(pop[f]['pop2020'])); r['netMigration'] = None if pop[f]['netMigration'] == '' else int(pop[f]['netMigration'])
        if f in acs: r['acs'] = acs[f]
        by.setdefault(ST[f[:2]], []).append(r)
    os.makedirs(OUT, exist_ok=True)
    for st, rows in by.items(): open(f'{OUT}/{st}.json', 'w').write('[\n' + ',\n'.join(json.dumps(r, separators=(',', ':')) for r in sorted(rows, key=lambda r: r['fips'])) + '\n]\n')
    meta = dict(quarter=names[-1], firstQuarter=names[3], quarters=n - 3, baseIndex=bi - 3, baseQuarter=qname(BASE_Q), acs=os.path.basename(a[-1])[5:9] if a else None, population=os.path.basename(pp[-1])[11:15] if pp else None, counties=sum(len(v) for v in by.values()))
    json.dump(meta, open(f'{OUT}/meta.json', 'w'), indent=1); print('built counties', meta)

if __name__ == '__main__':
    n = qcew_update() + acs_update() + pop_update(); print('new county files:', n)
    if (n or '--rebuild' in sys.argv or not os.path.exists(f'{OUT}/meta.json')) and '--no-build' not in sys.argv: build()
