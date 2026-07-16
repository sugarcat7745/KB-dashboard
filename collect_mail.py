"""
상담 이메일 수집(네이버 IMAP) → BigQuery(consult_raw) 적재.
홈페이지 '간편 상담 신청'이 lawkbsw@naver.com 로 들어와 '온라인상담문의' 폴더로 자동분류됨.
그 폴더를 읽어 이름·연락처·지역·상담내용을 구조화 → consult_raw 테이블에 저장한다.
목적: 대시보드 '상담 품질·보안' 탭에서 전화·내용 기준 스팸(같은번호·다른이름, 반복번호, 중복템플릿) 탐지.

설계 원칙
  - 멱등: UID 기준 증분 수집(이미 받은 메일은 다시 안 받음) + 전체를 WRITE_TRUNCATE로 재적재.
    (매번 폴더 전량을 내려받지 않아 네이버 보호조치(로그인 차단) 위험을 줄임)
  - 개인정보(이름·전화·상담내용)는 '비공개 BigQuery'에만 저장. 로그/CI에는 집계 수치만 출력(원문 금지).
  - 실패(로그인 차단 등)해도 통합 수집을 깨지 않도록 '경고 후 스킵(exit 0)'. 차단은 조용할 수 있으니
    freshness_guard가 아닌 이 스텝의 로그로 확인.

필요 env (GitHub Secrets) — 지메일 경로 권장(네이버 보호조치 우회):
  MAIL_IMAP_HOST  : IMAP 서버. 지메일=imap.gmail.com (미설정 시 imap.naver.com)
  MAIL_ID         : 로그인 아이디. 지메일=전체주소(kb.consult@gmail.com 등)
  MAIL_PW         : 비밀번호. 지메일=2단계인증 후 '앱 비밀번호'(16자리, 공백 제거)
  MAIL_FOLDER     : (선택) 폴더/라벨. 지메일 기본 INBOX / 네이버 기본 '온라인상담문의'
  GCP_SA_JSON     : 서비스계정 JSON 전체
  (구) NAVER_MAIL_ID/PW/FOLDER : MAIL_* 미설정 시 네이버 직결 폴백
흐름: 홈페이지 폼→lawkbsw@naver.com→(네이버 자동전달)→지메일 INBOX→여기서 수집.
"""
import os, re, json, base64, imaplib, email
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from email.header import decode_header, make_header
from html import unescape
import pandas as pd
from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT, DATASET, TABLE = "kb-dashboard-499704", "kb_ads", "consult_raw"
# 메일 서버 무관(네이버 IMAP이 보호조치로 막히면 '네이버→지메일 자동전달' 후 지메일에서 읽음).
#   MAIL_IMAP_HOST/MAIL_ID/MAIL_PW/MAIL_FOLDER(신규) 우선, 없으면 기존 NAVER_MAIL_* 폴백.
IMAP_HOST = (os.environ.get("MAIL_IMAP_HOST") or "imap.naver.com").strip()
IMAP_PORT = 993
_IS_NAVER = "naver" in IMAP_HOST.lower()
FOLDER_HINT = (os.environ.get("MAIL_FOLDER") or os.environ.get("NAVER_MAIL_FOLDER")
               or ("온라인상담문의" if _IS_NAVER else "INBOX")).strip()
COLS = ["uid", "datetime", "date", "hour", "center", "category",
        "name", "phone", "region", "content_len", "content"]
