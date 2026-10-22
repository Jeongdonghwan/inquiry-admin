import click
from flask import Flask

from .extensions import db


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.argument("login_id")
    @click.argument("password")
    @click.option("--name", default="관리자")
    def create_admin(login_id, password, name):
        """admin 계정 생성 (이미 있으면 비밀번호만 재설정)."""
        from .models import User
        u = User.query.filter_by(login_id=login_id).first() or User(login_id=login_id, name=name, role="admin")
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        click.echo(f"admin 준비됨: {login_id}")

    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="기존 데이터를 지우고 다시 넣는다")
    def seed(reset):
        """개발·시연용 목업 데이터 (11. 목업 데이터). 운영에서는 거부."""
        if app.config.get("ENV") == "production":
            raise click.ClickException("운영 환경(FLASK_ENV=production)에서는 seed를 실행할 수 없습니다.")
        from .seeds.seed_data import run_seed
        run_seed(reset=reset)
        click.echo("seed 완료")

    @app.cli.command("seed-forms")
    def seed_forms():
        """app/seeds/consult_forms/*.json 을 이름 기준으로 추가·갱신 (운영에서도 사용 가능, 답변은 보존)."""
        from .models import ConsultForm
        from .seeds.seed_data import load_forms
        n = 0
        for i, f in enumerate(load_forms()):
            cf = ConsultForm.query.filter_by(name=f["name"]).first()
            if cf is None:
                cf = ConsultForm(name=f["name"], sort_order=i, version=0)
                db.session.add(cf)
            cf.category, cf.inquiry_type_keys, cf.schema_json = f.get("category"), f["inquiry_type_keys"], f["schema"]
            cf.version += 1
            n += 1
        db.session.commit()
        click.echo(f"양식 {n}개 반영")

    @app.cli.command("merge-duplicates")
    def merge_duplicates_cmd():
        """같은 연락처의 기존 문의들을 가장 먼저 접수된 건으로 통합 (기록·문자·상담지 이동)."""
        from .services.merge import merge_duplicates
        click.echo(f"통합 {merge_duplicates()}건")

    @app.cli.command("sms-worker")
    def sms_worker():
        """crontab 1분 주기: 대기·예약 문자 발송."""
        from .services.sms.queue import run_worker
        click.echo(run_worker())

    @app.cli.command("privacy-sweep")
    def privacy_sweep():
        """매일 새벽: 보관기간 지난 종결·계약 건 개인정보 마스킹."""
        from .services.privacy import sweep
        click.echo(f"마스킹 {sweep()}건")
