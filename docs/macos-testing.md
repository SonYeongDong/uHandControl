# Mac에서 uHandControl 1.0.0 실행하기

Mac 실기에서 동작을 확인한 1.0.0 배포판의 설치 방법입니다. 가상 서버, 편집기, Python 클라이언트 세 프로그램을 Mac 한 대에서 확인할 수 있습니다. 실물용 uHandServer는 로봇손의 Raspberry Pi OS에서 실행됩니다.

## 1. 두 프로그램 열기

1. **준비물**은 macOS 14 이상과 Tkinter가 포함된 일반 64비트 Python 3.13입니다. Qt 6.12의 macOS 설치 파일은 14 이상용입니다. Apple Silicon과 Intel용 Python 패키지가 제공됩니다.
2. [Windows·Mac 공용 소스 ZIP](https://github.com/SonYeongDong/uHandControl/archive/refs/tags/v1.0.0.zip)을 다운로드하고 Finder에서 압축을 풉니다.
3. 터미널에서 `cd`와 공백을 입력하고, 압축을 푼 폴더를 터미널로 끌어놓은 뒤 Return을 누릅니다. 다음 명령을 실행합니다.

   ```sh
   python3.13 run.pyw
   ```

4. 실행기에서 **uHandVirtualServer**를 누릅니다. 첫 설치에는 인터넷 연결이 필요합니다. 시작음이 끝나 **연결 대기**가 뜨면 같은 실행기에서 **uHandMotionCreator**를 누릅니다.
5. 명령을 찾을 수 없거나 Tkinter 오류가 나면 [Python의 macOS 설치본](https://www.python.org/downloads/macos/)에서 Python 3.13 버전을 설치하고 터미널을 다시 엽니다. `python3.13 -m tkinter`로 작은 창이 열리는지 확인합니다. 패키지 설치나 앱 시작 오류는 압축을 푼 폴더의 `build/launcher.log`에 기록됩니다.

## 2. 첫 실행에서 기능 확인하기

| 확인할 동작 | 기대 결과 |
| --- | --- |
| 가상 서버를 시작하고 전원을 껐다 켜기 | 도·미·솔 세 음이 처음부터 들리고, 같은 IP와 포트에서 다시 연결 대기가 뜹니다. |
| 편집기에서 손 자세를 바꾸고 화면을 두 손가락으로 스크롤하거나 보조 클릭한 채 드래그하기 | 손 자세가 바뀌며 카메라 확대·축소와 회전이 가능합니다. 두 창을 나란히 놓았을 때 3D 손과 한글 글꼴이 표시됩니다. |
| 손동작·부저·LED 카드를 추가하고 저장한 뒤 다시 열기 | macOS 파일 대화상자가 열리고 한글 이름의 `.uhjson` 파일에 카드의 순서와 값이 보존됩니다. ⌘S로 저장하고 ⌘O로 엽니다. |
| 시퀀스와 리스트 창에서 카드 복사·붙여넣기, 실행 취소·다시 실행 | ⌘C, ⌘V, ⌘Z, ⇧⌘Z가 동작합니다. 카드에 포커스가 있을 때 Delete 키로 선택한 카드를 삭제할 수 있습니다. |
| 편집기에서 가상 서버 `127.0.0.1:5000`에 연결하고 카드 실행 | 연결음 후 손 자세와 두 LED의 색·밝기가 바뀝니다. 지정 시간 부저음이 멈추고, 연속음은 손동작 중에도 유지되며 0 Hz 명령으로 멈춥니다. |
| 편집기 연결 해제, 재연결, 연결 중 가상 서버 전원 끄기와 다시 켜기 | 연결 해제음과 초기화, 전원 차단 시 소리 중지, 같은 포트 재연결을 확인합니다. |

편집기의 서버 연결을 해제하고 가상 서버가 연결 대기 상태로 돌아오면, 저장소 폴더에서 Python 클라이언트도 독립적으로 시험합니다.

```sh
.venv/bin/python projects/uhand-client-module/examples/basic_sequence.py
```

가상 손이 1부터 5까지 세고, 부저가 울리고, 두 LED가 초록색으로 켜집니다. 터미널에 마지막 상태가 출력됩니다. 클라이언트 예제만 실행할 때는 Python 3.10 이상에서 예제 옆의 프로젝트 소스를 사용할 수 있습니다.

## 3. 개발자 테스트 및 문제 보고

같은 설치 환경에서 회귀 테스트와 두 GUI의 통합 시험도 실행할 수 있습니다. GUI 시험에서는 창이 잠시 열리고 알림음이 들립니다.

```sh
.venv/bin/python shared/tests/run_all.py
.venv/bin/python shared/tests/gui_release.py
```

macOS 버전(`sw_vers -productVersion`), CPU 종류(`uname -m`), Python 버전(`python3.13 --version`), 사용한 출력 장치와 위 항목별 결과를 함께 기록해 주세요. 오류가 생기면 재현 단계와 `build/launcher.log`의 해당 오류를 첨부해 주세요.
