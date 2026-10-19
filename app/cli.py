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
