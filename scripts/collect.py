"""공모 레이더 데이터 수집기.

문화포털(문화지원사업), 경기기업비서, 기업마당에서 지금 접수 중인 공고를 모아
data.json 으로 저장한다. 표준 라이브러리만 쓴다.

사용: python scripts/collect.py [출력경로]
"""
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; gongmo-radar/1.0)"
KST = dt.timezone(dt.timedelta(hours=9))


def fetch(url, data=None, tries=3):
    body = urllib.parse.urlencode(data).encode() if data else None
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # 네트워크 오류는 잠깐 쉬고 다시 시도
            last = e
            time.sleep(2 * (i + 1))
    raise last


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def norm_date(s):
    m = re.search(r"(\d{4})[-.](\d{1,2})[-.](\d{1,2})", s or "")
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


# ---------- 문화포털 ----------
CUL_LIST = "https://www.culture.go.kr/portal/cltBnf/cltSup/getRcrtinfoList.do?viewType=CONTBODY"
CUL_VIEW = "https://www.culture.go.kr/portal/cltBnf/cltSup/view.do?menuNo=200104&rcrtSn="
CUL_CATS = {"01": "문화예술", "02": "인문·출판", "03": "관광", "04": "체육"}


def collect_culture():
    out = []
    for code, cat in CUL_CATS.items():
        page = 1
        while page < 30:
            s = fetch(CUL_LIST, {
                "pageIndex": page, "menuNo": "200104", "searchPageUnit": 100,
                "searchSttscd": "S", "sSort": "2", "trgtInstCd": "CT00000",
                "clctFldCd": code, "searchFldCd": code,
            })
            items = re.findall(r"<li>\s*<input[^>]*scrapSn.*?</li>", s, re.S)
            if not items:
                break
            for it in items:
                sn = re.search(r"rcrtSn=(\d+)", it)
                if not sn:
                    continue
                org = clean((re.search(r'class="logo">\s*<span>(.*?)</span>', it, re.S) or [None, ""])[1])
                title = clean((re.search(r'class="tit__title">(.*?)</span>', it, re.S) or [None, ""])[1])
                tgt = clean((re.search(r'class="support-txt">(.*?)</span>', it, re.S) or [None, ""])[1])
                typ = "/".join(clean(b) for b in re.findall(r'class="badge-box">(.*?)</div>', it, re.S))
                end = norm_date((re.search(r'class="num">(.*?)</span>', it, re.S) or [None, ""])[1])
                out.append({"t": title, "org": org, "tgt": tgt, "type": typ, "s": None, "e": end,
                            "cat": cat, "src": "문화포털", "url": CUL_VIEW + sn.group(1)})
            if len(items) < 100:
                break
            page += 1
            time.sleep(0.5)
    return out


# ---------- 경기기업비서 ----------
EGB_LIST = "https://www.egbiz.or.kr/sp/supportPrjOutsideList.do"
EGB_VIEW = "https://www.egbiz.or.kr/sp/supportPrjOutsideDtl.do?listUrl=supportPrjOutsideList&bizCyclId="


def collect_egbiz():
    out, seen = [], set()
    for page in range(1, 40):
        s = fetch(EGB_LIST, {"pageIndex": page, "prjStatus": "apply"})
        rows = re.findall(
            r"fn_supportPrjDtl\('(PD\d+)'\);\">(.*?)</a>.*?<td>(.*?)</td>\s*<td>(.*?)</td>", s, re.S)
        new = [r for r in rows if r[0] not in seen]
        if not new:
            break
        for pid, title, org, period in new:
            seen.add(pid)
            parts = re.findall(r"\d{4}-\d{2}-\d{2}", period)
            row = {"t": clean(title), "org": clean(org), "s": parts[0] if parts else None,
                   "e": parts[1] if len(parts) > 1 else None, "src": "경기기업비서",
                   "url": EGB_VIEW + pid, "reg": "경기"}
            rest = clean(re.sub(r"\d{4}-\d{2}-\d{2}", "", period)).strip(" -~")
            if len(parts) < 2 and rest:
                row["note"] = rest
            out.append(row)
        time.sleep(0.5)
    return out


