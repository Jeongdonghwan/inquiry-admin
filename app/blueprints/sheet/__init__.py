"""상담지 탭 조각 + 저장 + 요약 (CLAUDE.md 8)."""
from flask import Blueprint, Response, jsonify, render_template, request
from flask_login import current_user, login_required

from ...extensions import db
from ...models import ConsultForm
from ...permissions import get_inquiry_or_404
from ...services import sheet as svc

bp = Blueprint("sheet", __name__, template_folder="../../templates")


def _render(inq, form, sheet):
    answers = sheet.answers_json if sheet else {}
    return render_template("inquiries/_sheet.html", inq=inq, form=form, sheet=sheet, answers=answers,
                           forms=svc.active_forms(inq.site.category),
                           missing=svc.missing_required(form.schema_json, answers) if form else [])


def render_sheet(inq, form_id: int | None = None) -> str:
    sheet = svc.current_sheet(inq)
    form = db.session.get(ConsultForm, form_id) if form_id else (sheet.form if sheet else svc.match_form(inq))
    if form_id and sheet and sheet.form_id != form_id:
        sheet = None
    return _render(inq, form, sheet)


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
    s = svc.current_sheet(inq)
    return Response(svc.summary_text(s) if s else "", mimetype="text/plain; charset=utf-8")
