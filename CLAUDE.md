# CLAUDE.md — 통합 상담 어드민 (Inquiry Admin)

> 여러 홈페이지(법률사무소·프랜차이즈 가맹 사이트 등)에서 들어온 고객 문의를 **하나의 DB로 모아**
> 상담 상태 관리, 담당자 배정, 상담 기록, 문자 발송까지 처리하는 관리자 웹앱.
>
> **작업 방식:** 아래 Phase를 **한 번에 하나씩** 진행한다. 각 Phase가 끝나면 "완료 기준"을 모두 확인하고,
> 결과를 요약한 뒤 멈춰서 다음 지시를 기다린다. 다음 Phase를 임의로 시작하지 않는다.

---

## 0. 한 줄 요약

- **들어오는 쪽:** 각 홈페이지 상담폼 → `POST /api/v1/inquiries` (사이트별 키로 인증) → `inquiries` 테이블에 저장 → 접수확인 문자 자동 발송(큐)
- **보는 쪽:** 직원이 로그인 → 목록 화면(A안) 또는 보드 화면(B안)에서 문의를 처리 → 모든 행동이 `inquiry_logs`에 시간순으로 남음

---

## 1. 기술 스택 (고정)

| 구분 | 사용 |
|---|---|
| 서버 | Python 3.11+, **Flask** (앱 팩토리 + Blueprint) |
| 화면 | **Jinja2 SSR** + 바닐라 JS(`fetch`)로 부분 갱신. 프론트 빌드 도구 쓰지 않음 |
| DB | **MariaDB 10.6+**, SQLAlchemy 2.x + Flask-Migrate(Alembic) |
| 인증 | Flask-Login(세션), 비밀번호는 `werkzeug.security` 해시, Flask-WTF CSRF |
| 제한 | Flask-Limiter (접수 API 속도 제한) |
| 엑셀 | openpyxl |
| 문자 | 발송사 어댑터 구조 (기본: **알리고**, 교체 가능: 솔라피 등) |
| 배포 | Cafe24 가상서버, gunicorn + nginx, 문자 큐는 **crontab 1분 주기 CLI**로 처리 (Celery/Redis 쓰지 않음) |
| 테스트 | pytest (+ 테스트용 SQLite 또는 별도 MariaDB 스키마) |

추가 패키지가 꼭 필요하면 이유를 먼저 말하고 쓴다.

---

## 2. 폴더 구조

```
inquiry-admin/
├─ CLAUDE.md
├─ .env.example
├─ requirements.txt
├─ wsgi.py
├─ app/
│  ├─ __init__.py          # create_app()
│  ├─ config.py
│  ├─ extensions.py        # db, migrate, login_manager, csrf, limiter
│  ├─ models/              # site.py, user.py, inquiry.py, log.py, sms.py, template.py, access_log.py
│  ├─ services/
│  │  ├─ intake.py         # 접수 처리(정규화·중복판정·자동문자 큐 등록)
│  │  ├─ inquiry.py        # 상태변경·배정·콜백·기록 (모든 변경은 여기서 + 로그 기록)
│  │  ├─ sms/
│  │  │  ├─ base.py        # SmsProvider 인터페이스
│  │  │  ├─ aligo.py
│  │  │  ├─ dummy.py       # 개발/테스트용 (실제 발송 안 함)
│  │  │  └─ queue.py       # 큐 적재·발송 워커
│  │  ├─ sheet.py          # 상담지: 양식 매칭·스키마 검증·답변 저장·요약 텍스트
│  │  ├─ template.py       # 변수 치환, 바이트 계산
│  │  ├─ privacy.py        # 마스킹, 보관기간 처리
│  │  └─ stats.py
│  ├─ blueprints/
│  │  ├─ auth/             # 로그인/로그아웃
│  │  ├─ api/              # /api/v1/inquiries (외부 사이트용)
│  │  ├─ inquiries/        # 목록(A), 보드(B), 상세, 액션
│  │  ├─ sms/              # 발송내역
│  │  ├─ settings/         # 사이트, 템플릿, 직원
│  │  └─ stats/
│  ├─ templates/
│  │  ├─ base.html         # 사이드바 레이아웃
│  │  ├─ inquiries/list.html, _detail.html, _row.html, _log_item.html, _sheet.html, _sheet_field.html
│  │  ├─ settings/forms.html, form_builder.html
│  │  └─ ...
│  ├─ seeds/consult_forms/   # 기본 상담지 양식 JSON 6개 (개인회생·형사·민사·가사·교통사고·가맹)
│  ├─ static/css/app.css, static/js/app.js
│  └─ cli.py               # flask seed / flask sms-worker / flask privacy-sweep / flask create-admin
├─ migrations/
└─ tests/
```

---

## 3. 핵심 용어와 상태값

### 3-1. 상담 상태 (`inquiries.status`)

| 코드 | 화면 표시 | 의미 | 색 (배경 / 글자) |
|---|---|---|---|
| `new` | 신규 | 접수 후 아직 아무도 연락 안 함 | `#fde6d6` / `#9a3400` |
| `contacting` | 연락중 | 연락 시도 중 (부재 포함) | `#e1e9fc` / `#1a43ad` |
| `consulted` | 상담완료 | 상담은 했고 결정 대기 | `#d9efe8` / `#0b5a4c` |
| `contracted` | 계약 | 법률=수임, 프랜차이즈=가맹계약 | `#1c2230` / `#ffffff` |
| `hold` | 보류 | 고객 사정으로 대기 (재연락 날짜 지정 권장) | `#e9eaed` / `#40454f` |
| `closed` | 종결 | 끝남. **종결 사유 필수** | `#f1f1f1` / `#666a72` + 취소선 |

- 상태는 어느 방향으로든 바꿀 수 있다 (순서 강제 없음).
- `closed`로 바꿀 때는 사유를 고르게 한다: `부재 지속` / `비용 불일치` / `타사 선택` / `상담 불가 사건` / `허위·스팸` / `기타(직접 입력)`.
- `contracted`로 바뀌면 `contracted_at` 기록, 처음으로 `new`가 아닌 상태가 되면 `first_contact_at` 기록 (응답속도 통계용).

### 3-2. 업종 (`sites.category`)
- `legal`(법률), `franchise`(프랜차이즈). 화면 필터와 문자 템플릿 분류에 쓴다. 나중에 업종이 늘 수 있으니 ENUM 대신 **VARCHAR(20)** + 코드 상수로 관리.

### 3-3. 권한 (`users.role`)

| 역할 | 할 수 있는 것 |
|---|---|
| `admin` | 전부. 사이트·직원·템플릿 관리, 엑셀 내려받기, 통계 |
| `manager` | 담당 사이트의 모든 문의 보기·배정·처리, 통계 보기 |
| `agent` | 담당 사이트 문의 중 **본인 배정 건 + 미배정 건**만 보기·처리. 배정은 "나에게 배정"만 가능 |

담당 사이트는 `user_sites`로 연결. admin은 전체 사이트.

---

## 4. DB 설계 (MariaDB, utf8mb4)

모든 테이블: `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`. 시간은 **KST 기준 DATETIME**으로 저장 (서버·DB 타임존 Asia/Seoul로 통일).

