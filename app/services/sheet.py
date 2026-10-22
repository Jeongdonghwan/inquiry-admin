"""상담지: 양식 매칭·스키마 검증·답변 저장·요약 텍스트 (CLAUDE.md 7-7)."""
import re
import secrets

from .. import now_kst
from ..extensions import db
from ..models import ConsultForm, ConsultSheet, Inquiry, User
from . import inquiry as inq_svc

FIELD_TYPES = ("select", "multi", "radio", "bool", "number", "text", "textarea", "date")
OPTION_TYPES = ("select", "multi", "radio")


class SchemaError(ValueError):
    pass


# ---- 매칭 ----
def active_forms(category: str | None = None) -> list[ConsultForm]:
    q = ConsultForm.query.filter_by(is_active=True)
    if category:
        q = q.filter((ConsultForm.category == category) | (ConsultForm.category.is_(None)))
    return q.order_by(ConsultForm.sort_order, ConsultForm.id).all()


def match_form(inq: Inquiry) -> ConsultForm | None:
    """inquiry_type 부분일치. 가장 긴 키가 맞는 양식 우선."""
    t = inq.inquiry_type or ""
    best, best_len = None, 0
    for f in active_forms(inq.site.category):
        for key in f.inquiry_type_keys or []:
            if key and key in t and len(key) > best_len:
                best, best_len = f, len(key)
    return best


def sheets_of(inq: Inquiry) -> list[ConsultSheet]:
    """문의 1건의 사건별 상담지 (양식마다 1개), 작성 순."""
    return ConsultSheet.query.filter_by(inquiry_id=inq.id, is_current=True).order_by(ConsultSheet.id).all()


def current_sheet(inq: Inquiry, form_id: int | None = None) -> ConsultSheet | None:
    q = ConsultSheet.query.filter_by(inquiry_id=inq.id, is_current=True)
    if form_id:
        q = q.filter_by(form_id=form_id)
    return q.order_by(ConsultSheet.id).first()


# ---- 스키마 ----
def fields_of(schema: dict):
    for sec in schema.get("sections", []):
        for f in sec.get("fields", []):
            yield f


def visible(field: dict, answers: dict) -> bool:
    cond = field.get("show_if")
    if not cond:
        return True
    return answers.get(cond.get("key")) == cond.get("eq")


def required_done(schema: dict, answers: dict) -> bool:
    return not missing_required(schema, answers)


def missing_required(schema: dict, answers: dict) -> list[str]:
    out = []
    for f in fields_of(schema):
        if f.get("required") and visible(f, answers) and answers.get(f["key"]) in (None, "", []):
            out.append(f["label"])
    return out


def sheet_incomplete(inq: Inquiry) -> bool:
    """탭 옆 주황 점용: 현재 상담지가 있고 필수가 비었으면 True."""
    return any(not s.required_done for s in sheets_of(inq))


def validate_schema(schema: dict) -> None:
    if not isinstance(schema, dict) or not isinstance(schema.get("sections"), list) or not schema["sections"]:
        raise SchemaError("sections 배열이 필요합니다")
    keys = set()
    for si, sec in enumerate(schema["sections"], 1):
        if not isinstance(sec, dict) or not sec.get("title"):
            raise SchemaError(f"{si}번째 섹션: 제목이 없습니다")
        sec.setdefault("fields", [])
        for f in sec["fields"]:
            k = f.get("key", "")
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", k or ""):
                raise SchemaError(f"'{f.get('label') or k}': key는 영문 소문자 snake_case")
            ck = (f.get("check") or {}).get("key")
            for kk in filter(None, [k, ck]):
                if kk in keys:
                    raise SchemaError(f"'{f.get('label')}': key '{kk}' 중복")
                keys.add(kk)
            if not f.get("label"):
                raise SchemaError(f"'{k}': 라벨이 없습니다")
            if f.get("type") not in FIELD_TYPES:
                raise SchemaError(f"'{f['label']}': 타입 '{f.get('type')}'은 지원하지 않습니다")
            if f["type"] in OPTION_TYPES and not [o for o in f.get("options") or [] if str(o).strip()]:
                raise SchemaError(f"'{f['label']}': {f['type']}에는 선택지(options)가 필요합니다")
    for f in fields_of(schema):
        cond = f.get("show_if")
        if cond and cond.get("key") not in keys:
            raise SchemaError(f"'{f['label']}': show_if가 없는 key '{cond.get('key')}'를 가리킵니다")


