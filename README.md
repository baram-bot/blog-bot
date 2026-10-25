# 바람따라 한국여행 블로그 자동 발행 봇

구글 블로거(baram-salim.blogspot.com)에 하루 3편(오전 8시, 오후 1시, 저녁 7시쯤) 한국여행 글을 자동으로 발행합니다.
컴퓨터를 꺼도 GitHub에서 돌아가고, 비용은 들지 않습니다(Gemini 무료 사용량 안에서).

## 이렇게 돌아갑니다

1. `topics.txt`에서 아직 안 쓴 주제를 위에서부터 하나 고릅니다.
2. Gemini가 구글 검색으로 사실을 확인하면서 2,500~3,500자 글을 씁니다.
3. 위키미디어 공용에서 자유 이용 사진을 찾아 출처와 함께 넣습니다.
4. `data/coupang_links.txt`에 맞는 상품이 있으면 글 끝에 1개 넣고, 맨 위에 대가성 문구를 붙입니다.
5. 블로거에 바로 발행하고, 텔레그램으로 제목과 주소를 알려 줍니다.
6. 발행 기록은 `data/posted.json`에 남아 같은 주제를 두 번 쓰지 않습니다.

## 처음 한 번만 하는 설정

비밀번호와 키 입력은 보안상 직접 해 주셔야 합니다. PC 크롬에서 하시는 것이 편합니다.

### 1. Gemini API 키 (GEMINI_API_KEY)
1. https://aistudio.google.com/apikey 접속, 블로그와 같은 구글 계정으로 로그인
2. **API 키 만들기** → 나온 키를 복사해 메모장에 붙여 둡니다.

### 2. 구글 클라우드에서 블로거 연결 준비 (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET)
1. https://console.cloud.google.com 접속 → 위쪽 프로젝트 선택 → **새 프로젝트** → 이름 `baram-blog` → 만들기
2. 왼쪽 메뉴 **API 및 서비스 → 라이브러리** → `Blogger API v3` 검색 → **사용**
3. **API 및 서비스 → OAuth 동의 화면**(또는 Google 인증 플랫폼) → 외부(External) → 앱 이름 `baram-blog`, 이메일은 본인 것 → 저장
4. **대상(Audience)** 또는 동의 화면에서 **앱 게시(Publish app) → 프로덕션으로 푸시**를 꼭 눌러 주세요.
   이걸 안 하면 7일마다 연결이 끊겨 글이 안 올라갑니다. (본인만 쓰는 앱이라 구글 심사는 필요 없습니다.)
5. **사용자 인증 정보(클라이언트) → OAuth 클라이언트 ID 만들기**
   - 애플리케이션 유형: **웹 애플리케이션**
   - 승인된 리디렉션 URI: `https://developers.google.com/oauthplayground`
6. 만들어진 **클라이언트 ID**와 **클라이언트 보안 비밀번호**를 메모장에 복사합니다.

### 3. 블로그 연결 토큰 받기 (GOOGLE_REFRESH_TOKEN)
1. https://developers.google.com/oauthplayground 접속
2. 오른쪽 위 **톱니바퀴** → **Use your own OAuth credentials** 체크 → 2번의 클라이언트 ID와 보안 비밀번호 붙여넣기
3. 왼쪽 아래 입력칸에 `https://www.googleapis.com/auth/blogger` 입력 → **Authorize APIs**
4. 블로그 주인 구글 계정으로 로그인 → "확인되지 않은 앱" 경고가 나오면 **고급 → baram-blog(으)로 이동** → 허용
5. **Exchange authorization code for tokens** 클릭 → 나온 **Refresh token**을 메모장에 복사

### 4. 블로그 번호 (BLOGGER_BLOG_ID)
블로거 관리 화면(blogger.com)을 열면 주소창에 `blogID=숫자`가 있습니다. 그 숫자만 복사합니다.

### 5. GitHub에 비밀값 넣기
저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 아래 이름 그대로(대소문자·철자 정확히) 넣습니다.

| 이름 | 값 |
|---|---|
| GEMINI_API_KEY | 1번 키 |
| GOOGLE_CLIENT_ID | 2번 클라이언트 ID |
| GOOGLE_CLIENT_SECRET | 2번 보안 비밀번호 |
| GOOGLE_REFRESH_TOKEN | 3번 토큰 |
| BLOGGER_BLOG_ID | 4번 숫자 |
| TELEGRAM_BOT_TOKEN | 스레드 봇과 같은 텔레그램 봇 토큰(선택) |
| TELEGRAM_CHAT_ID | 스레드 봇과 같은 채팅 ID(선택) |

### 6. 시험 발행
저장소 **Actions → blog-auto-post → Run workflow** → 1~3분 뒤 블로그에 글이 올라오면 성공입니다.
실패하면 텔레그램(또는 Actions 기록)에 원인이 나옵니다.

## 쿠팡 파트너스 상품 넣기
- `data/coupang_links.txt`에 `단축링크 | 상품명 | 분류` 형식으로 한 줄씩 추가합니다.
- 분류: 여행공통, 등산, 캠핑, 겨울여행, 가족여행, 바다여행
- 쿠팡 파트너스 **내 정보 → 웹사이트/채널**에 `https://baram-salim.blogspot.com`을 꼭 등록해 주세요. 등록 안 된 곳에 링크를 올리면 정책 위반이 될 수 있습니다.

## 주제 추가
`topics.txt` 아래에 `주제 | 사진 검색어(영어) | 분류` 형식으로 추가하면 됩니다. 주제를 다 쓰면 텔레그램으로 알려 줍니다.

## 애드센스 신청 시기
글이 20~30편 쌓인 뒤 신청하는 것이 좋습니다. 그 전에 블로그에 **소개** 페이지와 **개인정보처리방침** 페이지를 만들어 두세요.
