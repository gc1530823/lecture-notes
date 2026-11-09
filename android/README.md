# 강의노트 안드로이드 앱

화면은 서버의 웹앱(`/web/`, `web/` 폴더)을 그대로 띄우고, **녹음과 서버 연결은 앱이 직접** 해서 화면을 꺼도 녹음이 이어집니다.
웹앱에 넣은 기능은 따로 만들 필요 없이 앱에도 바로 들어갑니다.

## 받기 · 깔기 (Mac·개발자 계정 필요 없음)

1. 핸드폰 브라우저로 GitHub에 로그인한 채 저장소의 **Releases → 안드로이드 앱 (최신)** 에서 `lecture-notes.apk` 를 받습니다.
2. 받은 파일을 열고, 처음 한 번 "이 출처의 앱 설치 허용"을 켭니다.
3. 앱을 켜면 서버 주소를 묻습니다. Codespaces라면 포트 8000번 주소 (`https://…-8000.app.github.dev`)를 넣습니다.
   비공개 포트라 처음에 GitHub 로그인 화면이 나오면 로그인합니다.

## 앱이 하는 일

| 기능 | 어떻게 |
| --- | --- |
| 녹음 | `LiveService` (포그라운드 서비스, 알림 줄에 "녹음 중"): 16kHz PCM을 서버 WebSocket으로. 끊기면 다시 잇고 끊긴 동안 소리를 모아 둠 |
| 화면 | WebView로 `/web/`. 웹앱은 `window.AndroidLive`가 있으면 브라우저 마이크 대신 앱 녹음을 씀 (`web/src/lib/live.ts`) |
| 파일 올리기·칠판 사진 | WebView 파일 선택 (카메라 포함) |
| 내려받기 | 정리 PDF·Markdown·Anki는 다운로드 관리자로, 족보 공유 파일은 내려받기 폴더에 저장 |
| 인쇄 | 족보 노트를 안드로이드 인쇄(PDF로 저장) |

## 빌드

GitHub Actions의 **Android** 워크플로가 `android/` 가 바뀔 때마다 빌드해 `android-latest` 릴리스에 올립니다.
직접 빌드하려면 Android SDK와 JDK 17을 깔고 `cd android && gradle assembleRelease`.

### 서명 키 (선택)

서명 키가 없으면 빌드할 때마다 임시 키로 서명돼서, 새 버전을 깔 때 **앱을 지우고 다시 깔아야** 합니다
(자료는 서버에 있어 그대로, 서버 주소만 다시 넣으면 됨).
덮어 깔기가 되게 하려면 서명 키를 한 번 만들어 저장소 Settings → Secrets and variables → Actions 에 넣습니다:
`ANDROID_KEYSTORE_BASE64`(키 파일을 base64로), `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`.
키 파일과 비밀번호는 채팅이나 저장소에 올리지 마세요.
