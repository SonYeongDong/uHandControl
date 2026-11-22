# uHandClientModule 1.0.0

Python 코드에서 uHandVirtualServer 또는 실물 uHandServer를 제어하는 모듈입니다. 한 Python 프로세스에서 서버 한 대에 연결합니다. 처음 연습할 때는 [같은 PC의 가상 서버](../uhand-virtual-server/README.md)를 먼저 실행하세요.

**Mac 사용자** · [macOS에서 설치하고 실행하기](../../docs/macos-testing.md)

## 설치와 첫 실행

VS Code에서 바로 실행하려면 먼저 uHandVirtualServer를 켜고 **연결 대기**를 확인하세요. [상태 조회 예제](examples/get_status.py) 또는 [손가락으로 1~5 세기 예제](examples/basic_sequence.py)를 열고 **Run Python File**을 누르면 됩니다. 두 예제는 파일 위치를 기준으로 같은 프로젝트의 `src/uhand_client_module`을 찾아 사용하며, 기본 연결 대상은 이 PC의 `127.0.0.1:5000`입니다. 다른 주소나 포트는 터미널에서 `--ip`, `--port`로 지정할 수 있습니다.

Windows 또는 macOS용 Python 3.10 이상이 필요합니다. 두 GUI와 함께 사용하는 검증 환경은 Python 3.13.2입니다. 저장소 최상위에서 [실행기](../../run.pyw)로 GUI 하나를 열었다면 ClientModule도 같은 환경에 설치되어 있습니다. 가상 서버가 연결 대기 중일 때 다음 명령을 실행하세요.

```powershell
.\.venv\Scripts\python.exe projects\uhand-client-module\examples\get_status.py --port 5000
```

모듈만 따로 설치하려면 저장소 최상위의 PowerShell에서 아래 명령을 실행합니다. VS Code에서는 **Python: Select Interpreter**로 이 폴더의 `.venv\Scripts\python.exe`를 선택합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\projects\uhand-client-module
```

## 첫 제어 예제

```python
import uhand_client_module as hand

try:
    hand.Connect("127.0.0.1", 5000)
    # 엄지, 검지, 중지, 약지, 소지, 손목 순서입니다. 각 자세로 1.2초 동안 이동합니다.
    hand.SetuHandPulse(2000, 2000, 1000, 1000, 1000, 1500, 1200)  # 1: 검지
    hand.SetuHandPulse(2000, 2000, 2000, 1000, 1000, 1500, 1200)  # 2: 중지 추가
    hand.SetuHandPulse(2000, 2000, 2000, 2000, 1000, 1500, 1200)  # 3: 약지 추가
    hand.SetuHandPulse(2000, 2000, 2000, 2000, 2000, 1500, 1200)  # 4: 소지 추가
    hand.SetuHandPulse(1000, 2000, 2000, 2000, 2000, 1500, 1200)  # 5: 엄지 추가
    hand.SetuHandBuzzer(1000, 500)
    hand.SetuHandLED(False, True, False)
    print(hand.GetStatus())
except hand.UHandError as error:
    print(type(error).__name__, str(error))
finally:
    hand.Disconnect()
