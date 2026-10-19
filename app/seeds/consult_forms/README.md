# 상담지 기본 양식

`01_rehab.json`은 완성본. 나머지 5개(`02_criminal.json` 형사, `03_civil.json` 민사, `04_family.json` 가사, `05_traffic.json` 교통사고, `06_labor.json` 인사·노무)는
CLAUDE.md 7-7의 "기본 양식 6종" 표에 적힌 항목을 같은 JSON 구조로 만든다. `flask seed`가 이 폴더의 *.json을 파일명 순으로 읽어 `consult_forms`에 넣는다.