```sql
CREATE TABLE sites (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  code            VARCHAR(30)  NOT NULL UNIQUE,      -- 'hs', 'cb' 등 짧은 코드
  name            VARCHAR(100) NOT NULL,             -- 화면 표시명 '회생파산 상담센터'
  category        VARCHAR(20)  NOT NULL,             -- legal | franchise
  color           CHAR(7)      NOT NULL DEFAULT '#475569',
  domain          VARCHAR(255) NULL,                 -- 'example.co.kr' (CORS 허용 Origin 판단)
  allowed_origins TEXT NULL,                         -- 줄바꿈 구분, 브라우저 직접 전송 허용 Origin
  secret_key_hash VARCHAR(255) NOT NULL,             -- 서버→서버 전송용 비밀키 (해시만 저장)
  public_key      VARCHAR(64)  NOT NULL UNIQUE,      -- 브라우저 전송용 공개키 (Origin 검사와 함께 사용)
  sender_number   VARCHAR(20)  NULL,                 -- 사이트별 발신번호(사전 등록된 번호). 없으면 기본값
  auto_reply      TINYINT(1)   NOT NULL DEFAULT 1,   -- 접수확인 자동문자 여부
  auto_reply_template_id INT NULL,
  retention_days  INT NOT NULL DEFAULT 365,          -- 종결/계약 후 개인정보 보관 일수
  is_active       TINYINT(1) NOT NULL DEFAULT 1,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  login_id      VARCHAR(50)  NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  name          VARCHAR(50)  NOT NULL,              -- '윤서영'
  title         VARCHAR(30)  NULL,                  -- '팀장'
  role          VARCHAR(20)  NOT NULL DEFAULT 'agent',
  phone         VARCHAR(20)  NULL,
  is_active     TINYINT(1)   NOT NULL DEFAULT 1,
  last_login_at DATETIME NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_sites (
  user_id INT NOT NULL, site_id INT NOT NULL,
  PRIMARY KEY (user_id, site_id),
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY (site_id) REFERENCES sites(id) ON DELETE CASCADE
);

CREATE TABLE inquiries (
  id               BIGINT AUTO_INCREMENT PRIMARY KEY,
  site_id          INT NOT NULL,
  status           VARCHAR(20) NOT NULL DEFAULT 'new',
  assignee_id      INT NULL,
  customer_name    VARCHAR(50)  NOT NULL,
  phone            VARCHAR(20)  NOT NULL,           -- 숫자만 저장 '01048213307'
  region           VARCHAR(100) NULL,
  inquiry_type     VARCHAR(100) NULL,               -- '개인회생', '가맹 창업' 등 (폼에서 받은 값)
  message          TEXT NULL,
  extra_json       JSON NULL,                       -- 폼의 기타 필드 그대로 보관
  utm_source       VARCHAR(100) NULL,
  utm_medium       VARCHAR(100) NULL,
  utm_campaign     VARCHAR(150) NULL,
  utm_term         VARCHAR(200) NULL,               -- 화면의 '유입 키워드'
  referrer         VARCHAR(500) NULL,
  landing_url      VARCHAR(500) NULL,
  device           VARCHAR(10)  NULL,               -- mobile | pc | tablet (User-Agent로 판정)
  ip               VARCHAR(45)  NULL,
  user_agent       VARCHAR(500) NULL,
  privacy_agreed   TINYINT(1) NOT NULL DEFAULT 0,
  duplicate_of_id  BIGINT NULL,                     -- 같은 번호의 직전 문의
  callback_at      DATETIME NULL,
  close_reason     VARCHAR(100) NULL,
  received_at      DATETIME NOT NULL,
  first_contact_at DATETIME NULL,
  contracted_at    DATETIME NULL,
  closed_at        DATETIME NULL,
  is_masked        TINYINT(1) NOT NULL DEFAULT 0,
  updated_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (site_id) REFERENCES sites(id),
  FOREIGN KEY (assignee_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_status_received (status, received_at),
  INDEX idx_site_received (site_id, received_at),
  INDEX idx_phone (phone),
  INDEX idx_assignee (assignee_id),
  INDEX idx_callback (callback_at)
);

CREATE TABLE inquiry_logs (
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  inquiry_id  BIGINT NOT NULL,
  kind        VARCHAR(20) NOT NULL,   -- received | call | call_missed | memo | sms | status | assign | callback | system
  user_id     INT NULL,               -- NULL = 시스템/자동
  body        TEXT NULL,              -- 화면에 그대로 보여줄 문장
  meta_json   JSON NULL,              -- {"from":"new","to":"contacting"}, {"sms_id":12} 등
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (inquiry_id) REFERENCES inquiries(id) ON DELETE CASCADE,
  INDEX idx_inquiry_created (inquiry_id, created_at)
);

CREATE TABLE sms_templates (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  site_id    INT NULL,                -- NULL = 전체 공통
  category   VARCHAR(20) NULL,        -- NULL = 전 업종, legal/franchise = 해당 업종만
  name       VARCHAR(50) NOT NULL,    -- '부재 안내'
  body       TEXT NOT NULL,
  is_auto_reply TINYINT(1) NOT NULL DEFAULT 0,
  sort_order INT NOT NULL DEFAULT 0,
  is_active  TINYINT(1) NOT NULL DEFAULT 1
);

CREATE TABLE sms_messages (
  id              BIGINT AUTO_INCREMENT PRIMARY KEY,
  inquiry_id      BIGINT NULL,
  site_id         INT NOT NULL,
  user_id         INT NULL,            -- NULL = 자동발송
  to_phone        VARCHAR(20) NOT NULL,
  from_phone      VARCHAR(20) NOT NULL,
  body            TEXT NOT NULL,
  msg_type        VARCHAR(5) NOT NULL, -- SMS | LMS
  byte_len        INT NOT NULL,
  status          VARCHAR(12) NOT NULL DEFAULT 'queued',  -- queued | scheduled | sending | sent | failed | canceled
  is_auto         TINYINT(1) NOT NULL DEFAULT 0,
  scheduled_at    DATETIME NULL,
  provider        VARCHAR(20) NULL,
  provider_msg_id VARCHAR(100) NULL,
  error           VARCHAR(500) NULL,
  attempts        INT NOT NULL DEFAULT 0,
  sent_at         DATETIME NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_status_sched (status, scheduled_at),
  INDEX idx_inquiry (inquiry_id)
);

CREATE TABLE consult_forms (          -- 사건 유형별 상담지 양식 (7-7)
  id                INT AUTO_INCREMENT PRIMARY KEY,
  name              VARCHAR(50)  NOT NULL,          -- '개인회생·파산'
  category          VARCHAR(20)  NULL,              -- legal | franchise | NULL(공통)
  inquiry_type_keys JSON NOT NULL,                  -- ["개인회생","개인파산","회생","파산"] 부분일치 매칭
  schema_json       JSON NOT NULL,                  -- {"sections":[{"title","fields":[...]}]}
  version           INT NOT NULL DEFAULT 1,         -- 저장할 때마다 +1
  sort_order        INT NOT NULL DEFAULT 0,
  is_active         TINYINT(1) NOT NULL DEFAULT 1,
  updated_by        INT NULL,
  updated_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

CREATE TABLE consult_sheets (         -- 문의 1건의 상담지 답변
  id            BIGINT AUTO_INCREMENT PRIMARY KEY,
  inquiry_id    BIGINT NOT NULL,
  form_id       INT NOT NULL,
  form_version  INT NOT NULL,                       -- 작성 당시 양식 버전
  answers_json  JSON NOT NULL,                      -- {"total_debt": 7800, "debt_kinds": ["카드론", ...]}
  is_current    TINYINT(1) NOT NULL DEFAULT 1,      -- 양식을 바꾸면 이전 sheet는 0
  required_done TINYINT(1) NOT NULL DEFAULT 0,      -- 필수 항목 모두 채워졌는지 (저장 시 계산)
  created_by    INT NULL,
  updated_by    INT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (inquiry_id) REFERENCES inquiries(id) ON DELETE CASCADE,
  FOREIGN KEY (form_id) REFERENCES consult_forms(id),
  INDEX idx_inquiry_current (inquiry_id, is_current)
);

CREATE TABLE access_logs (            -- 개인정보 조회·다운로드 이력
  id          BIGINT AUTO_INCREMENT PRIMARY KEY,
  user_id     INT NOT NULL,
  action      VARCHAR(30) NOT NULL,   -- view_detail | export_excel | reveal_phone
  inquiry_id  BIGINT NULL,
  detail      VARCHAR(255) NULL,      -- 엑셀이면 필터 조건·건수
  ip          VARCHAR(45) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_user_created (user_id, created_at)
);
```

