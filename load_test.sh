#!/bin/bash
# 외래 5명 연속 시뮬레이션

MODEL="gemma-3-12b-it-qat"
URL="http://127.0.0.1:1234/v1/chat/completions"

CASES=(
"60세 남자 B형 간염으로 인한 간경변 추적 중. MELD 18점, Child-Pugh B 7점. 복부 초음파에서 5cm 간세포암이 우엽에 발견. 아테졸리주맙 베바시주맙 병용요법 시작 예정."
"45세 여자 알코올성 간경변 외래 추적. 복수 조절 위해 푸로세미드 40mg 스피로노락톤 100mg 증량. 간성혼수 grade 1 의심되어 락툴로오스 30cc 하루 세 번 시작."
"55세 남자 만성 C형 간염. 글레카프레비르 마비레트 8주 치료 종료 후 SVR12 평가 위해 HCV RNA 검사 시행. AST 25, ALT 30 정상화."
"68세 남자 HCC TACE 후 추적. AFP 250에서 80으로 감소. CT에서 우엽 2cm 병변 부분 괴사 확인. 6주 후 재평가 예정."
"50세 여자 자가면역성 간염 의심. ANA 1대 320 양성, IgG 2200 상승, ALT 280 AST 320. 간생검 시행 예정."
)

echo "===== 외래 5명 연속 시뮬레이션 시작 ====="
echo ""

for i in {0..4}; do
  echo "===== 환자 $((i+1)) ====="
  START=$(date +%s)

  curl -s "$URL" \
    -H "Content-Type: application/json" \
    -d "{
      \"model\": \"$MODEL\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"한국어 외래 진료 dictation을 SOAP JSON으로 분류. S(주관적), O(객관적), A(평가), P(계획). 원문에 없는 정보 추가 금지. JSON만 출력.\"},
        {\"role\": \"user\", \"content\": \"${CASES[$i]}\"}
      ],
      \"temperature\": 0.1,
      \"max_tokens\": 500
    }" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d['choices'][0]['message']['content'][:300])"

  END=$(date +%s)
  echo ""
  echo "응답 시간: $((END-START))초"
  echo ""
  sleep 2
done

echo "===== 시뮬레이션 완료 ====="
echo "메뉴바에서 최종 메모리 사용률을 확인하세요."