# ---------- 기업마당 ----------
BIZ_LIST = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do?schEndAt=N&cpage="
BIZ_VIEW = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId="
BIZ_FIELD = {"금융": "금융", "수출": "기업·판로", "내수": "기업·판로"}
# 문화·소상공인 중심 사이트라 이 분야는 아래 낱말이 제목에 있을 때만 남긴다.
BIZ_NARROW_FIELDS = {"기술", "수출", "인력"}
BIZ_KEEP_WORDS = re.compile(r"소상공인|자영업|소공인|상권|전통시장|문화|예술|콘텐츠|관광|축제|공예|디자인|로컬|농식품|식품|카페|음식")


def collect_bizinfo():
    out, seen = [], set()
    for page in range(1, 200):
        s = fetch(BIZ_LIST + str(page))
        rows = re.findall(r"<tr>\s*<td>\d+</td>(.*?)</tr>", s, re.S)
        added = 0
        for row in rows:
            pid = re.search(r"pblancId=(PBLN_\d+)", row)
            if not pid or pid.group(1) in seen:
                continue
            seen.add(pid.group(1))
            tds = [clean(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            # tds: 분야, 사업명, 신청기간, 소관부처, 수행기관, 등록일, 조회수
            if len(tds) < 5:
                continue
            field, title, period, _, org = tds[:5]
            added += 1
            if field in BIZ_NARROW_FIELDS and not BIZ_KEEP_WORDS.search(title):
                continue
            parts = re.findall(r"\d{4}-\d{2}-\d{2}", period)
            row = {"t": title, "org": org, "s": parts[0] if parts else None,
                   "e": parts[1] if len(parts) > 1 else None, "field": field,
                   "src": "기업마당", "url": BIZ_VIEW + pid.group(1)}
            if not parts and period:
                row["note"] = period  # 예: 예산 소진시까지, 상시 접수, 세부사업별 상이
            if len(tds) > 5 and re.match(r"\d{4}-\d{2}-\d{2}$", tds[5]):
                row["posted"] = tds[5]
            out.append(row)
        if not added:
            break
        time.sleep(0.4)
    return out


# ---------- 해외 공모 (유럽·일본·미국, 한국인 지원 가능) ----------
EUROPE = {
    "AT": "오스트리아", "BE": "벨기에", "BG": "불가리아", "HR": "크로아티아", "CY": "키프로스", "CZ": "체코",
    "DK": "덴마크", "EE": "에스토니아", "FI": "핀란드", "FR": "프랑스", "DE": "독일", "GR": "그리스",
    "HU": "헝가리", "IS": "아이슬란드", "IE": "아일랜드", "IT": "이탈리아", "LV": "라트비아", "LT": "리투아니아",
    "LU": "룩셈부르크", "MT": "몰타", "NL": "네덜란드", "NO": "노르웨이", "PL": "폴란드", "PT": "포르투갈",
    "RO": "루마니아", "RS": "세르비아", "SK": "슬로바키아", "SI": "슬로베니아", "ES": "스페인", "SE": "스웨덴",
    "CH": "스위스", "GB": "영국", "UK": "영국", "UA": "우크라이나", "TR": "튀르키예", "AL": "알바니아",
    "BA": "보스니아", "ME": "몬테네그로", "MK": "북마케도니아", "MD": "몰도바", "GE": "조지아", "AM": "아르메니아",
}
COUNTRY_EN = {
    "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY", "Czech Republic": "CZ",
    "Czechia": "CZ", "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR", "Germany": "DE",
    "Greece": "GR", "Hungary": "HU", "Iceland": "IS", "Ireland": "IE", "Italy": "IT", "Latvia": "LV",
    "Lithuania": "LT", "Luxembourg": "LU", "Malta": "MT", "Netherlands": "NL", "Norway": "NO", "Poland": "PL",
    "Portugal": "PT", "Romania": "RO", "Serbia": "RS", "Slovakia": "SK", "Slovenia": "SI", "Spain": "ES",
    "Sweden": "SE", "Switzerland": "CH", "United Kingdom": "GB", "Ukraine": "UA", "Turkey": "TR",
    "Japan": "JP", "United States of America": "US", "United States": "US", "USA": "US", "Europe": "EU",
}


def abroad(code):
    """국가 코드 -> (권역, 국가 한글명). 대상 밖이면 None."""
    if code == "JP":
        return "일본", "일본"
    if code == "US":
        return "미국", "미국"
    if code == "EU":
        return "유럽", "유럽"
    if code in EUROPE:
        return "유럽", EUROPE[code]
    return None


OPEN_WORDS = re.compile(r"all countries|any countr|any nationalit|all nationalit|regardless of nationality|"
                        r"international artists|worldwide|from around the world|open to all|korea|asia", re.I)
CLOSED_WORDS = re.compile(r"(citizens?|nationals?|residents?|resident artists?) of|must (be|live|reside|work)[^.]{0,60}"
                          r"\b(in|of)\b|based in|living in|legally[^.]{0,40}(EU|European Union|United States|US)|"
                          r"eu passport|EU/EEA|green card|social security number|county", re.I)


def open_to_korean(text):
    """지원 자격 문장으로 한국인 지원 가능 여부를 어림한다. 모르면 True."""
    if not text:
        return True
    if OPEN_WORDS.search(text):
        return True
    return not CLOSED_WORDS.search(text)


OTM_BASE = "https://on-the-move.org"
OTM_TYPE = {"Residencies": "레지던시", "Project Funding": "지원금", "Fellowships": "펠로십",
            "Competitions & Awards": "공모전·상", "Presenting Work": "발표 기회", "Training": "교육",
            "Meetings & Collaboration": "교류", "Jobs": "채용", "Surveys & Policy": "조사"}


def collect_onthemove():
    out, seen = [], set()
    for page in range(0, 15):
        s = fetch(f"{OTM_BASE}/news?page={page}")
        cards = re.findall(r"<div class='list_title'>(.*?)class='list-link'", s, re.S)
        new = 0
        for c in cards:
            href = re.search(r"href='(/news/[^']+)'", c)
            if not href or href.group(1) in seen:
                continue
            seen.add(href.group(1))
            new += 1
            title = clean((re.search(r"block-title'>(.*?)</span>", c, re.S) or [None, ""])[1])
            typ = clean((re.search(r"list_meta_news-type'>(.*?)</div>", c, re.S) or [None, ""])[1])
            dl = re.search(r'datetime="(\d{4}-\d{2}-\d{2})', c)
            if typ in ("Jobs", "Surveys & Policy"):
                continue
            # 상세 페이지: 대상 국가, 지원 대상, 원문 링크, 본문(자격 확인용)
            try:
                d = fetch(OTM_BASE + href.group(1))
            except Exception:
                continue
            main = re.search(r"<main.*?</main>", d, re.S)
            body = clean(main.group(0)) if main else ""
            dest = re.search(r"Destination countries:(.*?)(?:The |This |[A-Z][a-z]+ [a-z])", body)
            names = [n.strip() for n in re.split(r"\s{1,}(?=[A-Z])", dest.group(1).strip())] if dest else []
            codes = []
            for n in names:
                for en, code in COUNTRY_EN.items():
                    if en in n and code not in codes:
                        codes.append(code)
            if not codes:
                m = re.search(r"\(([^()]+)\)\s*$", title)
                if m:
                    codes = [code for en, code in COUNTRY_EN.items() if en in m.group(1)]
            places = [abroad(c) for c in codes]
            places = [p for p in places if p]
            if not places or not open_to_korean(body):
                continue
            more = re.search(r'href="(https?://[^"]+)"[^>]*>\s*More info', d)
            opn = re.search(r"Open for:(.*?)Destination", body)
            out.append({
                "t": title, "org": title.split(":")[0].strip() if ":" in title else "On the Move", "s": None, "e": dl.group(1) if dl else None,
                "cat": "해외", "reg": places[0][0], "nation": "·".join(dict.fromkeys(p[1] for p in places)),
                "type": OTM_TYPE.get(typ, typ), "tgt": clean(opn.group(1)) if opn else "",
                "src": "On the Move", "url": OTM_BASE + href.group(1),
                "apply": html.unescape(more.group(1)) if more else None,
            })
            time.sleep(0.7)
        if not new:
            break
        time.sleep(0.7)
    return out


AC_BASE = "https://www.artconnect.com"
AC_TYPE = {"ART_RESIDENCY": "레지던시", "OPEN_CALL": "공모", "GRANT_OR_STIPEND": "지원금",
           "AWARD_OR_PRICE": "공모전·상", "CALL_FOR_CURATORS": "큐레이터 공모",
           "ARTIST_COMMISSION": "작품 의뢰", "EXHIBITION": "전시"}


def ac_items(page_html):
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', page_html, re.S)
    txt = "".join(json.loads('"' + c + '"') for c in chunks)
    dec, items = json.JSONDecoder(), []
    for m in re.finditer(r'\{"id":"[^"]+","profile":\{', txt):
        try:
            obj, _ = dec.raw_decode(txt, m.start())
        except ValueError:
            continue
        if "deadline" in obj and "title" in obj:
            items.append(obj)
    return items


def collect_artconnect():
    out, seen = [], set()
    for page in range(1, 60):
        items = ac_items(fetch(f"{AC_BASE}/opportunities?page={page}"))
        new = [it for it in items if it["id"] not in seen]
        if not new:
            break
        for it in new:
            seen.add(it["id"])
            if it.get("type") not in AC_TYPE or it.get("isOnline"):
                continue
            r = it.get("restrictions") or {}
            nat = r.get("nationality")
            if nat and "KR" not in json.dumps(nat):
                continue
            locs = r.get("locations") or []
            if locs and not any((l or {}).get("country") == "KR" for l in locs):
                continue
            other = r.get("other") or ""
            if other.startswith("$"):
                other = ""
            if not open_to_korean(other):
                continue
            code = it.get("country") or ((it.get("locations") or [{}])[0] or {}).get("country") \
                or (it.get("profile") or {}).get("country")
            place = abroad(code)
            if not place:
                continue
            prof = it.get("profile") or {}
            org = prof.get("organizationName") or " ".join(
                x for x in (prof.get("firstName"), prof.get("lastName")) if x) or "ArtConnect"
            out.append({
                "t": it["title"], "org": org, "s": None, "e": (it.get("deadline") or "")[:10] or None,
                "cat": "해외", "reg": place[0], "nation": place[1], "type": AC_TYPE[it["type"]],
                "tgt": "참가비 없음" if it.get("fee") == "FREE" else "참가비 있음",
                "src": "ArtConnect", "url": f"{AC_BASE}/opportunity/{it['id']}",
            })
        time.sleep(1)
    return out


def main(path):
    now = dt.datetime.now(KST)
    data, notes = [], {}
    for name, fn in (("문화포털", collect_culture), ("경기기업비서", collect_egbiz), ("기업마당", collect_bizinfo),
                     ("On the Move", collect_onthemove), ("ArtConnect", collect_artconnect)):
        try:
            rows = fn()
            notes[name] = len(rows)
            data.extend(rows)
        except Exception as e:  # 한 곳이 실패해도 나머지는 저장
            notes[name] = f"실패: {e.__class__.__name__}"
            print(f"[{name}] 실패: {e}", file=sys.stderr)
    if not data:
        sys.exit("수집된 공고가 없어 저장하지 않음")
    # 한 곳이 실패하면 이전 data.json 에서 그 출처 공고를 이어 씀
    failed = [k for k, v in notes.items() if not isinstance(v, int)]
    if failed:
        try:
            old = json.load(open(path, encoding="utf-8"))
            keep = [d for d in old.get("items", []) if d.get("src") in failed]
            data.extend(keep)
        except Exception:
            pass
    doc = {"updated": now.strftime("%Y-%m-%d %H:%M"), "sources": notes, "items": data}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print(doc["updated"], notes, len(data))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data.json")
