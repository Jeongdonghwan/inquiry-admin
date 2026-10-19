from flask import Blueprint, render_template
from flask_login import login_required

bp = Blueprint("inquiries", __name__, template_folder="../../templates")


@bp.get("/inquiries")
@login_required
def list_view():
    # Phase 3에서 목록·상세 구현. Phase 1은 레이아웃 확인용 빈 화면.
    return render_template("inquiries/list.html")