> 실제 생성은 SQLAlchemy 모델 + Flask-Migrate로 하고, 위 SQL은 기준 문서로 쓴다.

---

## 5. 문의 접수 API (외부 사이트 → 어드민)

### 5-1. 엔드포인트

`POST /api/v1/inquiries` — JSON 또는 `application/x-www-form-urlencoded` 둘 다 받는다.

**인증 (둘 중 하나):**
1. **서버→서버 (권장):** 헤더 `X-Site-Key: <secret>` → `sites.secret_key_hash`와 비교. 사이트가 Flask 등 서버를 가진 경우.
2. **브라우저 직접 전송:** 바디의 `site_key=<public_key>` + 요청 `Origin`이 `sites.allowed_origins`에 있어야 통과. CORS 응답 헤더도 이 목록 기준으로만 내려준다.

**받는 필드:**

| 필드 | 필수 | 비고 |
|---|---|---|
| `name` | ✔ | 1~50자 |
| `phone` | ✔ | 숫자만 남겨 `^01[016789]\d{7,8}$` 검사 |
| `privacy_agreed` | ✔ | `1`/`true`가 아니면 400 |
| `inquiry_type` | | 예: 개인회생, 가맹 창업 |
| `region` | | |
| `message` | | 최대 3,000자 |
| `utm_source` `utm_medium` `utm_campaign` `utm_term` | | 폼 페이지에서 URL 파라미터를 hidden으로 넘김 |
| `referrer` `landing_url` | | |
| `website` | | **허니팟.** 값이 있으면 저장하지 않고 200 반환(스팸봇에 티 안 냄) |
| 그 외 필드 | | `extra_json`에 그대로 저장 |

**응답:** `201 {"ok": true, "id": 123}` / 검증 실패 `400 {"ok": false, "error": "phone_invalid"}` / 인증 실패 `401`.

**속도 제한:** IP당 분당 5회, 같은 번호+사이트 10분 내 재접수는 저장은 하되 자동문자는 생략.

### 5-2. 접수 처리 순서 (`services/intake.py`)

1. 인증 → 검증 → 정규화 (번호 숫자만, 이름 앞뒤 공백 제거)
2. `device`를 User-Agent로 판정
3. **중복 판정:** 같은 `phone`의 최근 30일 내 문의(사이트 무관)가 있으면 가장 최근 건 id를 `duplicate_of_id`에 넣는다. 막지는 않는다.
4. `inquiries` 저장 (`status='new'`, `received_at=now`)
5. `inquiry_logs`에 `received` 기록: "{사이트명} 상담폼으로 접수"
6. 사이트 `auto_reply=1`이면 접수확인 템플릿으로 `sms_messages`에 `queued` 등록(`is_auto=1`) + 로그 `sms`
7. 트랜잭션 커밋 후 201 응답 (문자 실제 발송은 워커가 함 → 응답 지연 없음)

### 5-3. 사이트 연동 예시 (설정 > 사이트 화면에 복사 가능하게 보여줄 것)

- **Flask 사이트에서 서버→서버:** `requests.post(ADMIN_URL + "/api/v1/inquiries", json=payload, headers={"X-Site-Key": SECRET}, timeout=5)` — 실패해도 사이트 쪽 폼은 "접수되었습니다"를 보여주고, 사이트 DB/로그에 백업 저장.
- **정적 사이트/빌더 사이트:** `<form>` + `fetch` 스니펫 (public_key 사용, utm 값을 `URLSearchParams(location.search)`에서 채움, 허니팟 input은 CSS로 숨김).

---

## 6. 문자 발송

### 6-1. 구조
- `SmsProvider` 인터페이스: `send(to, from_, body, msg_type, title=None) -> (ok, provider_msg_id, error)`
- 구현: `AligoProvider`(기본), `DummyProvider`(개발·테스트, 로그만 남기고 성공 처리). `.env`의 `SMS_PROVIDER`로 선택.
- **알리고 API 파라미터와 테스트모드(`testmode_yn`)는 구현 시점에 공식 문서로 다시 확인**하고, 개발 중에는 반드시 Dummy 또는 테스트모드로 돌린다.

### 6-2. 큐와 워커
- 화면에서 "지금 보내기" → `sms_messages`에 `queued`로 넣고 **즉시 한 번 발송 시도** (요청 안에서, 타임아웃 5초). 실패하면 `queued` 유지.
- "예약 발송" → `scheduled` + `scheduled_at`.
- `flask sms-worker` (crontab 1분마다): `queued` 전부 + `scheduled_at <= now`인 `scheduled`를 가져와 발송. 행 잠금(`SELECT ... FOR UPDATE SKIP LOCKED`) 또는 `status='sending'` 선점으로 중복 발송 방지. 3회 실패하면 `failed`.
- 발송 결과는 문의의 상담 기록에도 반영 (실패 시 "문자 발송 실패: 사유" 로그 추가).

### 6-3. 길이 계산과 템플릿
- 바이트 = `len(body.encode('cp949', errors='replace'))` (한글 2바이트). **90바이트 이하 SMS, 초과 LMS** (LMS 최대 2,000바이트, 초과 시 발송 막음).
- 화면에서도 같은 규칙으로 실시간 표시 (JS: 코드값 127 초과 = 2바이트).
- 템플릿 변수: `{이름}` `{사이트}` `{담당자}` `{대표번호}` `{콜백일시}`. 치환 안 된 `{...}`가 남아 있으면 발송 전 경고.
- 기본 템플릿 (seed):
  - 공통 **접수확인(자동)**: `[{사이트}] {이름}님, 문의가 정상 접수되었습니다. 영업시간 내 순서대로 연락드리겠습니다.`
  - 공통 **부재 안내**: `[{사이트}] {이름}님, 문의 주신 건으로 연락드렸으나 통화가 어려워 문자 남깁니다. 편하신 시간을 회신 주시면 맞춰 연락드리겠습니다.`
  - 공통 **일정 확정**: `[{사이트}] {이름}님, 요청하신 상담이 {콜백일시}로 예약되었습니다. 변경이 필요하시면 이 번호로 회신 부탁드립니다.`
  - 법률 **준비서류 안내**, 프랜차이즈 **창업 안내서** (디자인 시안 문구 참고)