```

숫자 1은 검지만 펴고, 중지·약지·소지·엄지를 하나씩 더 펴서 5까지 셉니다. 손목은 중앙(1500)에 유지합니다. 다섯 손가락을 모두 펴면 1000 Hz 부저가 0.5초 울리고 두 LED가 초록색으로 켜집니다. 실물 서버에 연결할 때는 IP를 `192.168.61.1`로 바꿉니다. 서버의 시작·연결·연결 해제 과정에서는 장비가 초기 자세로 복귀합니다.

## 여섯 함수의 사용법

| 함수 | 입력과 동작 | 성공 시 반환 |
| --- | --- | --- |
| `Connect(IP, Port)` | 숫자 IPv4 또는 IPv6 주소 문자열과 포트 정수 1~65535. 준비된 서버에 연결합니다. | `None` |
| `Disconnect()` | 인수 없이 연결을 닫습니다. 이미 연결이 닫힌 경우에도 호출할 수 있습니다. | `None` |
| `SetuHandPulse(Finger1Pulse, Finger2Pulse, Finger3Pulse, Finger4Pulse, Finger5Pulse, WristPulse, RunningTime)` | 엄지 800~2200, 검지·중지·약지·소지 각각 800~2000, 손목 500~2500의 펄스 정수. 마지막 인수는 100~20000 ms이며 동작 완료까지 기다립니다. | `None` |
| `SetuHandBuzzer(Frequency, RunningTime, Continuous=False)` | 주파수 정수 0~10000 Hz, 시간 정수 100~20000 ms. 기본값에서는 지정 시간만큼 기다립니다. `True`이면 적용 후 반환하고 다음 부저 명령까지 유지합니다. 시간은 두 모드 모두 유효 범위로 지정합니다. | `None` |
| `SetuHandLED(Red, Green, Blue, Brightness=100)` | RGB 각 정수 0~255, 전체 밝기 정수 0~100%. 두 LED에 같은 출력을 즉시 적용합니다. 예전 채널 입력 `True/False`도 각각 255/0으로 처리합니다. | `None` |
| `GetStatus()` | 인수 없이 마지막 적용·완료 기록을 조회합니다. 동작 중 다른 스레드에서 호출하면 이전 완료 기록을 읽습니다. | `dict` |

손가락을 펼칠 때 엄지는 낮은 값, 검지부터 소지까지는 높은 값을 사용합니다. 부저에서 `SetuHandBuzzer(0, 250)`는 250 ms 무음 대기, `SetuHandBuzzer(0, 100, True)`는 즉시 무음 전환입니다. LED는 `SetuHandLED(0, 0, 0)`으로 끕니다.

### GetStatus 결과 읽기

| 키 | 의미 |
| --- | --- |
| `TargetPulses`, `PulseRunningTime` | 마지막 완료 목표 펄스 6개의 리스트(엄지부터 손목 순서)와 이동 시간(ms) |
| `BuzzerFrequency`, `BuzzerRunningTime`, `BuzzerContinuous` | 마지막 부저의 Hz, 지정 시간(ms), 연속 재생 여부 |
| `LED`, `LEDBrightness` | 밝기를 적용하기 전의 RGB 리스트와 밝기(%) |

아직 해당 동작의 기록이 없는 필드는 `None`입니다. 값은 서버가 적용한 명령의 기록입니다. 예컨대 유한음이 끝나도 마지막 주파수는 기록에 남습니다.

### 오류가 발생하면

| 예외 | 확인할 사항 |
| --- | --- |
| `InputValidationError` | 주소·포트·펄스·주파수·시간·RGB의 자료형과 범위를 확인합니다. 잘못된 입력은 전송 전에 거부됩니다. |
| `ConnectionFailedError`, `NotConnectedError`, `AlreadyConnectedError` | 서버의 전원·주소·포트와 현재 연결 여부를 확인합니다. 대상을 바꾸기 전에는 연결을 해제합니다. |
| `BusyError` | 다른 클라이언트가 사용 중이거나 진행 중인 초기화·출력이 완료될 때까지 기다립니다. |
| `DisconnectedError`, `RequestTimeoutError` | 전송 후 끊기면 장비에서 명령이 실행됐을 수 있습니다. 연결 복구 후 상태를 확인합니다. 자동 재전송은 하지 않습니다. |
| `DeviceError`, `UnsupportedFrequencyError`, 기타 `RemoteError` | 서버가 보낸 오류입니다. `code`, `message`로 장비와 요청을 확인합니다. |
| `ProtocolError` | 호환 서버인지, SSH 포트 대신 제어 포트를 지정했는지 확인합니다. |

모든 공개 예외는 `UHandError`로 함께 처리할 수 있습니다. 실행 가능한 예제는 [상태 조회](examples/get_status.py)와 [손·부저·LED 순차 실행](examples/basic_sequence.py)입니다.