SCHEMA = [
    bigquery.SchemaField("uid", "STRING"),
    bigquery.SchemaField("datetime", "STRING"),
    bigquery.SchemaField("date", "DATE"),
    bigquery.SchemaField("hour", "INTEGER"),
    bigquery.SchemaField("center", "STRING"),
    bigquery.SchemaField("category", "STRING"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("phone", "STRING"),
    bigquery.SchemaField("region", "STRING"),
    bigquery.SchemaField("content_len", "INTEGER"),
    bigquery.SchemaField("content", "STRING"),
]


# ── 한글 폴더명(IMAP modified UTF-7, RFC 3501) 인코딩/디코딩 ──
def _utf7_encode(s):
    out, buf = [], ""

    def flush():
        nonlocal buf
        if buf:
            enc = base64.b64encode(buf.encode("utf-16-be")).decode("ascii")
            out.append("&" + enc.rstrip("=").replace("/", ",") + "-")
            buf = ""

    for ch in s:
        if ch == "&":
            flush(); out.append("&-")
        elif 0x20 <= ord(ch) <= 0x7e:
            flush(); out.append(ch)
        else:
            buf += ch
    flush()
    return "".join(out)


def _utf7_decode(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "&":
            j = s.find("-", i)
            if j < 0:
                j = len(s)
            chunk = s[i + 1:j]
            if chunk == "":
                out.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                out.append(base64.b64decode(b64).decode("utf-16-be"))
            i = j + 1
        else:
            out.append(s[i]); i += 1
    return "".join(out)


# ── 본문 파싱(parse_emails.py와 동일 규칙) ──
def _dec(payload):
    if isinstance(payload, bytes):
        for enc in ("utf-8", "euc-kr", "cp949"):
            try:
                return payload.decode(enc)
            except Exception:
                continue
        return payload.decode("utf-8", "ignore")
    return payload if isinstance(payload, str) else ""


def decode_body(msg):
    if msg.is_multipart():
        html_txt, plain_txt = "", ""
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html" and not html_txt:
                html_txt = _dec(part.get_payload(decode=True))
            elif ct == "text/plain" and not plain_txt:
                plain_txt = _dec(part.get_payload(decode=True))
        return html_txt or plain_txt
    return _dec(msg.get_payload(decode=True))


def clean_text(html):
    t = re.sub(r'(?is)<br\s*/?>', '\n', html)
    t = re.sub(r'(?is)<[^>]+>', ' ', t)
    t = unescape(t)
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\n\s*\n+', '\n', t)
    return t.strip()


def parse_fields(text):
    d = {}
    for line in text.split('\n'):
        m = re.match(r'\s*([가-힣A-Za-z ]{1,12})\s*[:：]\s*(.+)', line)
        if m:
            k, v = m.group(1).strip(), m.group(2).strip()
            if k and v and k not in d:
                d[k] = v
    return d


def norm_phone(p):
    return re.sub(r'\D', '', p) if p else ""


def _subject(msg):
    try:
        return str(make_header(decode_header(msg.get("Subject") or "")))
    except Exception:
        return msg.get("Subject") or ""


def parse_message(uid_key, raw):
    msg = email.message_from_bytes(raw)
    subj = _subject(msg)
    sm = re.match(r'\s*\[(.*?)\]\s*(.*?)\s*(?:\||$)', subj)
    subj_center = sm.group(1).strip() if sm else ""
    subj_cat = sm.group(2).strip() if sm else ""
    try:
        dt = parsedate_to_datetime(msg.get("Date"))
    except Exception:
        dt = None
    dt_s = dt.strftime("%Y-%m-%d %H:%M:%S") if dt else ""
    date_s = dt.strftime("%Y-%m-%d") if dt else ""
    hour = dt.hour if dt else -1
    body = clean_text(decode_body(msg))
    f = parse_fields(body)
    name = f.get("이름", "")
    phone = norm_phone(f.get("연락처", "") or f.get("전화", "") or f.get("휴대폰", ""))
    region = f.get("지역", "")
    center = (f.get("센터", "") or subj_center).strip()
    content = f.get("상담내용", "") or f.get("내용", "") or body
    clen = len(re.sub(r'\s', '', content))
    return {
        "uid": uid_key, "datetime": dt_s, "date": date_s, "hour": hour,
        "center": center, "category": subj_cat, "name": name, "phone": phone,
        "region": region, "content_len": clen,
        "content": content[:300].replace("\n", " ").strip(),
    }


# ── BigQuery ──
def _client():
    info = json.loads(os.environ["GCP_SA_JSON"])
    return bigquery.Client(project=PROJECT,
                           credentials=service_account.Credentials.from_service_account_info(info))


def load_existing(client):
    tid = f"{PROJECT}.{DATASET}.{TABLE}"
    try:
        return client.query(f"SELECT {', '.join(COLS)} FROM `{tid}`").to_dataframe()
    except Exception:
        return pd.DataFrame(columns=COLS)


def save(client, df):
    tid = f"{PROJECT}.{DATASET}.{TABLE}"
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.date
    client.load_table_from_dataframe(
        out[COLS], tid,
        job_config=bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE", schema=SCHEMA)
    ).result()


# ── IMAP ──
def find_folder(imap):
    """리스트에서 FOLDER_HINT(부분일치)에 해당하는 폴더의 '원시(UTF-7) 이름'을 찾는다."""
    typ, data = imap.list()
    if typ != "OK":
        raise RuntimeError("IMAP LIST 실패")
    for line in data:
        s = line.decode("ascii", "ignore") if isinstance(line, bytes) else str(line)
        m = re.search(r'"([^"]*)"\s*$', s) or re.search(r'([^ ]+)\s*$', s)
        raw = m.group(1) if m else ""
        if not raw:
            continue
        if FOLDER_HINT in _utf7_decode(raw) or FOLDER_HINT in raw:
            return raw
    return None


def fetch_new(imap, raw_folder, seen_uids):
    """폴더 선택 → UID 목록 중 미수집분만 본문 FETCH → 파싱 rows."""
    st, sd = imap.status(raw_folder, "(UIDVALIDITY)")
    uidv = ""
    if st == "OK" and sd:
        mm = re.search(r'UIDVALIDITY (\d+)', sd[0].decode("ascii", "ignore"))
        uidv = mm.group(1) if mm else ""
    imap.select(f'"{raw_folder}"', readonly=True)
    typ, data = imap.uid("SEARCH", None, "ALL")
    if typ != "OK":
        raise RuntimeError("IMAP SEARCH 실패")
    uids = data[0].split() if data and data[0] else []
    rows, n_skip = [], 0
    for u in uids:
        us = u.decode() if isinstance(u, bytes) else str(u)
        key = f"{uidv}-{us}"
        if key in seen_uids:
            n_skip += 1
            continue
        t, d = imap.uid("FETCH", u, "(RFC822)")
        if t != "OK" or not d or not d[0]:
            continue
        raw = d[0][1]
        try:
            rows.append(parse_message(key, raw))
        except Exception:
            continue
    return rows, len(uids), n_skip


def main():
    uid = (os.environ.get("MAIL_ID") or os.environ.get("NAVER_MAIL_ID") or "").strip()
    pw = os.environ.get("MAIL_PW") or os.environ.get("NAVER_MAIL_PW") or ""
    if not uid or not pw:
        print("MAIL_ID/PW(또는 NAVER_MAIL_*) 미설정 → 상담메일 수집 스킵(설정 전 안전)")
        return
    print(f"[상담메일] IMAP {IMAP_HOST} · 폴더 '{FOLDER_HINT}'")
    client = _client()
    existing = load_existing(client)
    seen = set(existing["uid"].astype(str)) if not existing.empty else set()

    # 아이디 후보: 그대로 + (네이버면) '@naver.com' 붙인/뗀 형태를 순서대로 시도(형식 문제 자동 배제).
    ids = [uid]
    if "@" in uid:
        ids.append(uid.split("@")[0])
    elif _IS_NAVER:
        ids.append(f"{uid}@naver.com")
    imap, last_reason = None, ""
    for cand in ids:
        try:
            imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            imap.login(cand, pw)
            break
        except Exception as e:
            # 서버가 돌려준 사유(비밀번호 아님)를 남김 — 보호조치/앱비번 안내 URL 등 진단용
            last_reason = str(getattr(e, "args", [""])[0])[:200] if getattr(e, "args", None) else str(e)[:120]
            try:
                imap.logout()
            except Exception:
                pass
            imap = None
    if imap is None:
        # 로그인 실패(네이버 보호조치/비번/앱비번 등) → 통합 수집을 깨지 않게 경고 후 스킵
        print(f"⚠️ IMAP 로그인 실패 → 스킵. 보호조치/IMAP 미설정/비밀번호 확인 필요.")
        print(f"   서버 사유: {last_reason}")
        return

    try:
        raw_folder = find_folder(imap)
        if not raw_folder:
            print(f"⚠️ '{FOLDER_HINT}' 폴더를 못 찾음 → 스킵. (폴더명/라벨 확인)")
            return
        rows, n_total, n_skip = fetch_new(imap, raw_folder, seen)
    finally:
        try:
            imap.logout()
        except Exception:
            pass

    # 상담메일만 남김(지메일 INBOX처럼 다른 메일이 섞일 수 있는 경우 대비):
    #   이름 또는 전화가 파싱된 건만 상담으로 인정. (뉴스레터 등은 이 필드가 없어 제외)
    kept = [r for r in rows if str(r.get("name", "")).strip() or str(r.get("phone", "")).strip()]
    n_drop = len(rows) - len(kept)
    rows = kept
    print(f"[상담메일] 폴더 총 {n_total}통 · 기존 {n_skip} · 신규 {len(rows)}건"
          + (f" (상담 아님 {n_drop}건 제외)" if n_drop else ""))
    if not rows and existing.empty:
        print("  → 신규·기존 모두 없음. 적재 건너뜀"); return

    new_df = pd.DataFrame(rows, columns=COLS)
    final = pd.concat([existing[COLS], new_df[COLS]], ignore_index=True) if not existing.empty else new_df
    final = final.drop_duplicates(subset=["uid"], keep="last").reset_index(drop=True)
    save(client, final)

    # 집계만 출력(개인정보 원문 금지)
    ph = final["phone"].astype(str)
    valid = ph.str.match(r'01[016789]\d{7,8}$')
    print(f"[적재 완료] consult_raw 총 {len(final)}행 · "
          f"유효번호 {int(valid.sum())} · 무효/비정상번호 {int((~valid & (ph != '')).sum())} · "
          f"번호없음 {int((ph == '').sum())}")


if __name__ == "__main__":
    main()