### 6-4. 지켜야 할 것
- 발신번호는 발송사에 **사전 등록된 번호만** 사용 (`sites.sender_number` 또는 기본값). 등록 안 된 번호는 설정 화면에서 저장 시 경고.
- 이 시스템의 문자는 **고객이 요청한 상담에 대한 안내(정보성)**에 한정. 광고성 문구 템플릿은 만들지 않는다. (광고성 발송 기능은 범위 밖 — 필요해지면 수신동의·야간 발송 제한 등을 별도 설계)

---

## 7. 화면 설계

디자인 시안: `design/A_list.dc.html`(A안 업무형 3단), `design/B_board.dc.html`(B안 파이프라인 보드). 시안 전용 런타임 형식이라 그대로 실행되지 않으니 **배치·색·문구·간격을 읽어서 Jinja2 템플릿으로 옮긴다** (`<sc-for>`=반복, `<sc-if>`=조건, 하단 스크립트의 `seed()`=목업 데이터).
**결정: A안으로 간다.** 앱 전체 틀(사이드바·색·글꼴)과 문의 처리 화면은 A안 그대로 구현한다. B안(보드)은 **Phase 7 선택 사항**으로 미루며, 지시가 있을 때만 만든다.
상담지(사건 유형별 양식) 화면 시안: `design/C_sheet.dc.html` — 상세 패널의 「상담지」 탭 모습.

### 7-1. 디자인 기준값 (`static/css/app.css`의 CSS 변수)

```css
:root{
  --bg:#eef0f3; --panel:#ffffff; --line:#dde0e6; --line-soft:#eceef1;
  --text:#1b1f27; --muted:#5d6575; --sidebar:#1c2230; --sidebar-active:#2c3445; --sidebar-text:#c9cfdb;
  --primary:#1f4fc4; --primary-dark:#163a91; --accent:#e8590c; --selected:#e7eefc;
  --radius:4px;
  --font:'IBM Plex Sans KR',sans-serif; --mono:'IBM Plex Mono',monospace;
}
```

- 글꼴: Google Fonts `IBM Plex Sans KR`(400/500/600/700), 숫자·시간·전화번호는 `IBM Plex Mono`.
- 모서리 4px, 그림자 없음, 그라데이션·이모지 없음, 아이콘은 꼭 필요한 곳만(검색·전화·문자·닫기) 선 아이콘 인라인 SVG.
- 사이트 구분은 사이트별 `color`의 8px 점 하나로만 표시.
- 모바일(폭 768px 이하): 사이드바는 상단 메뉴 버튼으로 접힘, 목록 → 상세는 페이지 전환.

### 7-2. 공통 레이아웃 (`base.html`)
- **왼쪽 사이드바(212px):** 로고 「상담관리」 / 메뉴: 통합 문의함(신규 건수 주황 배지) · 오늘 콜백(건수) · 내 담당(건수) · 문자 발송내역 · 문자 템플릿 · 통계·유입분석 · 사이트·폼 연동 · 직원·권한(관리자만) / "연결된 사이트" 목록(색 점 + 이름 + 건수, 클릭 시 사이트 필터) / 하단 로그인 사용자 이름·직함.
- 사이드바 배지 숫자는 `GET /api/badge` 를 **30초마다 폴링**해 갱신. 신규 건수가 늘면 브라우저 탭 제목 앞에 `(3)`처럼 표시.

### 7-3. 목록 화면 — A안 `GET /inquiries`
- **상단 바:** 제목 「통합 문의함」 + 보조문구(선택 사이트명 · 연동 사이트 수 · 오늘 날짜) / 검색창(이름·번호·내용, 번호는 숫자만 넣어도 검색) / [목록 | 보드] 토글 / 「엑셀 내려받기」(admin) / 「수동 등록」(전화로 들어온 문의 직접 입력).
- **상태 탭:** 전체 · 신규 · 연락중 · 상담완료 · 계약 · 보류 · 종결 — 각 탭 옆에 건수. 현재 탭은 아래 2px 파란 줄.
- **추가 필터(접히는 줄):** 담당자, 기간(오늘/7일/30일/직접), 업종, 콜백 있음.
- **목록 열:** 상태 배지 · 접수일시(`10.13 19:42`) · 유입 사이트(색 점+이름) · 고객명 + 문의유형 + `중복` 배지 + 문의내용 한 줄 미리보기 · 연락처(`010-4821-3307` 형식) · 담당(미배정은 주황 굵게).
- 정렬: 기본 접수 최신순. 한 페이지 50건, 하단에 "총 N건" + 페이지 번호.
- 행 클릭 → URL을 `?id=123`으로 바꾸고(`history.replaceState`) 오른쪽 상세를 `GET /inquiries/123/panel`(HTML 조각)로 교체. 새로고침해도 같은 건이 열려 있어야 함.
- 키보드: ↑/↓로 이전·다음 건 (입력창에 포커스 있을 때는 동작 안 함).

### 7-4. 상세 패널 (`_detail.html`, 목록·보드 공용)
1. **머리:** 사이트(색 점) · 업종 · 문의번호 / 고객명(크게) + 문의유형 / 연락처 / [전화](`tel:` 링크, 누르면 "통화 결과 기록" 버튼이 강조됨) [문자](문자 탭으로 이동)
2. **중복 안내 띠:** `duplicate_of_id`가 있거나 이 건을 가리키는 후속 문의가 있으면 "같은 연락처로 접수된 문의가 N건 더 있습니다 · 보기"
3. **상담 상태:** 6칸 버튼 줄(현재 상태만 진하게). 종결 누르면 사유 선택 작은 창.
4. **담당자**(select, agent는 "나에게 배정"만) · **콜백 예약**(날짜+시간 입력, 비우기 가능) · 지역 · 접수일시/기기 · 유입 키워드(`utm_term`, 없으면 referrer 도메인)
5. **문의 내용** 박스 (줄바꿈 유지)
6. **탭: 상담 기록 / 상담지 / 문자 보내기**
   - 상담 기록: 메모 입력칸 + [통화 완료로 기록] [부재중 기록] [메모 등록]. 아래 기록 목록은 **최신이 위**. 각 줄 = 종류 배지(접수·통화·문자·메모·상태·상담지) + 내용 + `시간 · 작성자`.
   - 상담지: 사건 유형별 구조화 양식. **7-7 참고.**
   - 문자 보내기: 받는 사람/발신번호 표시, 템플릿 버튼(사이트·업종에 맞는 것만), 내용 입력, `N byte · SMS 단문/LMS 장문` 실시간 표시, [예약 발송] [지금 보내기]. 보내면 "발송 완료 · 상담 기록에 저장되었습니다" 표시.
- 상세를 열 때마다 `access_logs`에 `view_detail` 기록 (같은 사용자·같은 건은 10분 내 중복 기록 안 함).

### 7-7. 상담지 (사건 유형별 양식) — 상세 패널 「상담지」 탭

**왜 필요한가:** 형사·민사·가사·개인회생·교통사고·가맹 상담은 물어봐야 할 항목이 전혀 다르다. 메모 한 칸으로는 빠뜨리는 게 생기고 나중에 찾기도 어렵다. 그래서 **유형마다 체크박스·드롭다운·숫자칸으로 된 양식**을 두고, 상담원이 통화하면서 채우게 한다. 양식은 코드에 박지 않고 **DB(JSON 스키마)**에 두어 관리자가 설정 화면에서 항목을 고치고 새 유형을 추가할 수 있게 한다.

