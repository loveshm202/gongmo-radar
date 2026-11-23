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
            out.append({"t": clean(title), "org": clean(org), "s": parts[0] if parts else None,
                        "e": parts[1] if len(parts) > 1 else None, "src": "경기기업비서",
                        "url": EGB_VIEW + pid, "reg": "경기"})
        time.sleep(0.5)
    return out


# ---------- 기업마당 ----------
BIZ_LIST = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do?schEndAt=N&cpage="
BIZ_VIEW = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId="
BIZ_FIELD = {"금융": "금융", "수출": "기업·판로", "내수": "기업·판로"}


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
            parts = re.findall(r"\d{4}-\d{2}-\d{2}", period)
            out.append({"t": title, "org": org, "s": parts[0] if parts else None,
                        "e": parts[1] if len(parts) > 1 else None, "field": field,
                        "src": "기업마당", "url": BIZ_VIEW + pid.group(1)})
            added += 1
        if not added:
            break
        time.sleep(0.4)
    return out


def main(path):
    now = dt.datetime.now(KST)
    data, notes = [], {}
    for name, fn in (("문화포털", collect_culture), ("경기기업비서", collect_egbiz), ("기업마당", collect_bizinfo)):
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
