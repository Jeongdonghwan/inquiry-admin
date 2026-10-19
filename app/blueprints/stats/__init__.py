from flask import Blueprint, render_template, request
from flask_login import current_user

from ...permissions import role_required
from ...services import stats as svc

bp = Blueprint("stats", __name__, template_folder="../../templates")


@bp.get("/stats")
@role_required("admin", "manager")
def stats_view():
    a = request.args
    data = svc.build(current_user, a.get("period", "30"), a.get("from"), a.get("to"))
    return render_template("stats/stats.html", d=data, args=a)