**구조**
- `consult_forms` 1행 = 양식 하나 (예: 「개인회생」). `category`(legal/franchise)와 `inquiry_type_keys`(폼에서 들어오는 `inquiry_type` 문자열 목록, 예: `["개인회생","회생"]`)로 문의에 자동 매칭된다.
- 양식의 항목은 `schema_json`에 **섹션 → 필드** 2단계 배열로 저장한다.
- `consult_sheets` 1행 = 문의 1건에 대한 양식 답변 (`answers_json`). 문의 1건에 양식 1개(양식을 바꾸면 이전 답변은 보관하고 새 sheet 생성).

**필드 타입 (`schema_json`의 `type`)**

| type | 화면 | 저장값 |
|---|---|---|
| `select` | 드롭다운 (`options`) | 문자열 |
| `multi` | 체크박스 묶음 (`options`) | 문자열 배열 |
| `radio` | 가로 버튼 묶음(2~4개 선택지일 때 드롭다운 대신) | 문자열 |
| `bool` | 체크박스 1개 | true/false |
| `number` | 숫자칸, `unit`(만원/명/개월/평) 뒤에 표시, 천 단위 콤마 | 숫자 |
| `text` | 한 줄 | 문자열 |
| `textarea` | 여러 줄 | 문자열 |
| `date` | 날짜 | `YYYY-MM-DD` |

공통 속성: `key`(영문 snake, 양식 안에서 유일) · `label` · `required`(bool) · `help`(작은 회색 설명) · `show_if`(`{"key":"has_lawyer","eq":true}` 처럼 다른 답에 따라 표시) · `score`(아래 참고).

**스키마 예시 — 개인회생**
```json
{
  "sections": [
    {"title": "채무 현황", "fields": [
      {"key": "total_debt", "label": "총 채무액", "type": "number", "unit": "만원", "required": true},
      {"key": "debt_kinds", "label": "채무 종류", "type": "multi", "options": ["신용카드","카드론","은행 신용대출","저축은행·캐피탈","대부업","사채","세금·4대보험 체납","개인 채무"]},
      {"key": "creditor_count", "label": "채권자 수", "type": "number", "unit": "곳"},
      {"key": "overdue", "label": "연체 상태", "type": "radio", "options": ["연체 없음","1~3개월","3개월 이상","추심 진행 중"]},
      {"key": "has_lawsuit", "label": "소송·압류·경매 진행 여부", "type": "bool"},
      {"key": "lawsuit_detail", "label": "진행 내용", "type": "text", "show_if": {"key": "has_lawsuit", "eq": true}}
    ]},
    {"title": "소득·재산", "fields": [
      {"key": "job_type", "label": "소득 형태", "type": "select", "options": ["급여소득(4대보험)","급여소득(비정규·일용)","사업소득","프리랜서","무직","기타"], "required": true},
      {"key": "monthly_income", "label": "월 실수령", "type": "number", "unit": "만원", "required": true},
      {"key": "dependents", "label": "부양가족 수", "type": "number", "unit": "명"},
      {"key": "assets", "label": "보유 재산", "type": "multi", "options": ["자가 주택","전세·월세 보증금","자동차","예금·적금","보험 해지환급금","없음"]},
      {"key": "asset_value", "label": "재산 합계(추정)", "type": "number", "unit": "만원"}
    ]},
    {"title": "이력·판단", "fields": [
      {"key": "prior_case", "label": "과거 회생·파산·워크아웃 이력", "type": "radio", "options": ["없음","회생","파산","신복위 워크아웃"]},
      {"key": "fit", "label": "적합 절차(상담원 판단)", "type": "select", "options": ["개인회생","개인파산","신복위 워크아웃","판단 보류","해당 없음"]},
      {"key": "note", "label": "특이사항", "type": "textarea"}
    ]}
  ]
}
```

**기본 양식 6종 (seed, `app/seeds/consult_forms/*.json`에 파일로 두고 seed가 읽음)**

| 양식 | 매칭 inquiry_type | 핵심 항목 |
|---|---|---|
| 개인회생·파산 | 개인회생, 개인파산, 회생, 파산 | 위 예시 |
| 형사 | 형사, 경찰 출석, 고소 대응, 고소, 피의자, 피해자 | 입장(피의자/피해자/참고인) · 죄명(select: 폭행·상해, 사기, 음주·무면허, 성범죄, 마약, 명예훼손·모욕, 교통사고(형사), 기타) · 사건 단계(radio: 고소 전/경찰 조사/검찰 송치/기소/재판) · 출석·재판 일시(date) · 구속 여부(bool) · 합의 여부(radio) · 전과(radio) · 증거자료 보유(multi) · 요청사항(multi: 조사 동행, 의견서, 합의 중재, 재판 변론) |
| 민사 | 민사, 손해배상, 대여금, 계약, 임대차 | 사건 종류(select: 대여금, 손해배상, 계약 분쟁, 임대차·보증금, 공사대금, 명예훼손, 기타) · 입장(원고/피고 예정) · 분쟁 금액(number 만원) · 상대방(개인/법인) · 증거(multi: 계약서, 차용증, 송금내역, 문자·카톡, 녹취, 없음) · 소멸시효 관련 발생일(date) · 상대방 재산 파악 여부(bool) · 기존 소송·지급명령 여부(radio) |
| 가사(이혼·양육) | 이혼, 협의이혼, 재산분할, 양육권, 양육비, 가사, 상속 | 유형(select: 협의이혼, 재판이혼, 재산분할, 위자료, 양육권·양육비, 상속·유류분) · 혼인 기간(number 년) · 자녀(number 명, 미성년 bool) · 재산(multi: 아파트·주택, 전세보증금, 예금, 사업체, 차량, 부채) · 추정 재산 합계(number 만원) · 유책 사유(multi: 외도, 폭력, 유기, 경제 문제, 성격 차이, 기타) · 상대방 합의 의사(radio) · 별거 여부·기간 · 양육비 미지급 기간(개월, show_if 유형=양육) |
| 교통사고 | 교통사고, 보험 합의, 보상 | 입장(피해자/가해자) · 사고 일시(date) · 과실 비율(number %) · 부상(select: 경상 염좌, 골절, 수술, 장해 예상, 사망) · 진단 주수(number) · 치료(radio: 통원/입원/치료 중) · 입원 일수 · 보험사 제시액(number 만원) · 보험사 측 접촉 여부(bool) · 자료 보유(multi: 진단서, 사고사실확인원, 블랙박스, 입퇴원확인서) |
| 프랜차이즈 가맹 | 가맹, 창업, 업종전환, 가맹 계약 | 창업 형태(radio: 신규/업종전환/추가 점포) · 희망 지역(text) · 점포 확보(radio: 확보/후보 있음/없음) · 평수(number 평) · 가용 자금(number 만원) · 대출 계획(bool) · 운영 형태(radio: 직접 운영/점장 운영/배달 전문) · 외식업 경험(radio) · 희망 오픈 시기(select: 1개월 내/3개월/6개월/미정) · 상담 단계(select: 1차 안내/자료 발송/본사 미팅/상권 분석/계약 검토) · 특이사항 |

> 위 항목은 출발점이다. 법률 항목 명칭은 **실무자 확인 후 설정 화면에서 수정**하라고 사용자에게 안내한다. 코드 수정 없이 바꿀 수 있어야 한다.

