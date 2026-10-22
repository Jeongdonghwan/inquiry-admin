"""목업 데이터 (CLAUDE.md 11. + design/A_list.dc.html seed()).

날짜는 실행일 기준 상대값(D0=오늘). seed 문자는 provider='seed', status='sent'로만 기록하고 실제 발송하지 않는다.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from ..extensions import db
from ..models import (AccessLog, ConsultForm, ConsultSheet, Inquiry, InquiryLog, Site, SmsMessage,
                      SmsTemplate, User, user_sites)

SEED_PASSWORD = "test1234!"

SITES = [
    ("hs", "회생파산 상담센터", "legal", "#c2410c"),
    ("ih", "이혼·가사 상담", "legal", "#7c3aed"),
    ("ta", "교통사고 보상센터", "legal", "#0369a1"),
    ("hj", "형사 변호 상담", "legal", "#475569"),
    ("nm", "노무 상담센터", "labor", "#b45309"),
    ("in", "인사·징계 대응", "labor", "#15803d"),
]

USERS = [  # login_id, name, title, role, sites(None=전체)
    ("admin", "관리자", None, "admin", None),
    ("yoon", "윤서영", "팀장", "manager", ["hs", "ih", "ta", "hj", "nm", "in"]),
    ("kang", "강민석", "실장", "manager", ["hs", "ih", "ta", "hj", "nm", "in"]),
    ("oh", "오세진", "노무팀", "agent", ["nm", "in"]),
]

TEMPLATES = [  # name, body, category, is_auto_reply
    ("접수확인(자동)", "[{사이트}] {이름}님, 문의가 정상 접수되었습니다. 영업시간 내 순서대로 연락드리겠습니다.", None, True),
    ("부재 안내", "[{사이트}] {이름}님, 문의 주신 건으로 연락드렸으나 통화가 어려워 문자 남깁니다. 편하신 시간을 회신 주시면 맞춰 연락드리겠습니다.", None, False),
    ("일정 확정", "[{사이트}] {이름}님, 요청하신 상담이 {콜백일시}로 예약되었습니다. 변경이 필요하시면 이 번호로 회신 부탁드립니다.", None, False),
    ("준비서류 안내", "[{사이트}] {이름}님, 상담 시 지참하실 서류 안내드립니다.\n- 신분증\n- 소득 증빙\n- 관련 자료(계약서·진단서 등)\n문의: {대표번호}", "legal", False),
    ("진정 서류 안내", "[{사이트}] {이름}님, 노동청 진정·구제신청 시 필요한 서류 안내드립니다.\n- 근로계약서\n- 급여명세서·통장 내역\n- 출퇴근 기록\n- 해고·징계 통지서(있는 경우)\n문의: {대표번호}", "labor", False),
]

AUTO_REPLY = "[접수확인] 문의가 정상 접수되었습니다. 영업시간 내 순서대로 연락드리겠습니다."


def _d(day: int, hm: str) -> datetime:
    """D0 기준 상대 일자 + 'HH:MM'."""
    from .. import now_kst
    h, m = map(int, hm.split(":"))
    base = now_kst().replace(hour=h, minute=m, second=0, microsecond=0)
    return base + timedelta(days=day)


# 문의 12건: (site, type, name, phone, region, (day, time), status, assignee, callback(day,time)|None, kw, device, msg, logs)
# logs: (day, time, kind, user|None, body)
def _inquiries():
    return [
        dict(site="hs", type="개인회생", name="박정훈", phone="01048213307", region="경기 수원시 영통구", at=(0, "19:42"), status="new", who=None, cb=None,
             kw="수원 개인회생 비용", device="mobile",
             msg="카드론 포함 채무가 7,800만원 정도이고 월 실수령 280만원입니다. 개인회생 가능한지, 수임료가 어느 정도인지 궁금합니다.",
             logs=[(0, "19:42", "received", None, "회생파산 상담센터 상담폼으로 접수"), (0, "19:42", "sms", None, AUTO_REPLY)]),
        dict(site="hj", type="형사 · 경찰 출석", name="조민재", phone="01066120954", region="서울 강서구", at=(0, "20:03"), status="new", who=None, cb=None,
             kw="경찰조사 변호사 동행", device="mobile",
             msg="다음 주 화요일 경찰서 출석 요구를 받았습니다. 변호사 동행이 가능한지, 비용은 어떻게 되는지 문의드립니다.",
             logs=[(0, "20:03", "received", None, "형사 변호 상담 상담폼으로 접수"), (0, "20:03", "sms", None, AUTO_REPLY)]),
        dict(site="ih", type="협의이혼 · 재산분할", name="정다은", phone="01022945518", region="서울 송파구", at=(0, "16:20"), status="contacting", who="yoon", cb=(1, "19:00"),
             kw="재산분할 비율 상담", device="pc",
             msg="남편과 협의이혼을 진행 중인데 공동명의 아파트 재산분할 비율 상담을 받고 싶습니다. 퇴근 후 저녁 7시 이후 통화 가능합니다.",
             logs=[(0, "16:20", "received", None, "이혼·가사 상담 상담폼으로 접수"), (0, "16:20", "sms", None, AUTO_REPLY),
                   (0, "16:41", "call_missed", "yoon", "부재중 — 1차 연락 안 됨"),
                   (0, "16:42", "sms", "yoon", "[이혼·가사 상담] 정다은님, 문의 주신 건으로 연락드렸으나 통화가 어려워 문자 남깁니다. 편하신 시간을 회신 주시면 맞춰 연락드리겠습니다."),
                   (0, "17:05", "memo", "yoon", "고객 회신: 내일 저녁 7시 통화 희망 → 콜백 지정")]),
        dict(site="nm", type="임금체불", name="이수진", phone="01077301942", region="경기 화성시 동탄", at=(0, "18:55"), status="new", who=None, cb=None,
             kw="임금체불 노동청 진정", device="pc",
             msg="퇴사한 지 두 달이 됐는데 마지막 두 달치 급여와 퇴직금을 못 받았습니다. 노동청 진정 절차와 변호사 대리 비용이 궁금합니다.",
             logs=[(0, "18:55", "received", None, "노무 상담센터 상담폼으로 접수"), (0, "18:55", "sms", None, AUTO_REPLY)]),
        dict(site="ta", type="보험 합의", name="한재욱", phone="01051638820", region="인천 부평구", at=(0, "11:08"), status="consulted", who="kang", cb=None,
             kw="교통사고 합의금 적정", device="mobile",
             msg="신호대기 중 후방추돌로 2주 입원했습니다. 보험사 합의금 제시액이 적정한지 봐주실 수 있나요?",
             logs=[(0, "11:08", "received", None, "교통사고 보상센터 상담폼으로 접수"), (0, "11:08", "sms", None, AUTO_REPLY),
                   (0, "11:30", "call", "kang", "통화 22분 · 사고 경위 및 치료 경과 확인"),
                   (0, "11:36", "memo", "kang", "진단 4주, 보험사 제시액 확인 필요. 진단서·입퇴원확인서 받기로 함"),
                   (0, "11:38", "status", "kang", "연락중 → 상담완료")]),
        dict(site="in", type="부당해고 · 구제신청", name="서동현", phone="01090154432", region="대전 유성구", at=(-1, "15:47"), status="contacting", who="oh", cb=(0, "21:00"),
             kw="부당해고 구제신청 기간", device="pc",
             msg="3년 근무한 회사에서 지난주 구두로 해고 통보를 받았습니다. 노동위원회 구제신청이 가능한지, 기간이 얼마나 남았는지 궁금합니다.",
             logs=[(-1, "15:47", "received", None, "인사·징계 대응 상담폼으로 접수"), (-1, "15:47", "sms", None, AUTO_REPLY),
                   (-1, "16:10", "call", "oh", "통화 15분 · 해고 통지서 없음, 상시 근로자 12명"),
                   (-1, "16:14", "sms", "oh", "[인사·징계 대응] 서동현님, 구제신청 시 필요한 서류 안내드립니다. 근로계약서, 급여명세서, 출퇴근 기록을 준비해 주세요.")]),
        dict(site="hj", type="형사 · 고소 대응", name="문상현", phone="01030476621", region="경기 성남시 분당구", at=(-1, "10:12"), status="hold", who="kang", cb=(3, "14:00"),
             kw="고소당했을때 대응", device="mobile",
             msg="지인과의 금전 문제로 고소장이 접수됐다는 연락을 받았습니다. 대응 방법 상담 원합니다.",
             logs=[(-1, "10:12", "received", None, "형사 변호 상담 상담폼으로 접수"),
                   (-1, "11:00", "call", "kang", "통화 18분 · 사건 개요 청취"),
                   (-1, "11:05", "status", "kang", "연락중 → 보류"),
                   (-1, "11:06", "memo", "kang", "본인이 자료 정리 후 다시 연락 주기로 함. 재연락 예정")]),
        dict(site="hs", type="개인파산", name="김영자", phone="01033802716", region="경기 수원시 권선구", at=(-1, "21:30"), status="contracted", who="kang", cb=None,
             kw="개인파산 신청 자격", device="mobile",
             msg="나이가 많아 일을 할 수 없는 상황입니다. 파산 신청이 가능한지 알고 싶습니다.",
             logs=[(-1, "21:30", "received", None, "회생파산 상담센터 상담폼으로 접수"),
                   (0, "09:40", "call", "kang", "방문 상담 일정 확정"),
                   (0, "15:10", "memo", "kang", "방문 상담 완료 · 수임 계약서 작성"),
                   (0, "15:12", "status", "kang", "상담완료 → 계약")]),
        dict(site="nm", type="직장 내 괴롭힘", name="유지호", phone="01088721406", region="충남 천안시", at=(-2, "13:30"), status="closed", who="oh", cb=None,
             kw="직장내 괴롭힘 신고", device="mobile", close_reason="비용 불일치",
             msg="팀장의 지속적인 폭언으로 병원 진단을 받았습니다. 회사에 신고했지만 조치가 없습니다.",
             logs=[(-2, "13:30", "received", None, "노무 상담센터 상담폼으로 접수"),
                   (-2, "15:00", "call", "oh", "통화 10분 · 사내 신고 후 미조치, 녹취 보유"),
                   (-2, "15:03", "status", "oh", "연락중 → 종결 (사유: 비용 불일치)")]),
        dict(site="ih", type="양육권 · 양육비", name="임가영", phone="01044192083", region="경기 고양시 일산동구", at=(-2, "09:50"), status="consulted", who="yoon", cb=None,
             kw="양육비 이행 청구", device="pc",
             msg="이혼 후 양육비를 1년째 받지 못하고 있습니다. 이행 청구 절차가 궁금합니다.",
             logs=[(-2, "09:50", "received", None, "이혼·가사 상담 상담폼으로 접수"),
                   (-2, "10:30", "call", "yoon", "통화 30분 · 이행명령 절차 안내"),
                   (-2, "10:35", "status", "yoon", "연락중 → 상담완료")]),
        dict(site="hs", type="개인회생", name="박정훈", phone="01048213307", region="경기 수원시 영통구", at=(-1, "19:05"), status="contacting", who="kang", cb=(0, "20:30"),
             kw="개인회생 조건", device="mobile",
             msg="개인회생 상담 받고 싶습니다. 저녁에 통화 가능합니다.",
             logs=[(-1, "19:05", "received", None, "회생파산 상담센터 상담폼으로 접수"), (-1, "19:05", "sms", None, AUTO_REPLY),
                   (0, "10:20", "call_missed", "kang", "부재중 — 1차 연락 안 됨"),
                   (0, "10:21", "sms", "kang", "[회생파산 상담센터] 박정훈님, 문의 주신 건으로 연락드렸으나 통화가 어려워 문자 남깁니다.")]),
        dict(site="in", type="징계 · 인사위원회 대응", name="황보름", phone="01025087731", region="부산 해운대구", at=(-4, "14:22"), status="contracted", who="oh", cb=None,
             kw="징계위원회 변호사 동석", device="pc",
             msg="다음 주 인사위원회에 출석하라는 통지를 받았습니다. 소명서 작성과 동석을 부탁드리고 싶습니다.",
             logs=[(-4, "14:22", "received", None, "인사·징계 대응 상담폼으로 접수"),
                   (-3, "11:00", "memo", "oh", "방문 상담 완료 · 징계 사유서 검토"),
                   (-1, "16:00", "status", "oh", "상담완료 → 계약 (소명서 작성·동석 수임)")]),
    ]


# 상담지 답변 예시: 문의 번호(1-based) → (양식 파일 stem, answers)
SHEETS = {
    1: ("01_rehab", {"ad_media": "홈페이지", "summary": "카드론 포함 7,800만원, 급여소득자. 회생 적합 검토", "case_kind": "개인회생", "age": 41,
                     "address": "경기 수원시 영통구", "married": "기혼", "minor_children": 2, "housing": "전세", "housing_deposit": 3000,
                     "has_car": False, "job": "회사원", "monthly_income": 280, "tenure": "6년", "total_debt": 7800, "creditor_count": 5,
                     "overdue": "2026년 6월부터 연체", "seizure": "카드사 지급명령 1건", "debt_cause": "생활비·자녀 교육비"}),
    5: ("05_traffic", {"side": "피해자", "accident_date": None, "fault_ratio": 0, "injury": "경상 염좌", "diagnosis_weeks": 4,
                       "treatment": "입원", "hospital_days": 14, "insurer_offer": 350, "insurer_contacted": True,
                       "docs": ["진단서", "입퇴원확인서"]}),
    6: ("06_labor", {"side": "근로자", "issue": "부당해고", "employment": "해고 통보", "tenure_months": 36, "company_size": "5~30인",
                     "dismissal_date": None, "proceeding": "없음", "evidence": ["문자·카톡", "급여명세서"], "requests": ["구제신청", "합의 교섭"]}),
    7: ("02_criminal", {"side": "피의자", "charge": "사기", "stage": "경찰 조사", "detained": False, "settlement": "미시도",
                        "priors": "없음", "evidence": ["문자·카톡", "송금내역"], "requests": ["조사 동행", "의견서"]}),
}


def load_forms() -> list[dict]:
    """consult_forms/*.json (_로 시작하는 파일 제외). 각 양식 앞에 _common.json 공통 섹션을 붙인다."""
    folder = Path(__file__).with_name("consult_forms")
    common = json.loads((folder / "_common.json").read_text(encoding="utf-8"))["sections"]
    out = []
    for p in sorted(folder.glob("[!_]*.json")):
        f = json.loads(p.read_text(encoding="utf-8")) | {"_stem": p.stem}
        if f.get("common", True):
            f["schema"] = {"sections": json.loads(json.dumps(common)) + f["schema"]["sections"]}
        out.append(f)
    return out


def _required_done(schema: dict, answers: dict) -> bool:
    for sec in schema["sections"]:
        for f in sec["fields"]:
            if f.get("required") and answers.get(f["key"]) in (None, "", []):
                return False
    return True


def run_seed(reset: bool = False) -> None:
    if reset:
        for model in (AccessLog, ConsultSheet, SmsMessage, InquiryLog, Inquiry, SmsTemplate, ConsultForm):
            db.session.query(model).delete()
        db.session.execute(user_sites.delete())
        db.session.query(User).delete()
        db.session.query(Site).delete()
        db.session.commit()
    if Site.query.first():
        raise RuntimeError("이미 데이터가 있습니다. --reset 으로 다시 넣으세요.")

    sites = {}
    for code, name, cat, color in SITES:
        s = Site(code=code, name=name, category=cat, color=color, sender_number="0200000000")
        s.issue_secret(); s.issue_public()
        db.session.add(s); sites[code] = s
    db.session.flush()

    users = {}
    for login_id, name, title, role, codes in USERS:
        u = User(login_id=login_id, name=name, title=title, role=role)
        u.set_password(SEED_PASSWORD)
        if codes:
            u.sites = [sites[c] for c in codes]
        db.session.add(u); users[login_id] = u
    db.session.flush()

    for i, (name, body, cat, auto) in enumerate(TEMPLATES):
        db.session.add(SmsTemplate(name=name, body=body, category=cat, is_auto_reply=auto, sort_order=i))

    forms = {}
    for i, f in enumerate(load_forms()):
        cf = ConsultForm(name=f["name"], category=f.get("category"), inquiry_type_keys=f["inquiry_type_keys"],
                         schema_json=f["schema"], sort_order=i)
        db.session.add(cf); forms[f["_stem"]] = cf
    db.session.flush()

    by_phone: dict[str, Inquiry] = {}
    created: list[Inquiry] = []
    for row in _inquiries():
        site = sites[row["site"]]
        inq = Inquiry(site=site, status=row["status"], assignee=users[row["who"]] if row["who"] else None,
                      customer_name=row["name"], phone=row["phone"], region=row["region"], inquiry_type=row["type"],
                      message=row["msg"], utm_source="naver", utm_medium="cpc", utm_term=row["kw"], device=row["device"],
                      privacy_agreed=True, received_at=_d(*row["at"]),
                      callback_at=_d(*row["cb"]) if row["cb"] else None, close_reason=row.get("close_reason"))
        db.session.add(inq); db.session.flush()
        for day, hm, kind, who, body in row["logs"]:
            db.session.add(InquiryLog(inquiry_id=inq.id, kind=kind, user_id=users[who].id if who else None,
                                      body=body, created_at=_d(day, hm)))
            if kind == "sms":
                db.session.add(SmsMessage(inquiry_id=inq.id, site_id=site.id, user_id=users[who].id if who else None,
                                          to_phone=inq.phone, from_phone=site.sender_number, body=body,
                                          msg_type="LMS" if len(body.encode("cp949", "replace")) > 90 else "SMS",
                                          byte_len=len(body.encode("cp949", "replace")), status="sent", is_auto=who is None,
                                          provider="seed", sent_at=_d(day, hm), created_at=_d(day, hm)))
        if inq.status != "new":
            inq.first_contact_at = inq.received_at + timedelta(minutes=20)
        if inq.status == "contracted":
            inq.contracted_at = _d(*row["logs"][-1][:2])
        if inq.status == "closed":
            inq.closed_at = _d(*row["logs"][-1][:2])
        created.append(inq)

    # 중복 판정: 같은 번호의 직전 문의 (#1 ↔ #11)
    for inq in sorted(created, key=lambda x: x.received_at):
        prev = by_phone.get(inq.phone)
        if prev:
            inq.duplicate_of_id = prev.id
        by_phone[inq.phone] = inq

    for no, (stem, answers) in SHEETS.items():
        inq, form = created[no - 1], forms[stem]
        db.session.add(ConsultSheet(inquiry_id=inq.id, form_id=form.id, form_version=form.version, answers_json=answers,
                                    required_done=_required_done(form.schema_json, answers),
                                    created_by=inq.assignee_id, updated_by=inq.assignee_id))
        db.session.add(InquiryLog(inquiry_id=inq.id, kind="sheet", user_id=inq.assignee_id,
                                  body=f"상담지 작성 시작: {form.name}", created_at=inq.received_at + timedelta(minutes=25)))
    db.session.commit()
    from ..services.merge import merge_duplicates
    merge_duplicates()  # 같은 연락처 = 문의 1건