def gen_key(label: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not re.match(r"^[a-z]", base or ""):
        base = "f_" + secrets.token_hex(3)
    k, i = base, 2
    while k in existing:
        k, i = f"{base}_{i}", i + 1
    return k


def coerce_answers(schema: dict, raw: dict) -> dict:
    """타입에 맞게 값 정리. 스키마에 없는 key는 보존(필드 삭제 후에도 답변 유지)."""
    out = dict(raw or {})
    for f in fields_of(schema):
        k, t = f["key"], f["type"]
        v = raw.get(k) if raw else None
        if v in (None, ""):
            out.pop(k, None)
            continue
        if t == "number":
            try:
                out[k] = float(str(v).replace(",", ""))
                if out[k].is_integer():
                    out[k] = int(out[k])
            except ValueError:
                out.pop(k, None)
        elif t == "bool":
            out[k] = v in (True, "true", "1", 1, "on")
        elif t == "multi":
            out[k] = [str(x) for x in (v if isinstance(v, list) else [v])]
        else:
            out[k] = str(v)
    return out


# ---- 저장 ----
def save_answers(inq: Inquiry, user: User, form_id: int, answers: dict) -> ConsultSheet:
    inq_svc._check(user, inq)
    form = db.session.get(ConsultForm, form_id)
    if form is None or not form.is_active:
        raise SchemaError("양식을 찾을 수 없습니다")
    cur = current_sheet(inq, form.id)
    answers = coerce_answers(form.schema_json, answers)
    if cur is None:  # 이 사건(양식)의 상담지 처음 작성 — 다른 사건 상담지는 그대로 둠
        first = not sheets_of(inq)
        cur = ConsultSheet(inquiry_id=inq.id, form_id=form.id, form_version=form.version, answers_json={},
                           created_by=user.id)
        db.session.add(cur)
        inq_svc.log(inq, user, "sheet", f"상담지 {'작성 시작' if first else '추가'}: {form.name}")
    cur.answers_json = answers
    cur.required_done = required_done(form.schema_json, answers)
    cur.updated_by = user.id
    cur.updated_at = now_kst()
    db.session.commit()
    return cur


def summary_text(sheet: ConsultSheet) -> str:
    """채워진 항목만 '라벨: 값' 줄바꿈 텍스트."""
    a = sheet.answers_json or {}
    lines = [f"[{sheet.form.name} 상담지]"]
    for sec in sheet.form.schema_json["sections"]:
        rows = []
        for f in sec.get("fields", []):
            v = a.get(f["key"])
            if v in (None, "", []) or not visible(f, a):
                continue
            ck = f.get("check")
            if f["type"] == "bool":
                v = "예" if v else "아니오"
            elif f["type"] == "multi":
                v = ", ".join(v)
            elif f["type"] == "number":
                v = f"{v:,}{f.get('unit', '')}" if isinstance(v, (int, float)) else v
            if ck and a.get(ck["key"]):
                v = f"{v} ({ck['label']})"
            rows.append(f"- {f['label']}: {v}")
        if rows:
            lines.append(f"\n■ {sec['title']}")
            lines.extend(rows)
    return "\n".join(lines)


# ---- 양식 관리 ----
def save_form(form: ConsultForm | None, user: User, data: dict) -> ConsultForm:
    schema = data["schema"]
    validate_schema(schema)
    if form is None:
        form = ConsultForm(version=0, sort_order=ConsultForm.query.count())
        db.session.add(form)
    else:
        # 저장된 key는 변경 불가: 기존 key가 사라지는 것은 허용(필드 삭제), 같은 label에 다른 key는 빌더에서 막는다
        pass
    form.name = (data.get("name") or "").strip()[:50] or "이름 없는 양식"
    form.category = data.get("category") or None
    form.inquiry_type_keys = [k.strip() for k in (data.get("inquiry_type_keys") or []) if k.strip()]
    form.schema_json = schema
    form.is_active = bool(data.get("is_active", True))
    form.version += 1
    form.updated_by = user.id
    db.session.commit()
    return form


def duplicate_form(form: ConsultForm, user: User) -> ConsultForm:
    copy = ConsultForm(name=f"{form.name} (복사)", category=form.category, inquiry_type_keys=[],
                       schema_json=form.schema_json, version=1, sort_order=ConsultForm.query.count(),
                       is_active=False, updated_by=user.id)
    db.session.add(copy)
    db.session.commit()
    return copy