**화면 동작 (`_sheet.html`)**
- 탭을 열면 문의의 `inquiry_type`에 매칭되는 양식을 자동 선택해 보여준다. 매칭이 없으면 상단 드롭다운 「양식 선택」만 보이고, 고르면 양식이 나타난다. 매칭됐어도 드롭다운으로 바꿀 수 있다 (예: 「개인회생」으로 들어왔지만 파산 상담이 된 경우).
- 섹션 제목은 작은 대문자 느낌의 회색 라벨 + 아래 얇은 줄. 필드는 **라벨 왼쪽(140px 고정) · 입력 오른쪽**의 2열 표 형태로, A안 상세 패널 폭(약 400~480px)에 맞춘다. `multi` 체크박스는 2열 격자, `radio`는 붙어 있는 세그먼트 버튼(상태 버튼과 같은 모양).
- **자동 저장:** 값이 바뀌면 800ms 뒤 `POST /inquiries/<id>/sheet`로 전체 answers 저장. 상단 오른쪽에 `저장됨 20:14` / `저장 중…` / `저장 실패 — 다시 시도` 표시. 명시적 저장 버튼은 없다.
- 필수 항목이 비어 있으면 탭 이름 옆에 작은 주황 점. 채워지면 사라진다.
- 저장할 때마다 `inquiry_logs`를 남기지는 않는다 (너무 많아짐). 대신 **상담지가 처음 작성될 때 1번**, 그리고 양식을 바꿀 때 `kind='sheet'` 로그 1줄 (`상담지 작성 시작: 개인회생`, `상담지 양식 변경: 개인회생 → 개인파산`).
- 「상담지 요약 복사」 버튼: 채워진 항목만 `라벨: 값` 줄바꿈 텍스트로 클립보드에 복사 (변호사·본사에 전달용). 「인쇄」는 상세 패널만 A4로 인쇄되는 `@media print` 스타일.
- 목록 화면 추가 필터에 **「상담지 작성됨 / 미작성」** 추가. 엑셀 내려받기에는 현재 필터의 양식이 하나로 통일돼 있을 때만 상담지 열을 펼쳐서 넣는다 (양식이 섞여 있으면 「상담지 요약」 한 열로).

**설정 > 상담지 양식 관리 `/settings/forms` (admin)**
- 목록: 양식명 · 업종 · 매칭 유형 · 필드 수 · 작성된 건수 · 사용 여부.
- 편집 화면은 **양식 빌더**: 왼쪽에 섹션/필드 목록(드래그 정렬은 SortableJS, 없으면 ▲▼ 버튼), 오른쪽에 선택한 필드의 속성 편집(라벨·타입·필수·선택지(한 줄에 하나)·단위·도움말·표시 조건). 아래에 **실시간 미리보기**(실제 `_sheet.html` 렌더링). 저장 시 `schema_json` 검증: key 중복, select/multi에 options 없음, show_if가 없는 key를 가리킴 → 저장 거부하고 어떤 필드인지 표시.
- 필드의 `key`는 처음 만들 때 라벨에서 자동 생성(영문 없으면 `f_<랜덤6>`)하고, **한 번 저장된 뒤에는 바꿀 수 없게** 한다(기존 답변이 깨지므로). 필드를 지워도 기존 `answers_json`의 값은 남겨두고 화면에만 안 보이게 한다.
- 「JSON으로 편집」 토글: 고급 사용자용으로 스키마를 직접 고칠 수 있게. 같은 검증 적용.
- 양식 복제 버튼 (비슷한 양식을 빠르게 만들 때).

### 7-5. 보드 화면 — B안 `GET /board`
- 상단: 업종 칩(전체/법률/프랜차이즈) · 사이트 칩(색 점) · 「내 담당만」 칩 / 오른쪽 요약 숫자 4개: **오늘 접수 · 미배정 · 오늘 콜백 · 계약 전환(계약 수 / 전체)** — 모두 DB에서 계산한 값.
- 본문: 상태 6칸(신규~종결). 칸 머리 위쪽 3px 색 줄 + 상태명 + 건수. 칸이 넘치면 가로 스크롤.
- 카드: 사이트(색 점)·접수시간 / 고객명(굵게)+문의유형 / 마지막 기록 내용 2줄(마지막이 접수·자동문자면 문의내용) / 배지: 담당(미배정 주황) · `콜백 10.14 19:00`(파랑) · `중복`.
- 종결 칸은 최근 30일만, 카드 흐리게.
- 카드 클릭 → **오른쪽에서 서랍(최대 560px)**으로 상세가 열림. 서랍 내용은 7-4와 같은 데이터를 B안 배치로: 진행 단계 4칸(신규→연락중→상담완료→계약) + [보류] [종결 처리] / 정보 3열 / 문의내용 인용 / **채팅형 타임라인(오래된 것이 위)**: 문자는 오른쪽 말풍선(자동발송은 흰 말풍선), 통화는 전화 아이콘 줄, 메모는 흰 박스, 접수·상태변경은 가운데 작은 회색 글씨 / 아래 입력창은 [메모|문자] 전환.
- (Phase 5 선택) 카드 드래그로 상태 변경 — SortableJS 사용 가능. 종결로 끌면 사유 선택창.

### 7-6. 그 밖의 화면
- **문자 발송내역** `/sms`: 기간·사이트·상태(성공/실패/예약)·자동여부 필터, 예약 건 취소, 실패 건 재발송.
- **문자 템플릿** `/settings/templates`: 목록·추가·수정·순서변경, 적용 범위(전체/업종/사이트), 미리보기(샘플 이름으로 치환 + 바이트).
- **사이트·폼 연동** `/settings/sites`: 사이트 추가(코드·이름·업종·색·도메인·허용 Origin·발신번호·자동문자 여부·보관일수), 키 재발급(비밀키는 발급 순간 한 번만 보여줌), 연동 예시 코드 복사, "테스트 문의 보내기" 버튼.
- **직원·권한** `/settings/users`: 추가·비활성화·비밀번호 초기화·역할·담당 사이트.
- **통계** `/stats` (Phase 6): 기간 선택 / 사이트별 접수·계약·전환율 표 / 일별 접수 막대그래프 / 첫 연락까지 걸린 시간(중앙값) / 담당자별 처리 건수 / 유입 키워드 상위 20.

---

## 8. 내부 엔드포인트 (화면용, 로그인 필요, CSRF 필수)

| 메서드 | 경로 | 동작 |
|---|---|---|
| GET | `/inquiries` | 목록 화면 (필터는 쿼리스트링: `status, site, q, assignee, period, cat, cb, page, id`) |
| GET | `/board` | 보드 화면 |
| GET | `/inquiries/<id>/panel` | 상세 HTML 조각 (`?layout=drawer`면 B안 배치) |
| POST | `/inquiries/<id>/status` | `{status, close_reason?}` |
| POST | `/inquiries/<id>/assign` | `{assignee_id \| null}` |
| POST | `/inquiries/<id>/callback` | `{callback_at \| null}` |
| POST | `/inquiries/<id>/logs` | `{kind: memo\|call\|call_missed, body}` |
| POST | `/inquiries/<id>/sms` | `{body, scheduled_at?}` |
| GET | `/inquiries/<id>/sheet` | 상담지 탭 HTML 조각 (`?form_id=`로 양식 바꿔 보기) |
| POST | `/inquiries/<id>/sheet` | `{form_id, answers}` 전체 저장 (자동 저장용, 응답 `{ok, saved_at, required_done}`) |
| GET | `/inquiries/<id>/sheet.txt` | 상담지 요약 텍스트 (복사 버튼용) |
| GET/POST | `/settings/forms`, `/settings/forms/<id>` | 양식 목록·빌더·저장 (admin) |
| POST | `/settings/forms/<id>/duplicate` | 양식 복제 |
| POST | `/inquiries` | 수동 등록 |
| GET | `/inquiries/export.xlsx` | 현재 필터 그대로 엑셀 (admin, `access_logs` 기록) |
| GET | `/api/badge` | `{new, today_callback, mine}` |

