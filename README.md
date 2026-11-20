# uHandControl 1.0.0

Hiwonder uHandPi의 손동작·소리·빛을 카드로 만들고, 가상 로봇손에서 확인한 뒤 실제 장비에서 실행하는 Python 프로젝트입니다.

## 1.0.0 다운로드

| 사용 목적 | 받을 파일 |
| --- | --- |
| Windows PC에서 실행 | [프로그램 소스 ZIP (GitHub)](https://github.com/SonYeongDong/uHandControl/archive/refs/tags/v1.0.0.zip)을 풀고 `run.pyw`를 실행합니다. |
| 실물 로봇손의 microSD 카드 준비 | [로봇손 OS 이미지 ZIP (Google Drive)](https://drive.google.com/file/d/1FIJfN0GGV1XN-rRClmctAZMtp2pYu3bc/view)을 풀고 `uHandControl-1.0.0.img`를 카드에 기록합니다. ZIP과 IMG 각각의 SHA-256 및 기록 방법은 [실물 설치 가이드](docs/hardware-setup.md)에 있습니다. |

## Windows에서 첫 동작 실행하기

1. **준비** — Windows에 64비트 Python 3.13(검증 환경 3.13.2)과 기본 설치 구성의 Tkinter가 필요합니다. 첫 설치는 인터넷에 연결해 진행하세요. 위 표에서 받은 **프로그램 소스 ZIP**은 먼저 쓰기 가능한 폴더에 압축을 모두 풉니다.
2. **실행** — 이 README 옆의 `run.pyw`를 더블클릭합니다. 파일 연결이 되어 있지 않으면 해당 폴더에서 PowerShell을 열고 `python run.pyw`를 실행합니다. **uHandVirtualServer**를 선택하면 전용 Python 환경을 준비하고 가상 서버를 엽니다. 시작음이 끝나고 **연결 대기**가 표시될 때까지 기다립니다.
3. **카드 만들기** — 같은 실행기에서 **uHandMotionCreator**를 엽니다. **손동작** 탭에서 검지 슬라이더를 옮기고 **+ 동작 추가**를 누릅니다. 또는 **열기**에서 [손동작·부저·LED 혼합 예제](projects/uhand-motion-creator/examples/sequences/mixed-demo.uhand.json)를 고릅니다.
4. **가상 로봇손 움직이기** — 편집기 상단 **서버 연결·테스트 → 가상 서버·이 PC → 연결**을 누릅니다. 가상 서버의 기본 주소는 `127.0.0.1:5000`입니다. 연결음이 끝난 뒤 **처음부터 실행**을 누르면 서버 창에서 로봇손의 자세가 바뀝니다.
5. **저장** — 편집기 상단 **저장**을 눌러 `.uhjson` 파일로 보관합니다. 다음 실행부터는 이미 설치한 전용 환경을 재사용합니다.

설치가 실패하면 실행기에서 안내하는 `build/launcher.log`를 확인한 뒤 프로그램을 다시 선택하세요.

## 프로그램별 안내

| 프로그램 | 환경 | 사용 안내 |
| --- | --- | --- |
| uHandMotionCreator | Windows | 카드 편집·저장·재생, 서버 연결, Python 코드 생성. [편집 화면 따라 하기](projects/uhand-motion-creator/README.md) |
| uHandVirtualServer | Windows | 가상 3D 손, 부저, LED와 이벤트 로그 확인. [가상 서버 화면 따라 하기](projects/uhand-virtual-server/README.md) |
| uHandClientModule | Windows Python | 함수 여섯 개로 가상·실물 서버 제어. [설치·예제·API 설명](projects/uhand-client-module/README.md) |
| uHandServer | 로봇손의 Raspberry Pi OS | 실물 서보·부저·LED 구동. [서버 사용 및 제조사 서비스 전환](projects/uhand-server/README.md) |

실물을 처음 준비할 때는 microSD 카드 기록, Ethernet 연결과 첫 로그인 순서대로 진행하세요. [실물 설치 가이드와 OS 이미지 배포 정보](docs/hardware-setup.md)

## 개발자 테스트

Windows 실행기로 환경을 설치한 뒤 저장소 최상위에서 아래 명령을 실행합니다. 첫 명령은 각 프로젝트와 공통 패키지의 회귀 테스트, 두 번째는 두 GUI에서 카드 저장·열기와 가상 서버 재생을 확인하는 시험입니다. 네트워크 시험은 이 PC의 루프백 주소를 사용합니다.

```powershell
.\.venv\Scripts\python.exe shared\tests\run_all.py
.\.venv\Scripts\python.exe shared\tests\gui_release.py
```

제조사 SDK 패킷 시험은 장비와 동일한 SDK 파일이 있을 때만 실행합니다. 해당 파일 경로는 환경변수 `UHAND_SDK_TEST_PATH`로 지정할 수 있습니다.