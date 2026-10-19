"""설정 > 상담지 양식 관리 (admin, CLAUDE.md 7-7)."""
import json

from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user

from ...extensions import db
from ...models import CATEGORIES, ConsultForm, ConsultSheet
from ...permissions import role_required
from ...services import sheet as svc
from . import bp


@bp.get("/forms")
@role_required("admin")
def forms():
    rows = ConsultForm.query.order_by(ConsultForm.sort_order, ConsultForm.id).all()
    counts = dict(db.session.query(ConsultSheet.form_id, db.func.count()).group_by(ConsultSheet.form_id).all())
    return render_template("settings/forms.html", rows=rows, counts=counts, cats=CATEGORIES,
                           nfields=lambda f: sum(1 for _ in svc.fields_of(f.schema_json)))


@bp.route("/forms/new", methods=["GET", "POST"])
@bp.route("/forms/<int:fid>", methods=["GET", "POST"])
@role_required("admin")
def form_builder(fid=None):
    form = db.session.get(ConsultForm, fid) if fid else None
    if fid and form is None:
        abort(404)
    if request.method == "POST":
        d = request.get_json(silent=True) or {}
        try:
            form = svc.save_form(form, current_user, d)
        except (svc.SchemaError, KeyError, TypeError) as e:
            return jsonify(ok=False, error=str(e) if not isinstance(e, KeyError) else "schema 가 필요합니다"), 400
        return jsonify(ok=True, id=form.id, version=form.version)
    saved_keys = sorted({f["key"] for f in svc.fields_of(form.schema_json)}) if form else []
    data = {"name": form.name, "category": form.category, "inquiry_type_keys": form.inquiry_type_keys, "schema": form.schema_json,
            "is_active": form.is_active} if form else \
           {"name": "", "category": "legal", "inquiry_type_keys": [], "schema": {"sections": [{"title": "기본 정보", "fields": []}]}, "is_active": True}
    return render_template("settings/form_builder.html", form=form, data=data, saved_keys=saved_keys, cats=CATEGORIES,
                           types=svc.FIELD_TYPES)


@bp.post("/forms/preview")
@role_required("admin")
def form_preview():
    """빌더 실시간 미리보기: 스키마 → 실제 _sheet 렌더 (저장 없음)."""
    d = request.get_json(silent=True) or {}
    schema = d.get("schema") or {"sections": []}
    answers = d.get("answers") or {}

    class _F:  # 템플릿이 기대하는 최소 속성
        id, name, schema_json = 0, d.get("name", ""), schema
    return render_template("settings/_form_preview.html", form=_F, answers=answers)


@bp.post("/forms/<int:fid>/duplicate")
@role_required("admin")
def form_duplicate(fid):
    form = db.session.get(ConsultForm, fid) or abort(404)
    copy = svc.duplicate_form(form, current_user)
    flash(f"복제됨: {copy.name} (사용 안 함 상태)")
    return redirect(url_for("settings.form_builder", fid=copy.id))


@bp.post("/forms/<int:fid>/toggle")
@role_required("admin")
def form_toggle(fid):
    form = db.session.get(ConsultForm, fid) or abort(404)
    form.is_active = not form.is_active
    db.session.commit()
    return redirect(url_for("settings.forms"))