- 액션 POST는 JSON으로 결과를 돌려주고, 화면은 돌려받은 **갱신된 상세 HTML 조각**과 **목록 행/카드 HTML 조각**으로 해당 부분만 교체한다 (응답: `{ok, panel_html, row_html}`).
- 모든 변경은 `services/inquiry.py`의 함수 하나를 거치며, 그 함수가 **변경 + `inquiry_logs` 기록**을 한 트랜잭션에서 처리한다. 라우트에서 모델을 직접 고치지 않는다.
- 권한 검사는 서비스 진입 시 `can_access(user, inquiry)`로 통일. 권한 없는 건은 404.

로그 문장 규칙 (화면에 그대로 보임):
- 상태: `연락중 → 상담완료` (종결이면 `→ 종결 (사유: 비용 불일치)`)
- 배정: `담당자 미배정 → 윤서영 팀장`
- 콜백: `콜백 예약 10.14 (수) 19:00` / `콜백 예약 해제`
- 통화: `통화 완료 · {메모}` / `부재중 — 연결 안 됨`

---

## 9. 개인정보 처리

- **보관기간:** 매일 새벽 `flask privacy-sweep`(crontab) → `closed_at` 또는 `contracted_at`이 `sites.retention_days`를 넘긴 건을 마스킹: 이름 `박*훈`, 번호 `010-****-3307`, 문의내용·메모·문자 본문은 `[보관기간 경과로 삭제]`, `extra_json`·`ip`·`user_agent` 삭제, `is_masked=1`. 통계용 숫자(사이트·상태·일시·utm)는 남긴다.
- **조회 기록:** 상세 열람·엑셀 다운로드는 `access_logs`에 남기고, admin은 설정에서 조회할 수 있게 한다.
- **엑셀:** admin만. 파일명에 다운로드 일시 포함.
- 로그인 5회 실패 시 10분 잠금. 세션 8시간 만료. 운영은 HTTPS 필수, 쿠키 `Secure`·`HttpOnly`·`SameSite=Lax`.
- 개인정보처리방침(수집 항목·보관기간·위탁: 문자발송사)은 **각 홈페이지에 게시**해야 함 — 사이트 설정 화면에 안내 문구로 표시.

---

## 10. 환경변수 (`.env.example`)

```
FLASK_ENV=development
SECRET_KEY=change-me
DATABASE_URL=mysql+pymysql://user:pass@localhost:3306/inquiry_admin?charset=utf8mb4
TZ=Asia/Seoul
ADMIN_BASE_URL=https://admin.example.co.kr

SMS_PROVIDER=dummy            # dummy | aligo
SMS_DEFAULT_SENDER=0200000000 # 사전 등록된 대표 발신번호
ALIGO_API_KEY=
ALIGO_USER_ID=
ALIGO_TESTMODE=Y              # 운영 전환 시 N

COMPANY_NAME=[회사명]
REPRESENTATIVE_PHONE=[대표번호]
```

---

## 11. 목업 데이터 (`flask seed`)

개발·시연용. 디자인 시안과 같은 데이터를 넣는다. `--reset` 옵션이면 기존 데이터를 지우고 다시 넣는다. **운영 DB에서는 실행 거부** (`FLASK_ENV=production`이면 중단).

**직원:** 윤서영(팀장, manager, 로그인 `yoon`) · 강민석(실장, manager, `kang`) · 오세진(가맹팀, agent, `oh`, 프랜차이즈 사이트만) · 관리자(admin, `admin`). 비밀번호는 모두 `test1234!` (seed 전용).

**사이트:**

| code | 이름 | 업종 | 색 |
|---|---|---|---|
| hs | 회생파산 상담센터 | legal | #c2410c |
| ih | 이혼·가사 상담 | legal | #7c3aed |
| ta | 교통사고 보상센터 | legal | #0369a1 |
| hj | 형사 변호 상담 | legal | #475569 |
| cb | 바삭한형제 가맹 | franchise | #b45309 |
| mc | 모퉁이커피 창업 | franchise | #15803d |

**문의 12건** (날짜는 seed 실행일 기준 상대값으로 계산: D0=오늘, D-1=어제 …):

| # | 사이트 | 유형 | 고객 | 번호 | 지역 | 접수 | 상태 | 담당 | 콜백 | 비고 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | hs | 개인회생 | 박정훈 | 01048213307 | 경기 수원시 영통구 | D0 19:42 | 신규 | 미배정 | | #11과 중복 |
| 2 | hj | 형사 · 경찰 출석 | 조민재 | 01066120954 | 서울 강서구 | D0 20:03 | 신규 | 미배정 | | |
| 3 | ih | 협의이혼 · 재산분할 | 정다은 | 01022945518 | 서울 송파구 | D0 16:20 | 연락중 | 윤서영 | D+1 19:00 | 부재→문자→회신 메모 |
| 4 | cb | 가맹 창업 | 이수진 | 01077301942 | 경기 화성시 동탄 | D0 18:55 | 신규 | 미배정 | | |
| 5 | ta | 보험 합의 | 한재욱 | 01051638820 | 인천 부평구 | D0 11:08 | 상담완료 | 강민석 | | 통화 22분, 메모 |
| 6 | mc | 가맹 · 업종전환 | 서동현 | 01090154432 | 대전 유성구 | D-1 15:47 | 연락중 | 오세진 | D0 21:00 | 안내서 문자 |
| 7 | hj | 형사 · 고소 대응 | 문상현 | 01030476621 | 경기 성남시 분당구 | D-1 10:12 | 보류 | 강민석 | D+3 14:00 | |
| 8 | hs | 개인파산 | 김영자 | 01033802716 | 경기 수원시 권선구 | D-1 21:30 | 계약 | 강민석 | | 방문상담→수임 |
| 9 | cb | 가맹 창업 | 유지호 | 01088721406 | 충남 천안시 | D-2 13:30 | 종결 | 오세진 | | 사유: 비용 불일치 |
| 10 | ih | 양육권 · 양육비 | 임가영 | 01044192083 | 경기 고양시 일산동구 | D-2 09:50 | 상담완료 | 윤서영 | | |
| 11 | hs | 개인회생 | 박정훈 | 01048213307 | 경기 수원시 영통구 | D-1 19:05 | 연락중 | 강민석 | D0 20:30 | 부재 기록 |
| 12 | mc | 가맹 계약 | 황보름 | 01025087731 | 부산 해운대구 | D-4 14:22 | 계약 | 오세진 | | 가맹계약 체결 |

**상담지 seed:** 양식 6종을 넣고, 문의 #1(박정훈 개인회생)·#5(한재욱 교통사고)·#6(서동현 가맹)·#7(문상현 형사)에는 양식에 맞는 답변이 채워진 `consult_sheets`를 넣는다 (#1은 문의 내용대로 총 채무 7,800만원·카드론 포함·월 실수령 280만원·급여소득). #3(정다은 가사)은 양식만 매칭되고 미작성 상태로 둔다.

