# 디자인

강의노트의 화면 설계와 디자인 시스템을 두는 곳입니다. 디자인 원본은 Figma에 있고, 프론트(`web/`)는 그 값을 그대로 씁니다.

- Figma 파일: [강의노트 디자인](https://www.figma.com/design/dX5M9RxMbJg3walupwZiWF)
  - `01 와이어프레임`: 화면 8개 뼈대
  - `02 디자인 시스템`: 변수(Color Light/Dark 24개, Spacing·Radius 10개), 글자 스타일 6개, 그림자 2개,
    컴포넌트 Button · Chip · ListItem · TopBar · BottomBar · PostIt(필기 7종) · TermCard · NoteSection
  - `03 디자인`: 자료 목록 · 강의 슬라이드(녹음 중) · 노트 모드 · 공부하기 · 시험 예상 지도 · 용어 사전
- 토큰 → 코드: `web/src/styles/tokens.css` (Figma 변수 이름의 `/`를 `-`로 바꾼 CSS 변수, 다크 모드 포함)
- 컴포넌트 → 코드: `web/src/components/ui.tsx` (이름과 variant를 Figma와 같게 맞춤)

## 작업 순서

1. ✅ 와이어프레임
2. ✅ 디자인 시스템 (토큰 · 컴포넌트)
3. ✅ 실제 디자인 (화면 6개) — 일러스트는 받으면 추가
4. ✅ `web/` 구현: 기존 웹앱의 모든 화면·기능을 옮김. 서버 `/` 가 새 앱으로 열린다 (빌드했을 때)
