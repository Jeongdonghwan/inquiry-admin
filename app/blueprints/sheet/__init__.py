"""상담지 탭 조각 + 저장 + 요약 (CLAUDE.md 8)."""
from flask import Blueprint, Response, jsonify, render_template, request
from flask_login import current_user, login_required

from ...extensions import db
from ...models import ConsultForm
from ...permissions import get_inquiry_or_404
from ...services import sheet as svc

bp = Blueprint("sheet", __name__, template_folder="../../templates")


def render_sheet(inq, form_id: int | None = None) -> str:
    """사건별 상담지 탭 + 선택한 양식 1개. 한 사람이 회생·민사·형사를 같이 진행해도 사건마다 따로 작성."""
    sheets = svc.sheets_of(inq)
    if form_id:
        form = db.session.get(ConsultForm, form_id)
    else:
        form = sheets[0].form if sheets else svc.match_form(inq)
    sheet = next((s for s in sheets if form and s.form_id == form.id), None)
    tabs = [s.form for s in sheets]
    for extra in (svc.match_form(inq), form):  # 유입 분야 양식·지금 연 양식은 저장 전이어도 탭으로
        if extra and extra not in tabs:
            tabs.append(extra)
    answers = sheet.answers_json if sheet else {}
    return render_template("inquiries/_sheet.html", inq=inq, form=form, sheet=sheet, answers=answers, tabs=tabs,
                           saved_ids={s.form_id for s in sheets},
                           add_forms=[f for f in svc.active_forms() if f not in tabs],
                           missing=svc.missing_required(form.schema_json, answers) if form else [])


@bp.get("/inquiries/<int:inquiry_id>/sheet")
@login_required
def sheet_view(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    return render_sheet(inq, request.args.get("form_id", type=int))


@bp.post("/inquiries/<int:inquiry_id>/sheet")
@login_required
def sheet_save(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    d = request.get_json(silent=True) or {}
    try:
        s = svc.save_answers(inq, current_user, int(d.get("form_id") or 0), d.get("answers") or {})
    except (svc.SchemaError, ValueError) as e:
        return jsonify(ok=False, error=str(e)), 400
    return jsonify(ok=True, saved_at=s.updated_at.strftime("%H:%M"), required_done=s.required_done,
                   missing=svc.missing_required(s.form.schema_json, s.answers_json))


@bp.get("/inquiries/<int:inquiry_id>/sheet.txt")
@login_required
def sheet_txt(inquiry_id):
    inq = get_inquiry_or_404(current_user, inquiry_id)
    s = svc.current_sheet(inq, request.args.get("form_id", type=int))
    return Response(svc.summary_text(s) if s else "", mimetype="text/plain; charset=utf-8")