문의 내용·유입 키워드·상담 기록 문장은 `design/A_list.dc.html` 하단 스크립트 `seed()` 데이터와 같게 작성한다. 시안 파일이 없으면 위 표의 비고를 바탕으로 자연스러운 한국어 문장으로 채운다. **seed 번호는 실제 사람과 겹칠 수 있으므로 seed 문자는 절대 실제 발송하지 않는다** (seed 시 `SMS_PROVIDER`와 무관하게 sms_messages를 `sent` + `provider='seed'`로만 기록).

---

## 12. 개발 단계 (한 단계씩)

### Phase 1 — 뼈대·DB·로그인
- 앱 팩토리, 설정, 확장, 폴더 구조
- 모델 전체 + 첫 마이그레이션
- 로그인/로그아웃, 역할 데코레이터(`@role_required`), `can_access`
- `base.html` 사이드바 레이아웃 + CSS 변수 (메뉴는 링크만)
- `flask create-admin`, `flask seed`
- **완료 기준:** `flask db upgrade && flask seed` 후 4개 계정으로 로그인됨 / agent로 로그인하면 사이드바에 직원·권한 메뉴가 안 보임 / pytest: 로그인, 권한 데코레이터

### Phase 2 — 접수 API와 사이트 연동
- `POST /api/v1/inquiries` (두 가지 인증, 검증, 허니팟, 속도 제한, CORS)
- `services/intake.py` (정규화·기기판정·중복판정·로그·자동문자 큐 등록)
- 설정 > 사이트 화면 (추가·수정·키 발급/재발급·연동 예시·테스트 문의 보내기)
- **완료 기준:** curl로 서버키 접수 201 / 잘못된 키 401 / 허용 안 된 Origin 거부 / 같은 번호 두 번 접수 시 두 번째에 `duplicate_of_id` / 허니팟 값 있으면 저장 안 됨 / 자동문자 `queued` 생성 / pytest 각 경우

### Phase 3 — 목록(A안)·상세·상담 기록
- `/inquiries` 목록 (탭·필터·검색·페이지), 상세 패널 조각, URL `?id=` 유지, ↑/↓ 이동
- 상태 변경(종결 사유), 담당 배정, 콜백 예약, 메모/통화/부재 기록 — 전부 서비스 함수 + 로그
- 사이드바 배지 + `/api/badge` 폴링
- 수동 등록
- **완료 기준:** 시안 A안과 같은 배치·색으로 보임 / 상태를 바꾸면 목록 행 배지·탭 건수·기록이 새로고침 없이 바뀜 / agent는 남의 배정 건이 목록에 없고 URL로 열어도 404 / 모바일 폭에서 목록→상세 전환 동작

### Phase 4 — 상담지 (사건 유형별 양식)
- `consult_forms`·`consult_sheets` 모델, `services/sheet.py` (양식 매칭, 스키마 검증, 답변 저장, 필수 완료 계산, 요약 텍스트)
- `_sheet.html` 렌더러: 스키마 → 8가지 필드 타입 렌더링, `show_if`, 자동 저장 JS, 저장 상태 표시, 요약 복사, 인쇄 스타일
- 상세 패널에 「상담지」 탭 추가 (시안 `design/C_sheet.dc.html` 배치대로), 탭 이름 옆 필수 미완료 점
- 설정 > 상담지 양식 관리: 목록, 빌더(섹션·필드 편집·정렬·속성·미리보기), JSON 편집, 복제, 저장 검증
- seed에 양식 6종 + 답변 예시 반영, 목록 필터 「상담지 작성됨/미작성」
- **완료 기준:** 개인회생 문의를 열면 개인회생 양식이 자동으로 보임 / 값을 바꾸면 1초 안에 "저장됨" 표시, 새로고침해도 유지 / `has_lawsuit` 체크 시에만 "진행 내용"이 나타남 / 빌더에서 선택지를 하나 추가하면 상담지에 바로 반영 / key 중복·옵션 없는 select 저장 시 거부 메시지 / 양식 변경 시 이전 sheet는 `is_current=0`으로 보존 / agent가 남의 문의 sheet에 POST하면 404 / pytest: 매칭·검증·show_if·요약

### Phase 5 — 문자
- Provider 인터페이스 + Dummy + Aligo, 바이트 계산, 템플릿 치환
- 상세의 문자 탭 (템플릿 버튼, 실시간 바이트, 지금/예약 발송)
- `flask sms-worker` + 재시도 + 실패 로그
- 문자 발송내역 화면, 템플릿 관리 화면
- **완료 기준:** Dummy로 보내면 `sent` + 상담 기록에 남음 / 91바이트 이상이면 LMS / 예약 건이 시각 이후 워커에서 발송 / 워커를 두 번 동시에 돌려도 중복 발송 없음 / 치환 안 된 변수 경고 / Aligo 테스트모드로 1건 실제 호출 성공 (사용자가 키를 넣은 뒤)

### Phase 6 — 콜백·통계·보안·배포
- 오늘 콜백 메뉴(콜백 시간순 목록, 지난 콜백은 빨간 글씨)
- `/stats`, 엑셀 내려받기(상담지 열 포함 규칙은 7-7), `access_logs` 화면
- `flask privacy-sweep`(상담지 `answers_json`도 마스킹 대상), 로그인 잠금, 세션 만료, 보안 헤더
- 배포 문서(`DEPLOY.md`): Cafe24 서버 gunicorn systemd 유닛, nginx 설정, crontab 3줄(sms-worker 매분, privacy-sweep 매일 04:00, DB 백업 매일)
- **완료 기준:** 보관기간 지난 테스트 건이 마스킹됨 / 엑셀 다운로드가 기록됨 / `DEPLOY.md`대로 새 서버에 올릴 수 있음

### Phase 7 (선택, 지시가 있을 때만) — 보드 보기(B안)
- `/board` 칸반 + 서랍 상세(`layout=drawer`), 요약 숫자 4개, 업종/사이트/내 담당 필터, (선택) 드래그 상태 변경. 시안 `design/B_board.dc.html`.
- **완료 기준:** 보드와 목록이 같은 데이터를 보여줌 / 서랍에서 상태 바꾸면 카드가 해당 칸으로 이동 / 서랍 밖 클릭·Esc로 닫힘

---

## 13. 코딩 규칙

- 화면 문구·로그 문장은 모두 한국어. 코드·변수·DB 컬럼은 영어.
- 날짜 표시: 목록·기록은 `MM.DD HH:mm`, 콜백은 `MM.DD (요일) HH:mm`. 필터 함수로 통일 (`|kdate`, `|kcallback`, `|phone`).
- 전화번호는 DB에 숫자만, 화면에는 `010-1234-5678`.
- 사용자 입력은 Jinja2 자동 이스케이프에 맡기고 `|safe` 쓰지 않는다 (서버가 만든 HTML 조각 삽입만 예외).
- JS는 `static/js/app.js` 한 파일, 모듈 패턴. `innerHTML`에는 서버가 렌더링한 조각만 넣는다.
- 새 기능은 서비스 함수 테스트를 먼저 쓴다. 각 Phase 끝에 `pytest` 전부 통과.
- 실제 문자 발송이 일어날 수 있는 코드는 `SMS_PROVIDER=dummy`일 때 절대 외부 호출을 하지 않도록 테스트로 보장.

---

## 14. 범위 밖 (지금은 안 함)

카카오 알림톡, 광고성 대량 문자, 고객용 마이페이지, 결제, 녹취 연동, 다중 회사(멀티테넌트). 필요해지면 별도 문서로 설계한다.
