# uHandServer

uHandServer는 Hiwonder uHandPi의 Raspberry Pi OS에서 실행되는 실물 제어 서버입니다. Windows 또는 macOS에서 실행한 uHandMotionCreator 또는 uHandClientModule에서 보내는 명령을 받아 다섯 손가락과 손목, 부저, 두 RGB LED를 구동합니다.

처음 설치할 때는 준비된 OS 이미지를 microSD 카드에 기록합니다. 다운로드 정보, Windows에서 Win32 Disk Imager로 카드를 기록하는 절차, SSH 계정과 초기 비밀번호는 설치 가이드에서 확인하세요. [실물 로봇손 설치 가이드](../../docs/hardware-setup.md)

## 소리로 서버 상태 확인하기

실물 서버는 다음 알림음을 로봇손의 내장 부저로 재생합니다. 부저 카드를 만들거나 별도의 명령을 보내지 않아도 들리는 소리입니다.

| 언제 들리나요? | 들리는 소리 | 의미 |
| --- | --- | --- |
| 로봇손 부팅으로 uHandServer가 시작되거나 서비스를 다시 시작했을 때 | **도 → 미 → 솔** (523 → 659 → 784 Hz) | 서버 초기화를 마치고 연결을 받을 준비가 됐습니다. |
| uHandMotionCreator 또는 Python 클라이언트가 제어 연결을 맺을 때 | **미 → 라** (659 → 880 Hz) | 연결음이 끝나면 제어 명령을 보낼 수 있습니다. |
| 클라이언트가 연결을 해제하거나, 실행 중인 서버가 통신 단절을 감지했을 때 | **라 → 파♯ → 레** (440 → 370 → 294 Hz) | 기존 제어 연결을 정리했습니다. 해제음이 끝나면 다시 연결할 수 있습니다. |

세 경우 모두 재생 중인 부저를 멈추고 두 LED를 끈 뒤, 손가락 다섯 개와 손목을 기본 펄스값 1500으로 복귀시킵니다(500 ms). 그다음 알림음을 한 음에 175 ms씩, 음 사이에 75 ms를 두고 재생합니다.

예를 들어 전원이 켜진 채 LAN 케이블이 빠지면 서버가 단절을 감지한 시점에 해제음을 냅니다. 장비 전원 자체가 끊기면 부저도 함께 꺼지므로 해제음은 들리지 않습니다.

## 서비스 전환

로봇손에 SSH로 로그인한 뒤 아래 명령을 실행합니다. 전환하면 실행 중인 서비스가 중지되므로 연결된 클라이언트의 작업을 먼저 마칩니다.

| 원하는 작업 | 명령 |
| --- | --- |
| 현재 실행 상태와 다음 부팅 설정 확인 | `uhand-mode status` |
| 제조사 서비스를 이번에만 사용 | `sudo uhand-mode vendor` |
| uHandServer로 즉시 복귀 | `sudo uhand-mode server` |
| 현재 실행 중인 서비스에서 다른 쪽으로 전환 | `sudo uhand-mode toggle` |
| 지금부터 재부팅 후에도 제조사 서비스 사용 | `sudo uhand-mode vendor --boot` |
| 지금부터 재부팅 후에도 uHandServer 사용 | `sudo uhand-mode server --boot` |

배포 기본값은 uHandServer 자동 시작입니다. 이 상태에서 `sudo uhand-mode vendor`로 바꾸면 지금은 제조사 서비스가 실행되고 다음 부팅 때는 uHandServer가 시작됩니다. `--boot`를 함께 지정하면 선택한 서비스가 다음 부팅에도 시작됩니다.

`uhand-mode status` 출력에서 `active/running`은 지금 동작하는 서비스, `boot=enabled`는 다음 부팅 때 시작될 서비스입니다. 모드 전환 스크립트의 장비 내 위치는 `/usr/local/bin/uhand-mode`입니다. 서비스 이름은 각각 `uhand-server.service`와 `uhandpi.service`입니다.

## 서버 소프트웨어만 업데이트하기

이미 이 프로젝트의 SD 이미지로 운용 중이라면, 새 릴리스가 현재 장비와 OS를 지원하는지 릴리스 설명에서 먼저 확인하세요. 아래는 **1.0.0과 같은 폴더 구조와 서비스 설정을 사용하는 후속 버전**의 수동 업데이트 절차입니다. 이전 릴리스 폴더는 보관하고 새 버전을 별도 폴더에 설치합니다. 3단계에서는 서비스가 원래 어느 폴더를 실행했는지 기록한 설정 파일도 백업합니다.

### 장비에서 어떤 파일을 사용하는가

1.0.1의 실행 기준 폴더는 `/home/pi/uhand-server/releases/1.0.1/`입니다. 1.0.0 배포 이미지에서는 같은 위치의 `1.0.0/` 폴더를 사용합니다. 현재 서비스가 가리키는 경로는 SSH에서 `systemctl show uhand-server.service -p WorkingDirectory -p ExecStart -p FragmentPath -p DropInPaths`로 확인할 수 있습니다.

| 저장소에서 가져올 파일 | 로봇손에서의 위치와 용도 |
| --- | --- |
| `projects/uhand-server/run_server.py` | 버전 폴더의 `run_server.py`. 서버 시작 파일 |
| `projects/uhand-server/src/uhand_server/` | 버전 폴더의 `src/uhand_server/`. 서버 제어 코드 전체 |
| `shared/uhand-server-lifecycle/src/uhand_server_lifecycle/` | 아래 절차에서는 **새 버전 폴더**의 `src/uhand_server_lifecycle/`에 함께 설치. 초기화·연결 처리를 담당하는 공통 코드 |
| `projects/uhand-server/config/hardware-profile.json` | 버전 폴더의 `config/hardware-profile.json`. 장비 매핑과 제조사 파일 검증값 |
| `projects/uhand-server/systemd/uhand-server.service` | `/etc/systemd/system/uhand-server.service`. 어느 버전을 자동 실행할지 지정 |
| `projects/uhand-server/tools/uhand_mode.py` | `/usr/local/bin/uhand-mode`. 서비스 전환 도구 자체를 갱신할 때 사용 |

제조사 SDK `/home/pi/uhandpi/common_sdk/common/ros_robot_controller_sdk.py`와 보정 원본 `/home/pi/uhandpi/config/deviation.yaml`은 장비에 보존합니다. 장비별 보정을 변경한 사용자는 새 프로필과 기존 프로필을 비교하고 해당 장비와의 호환성을 먼저 확인하세요.

### 1. Windows 또는 Mac에서 로봇손으로 새 릴리스 전송

GitHub Releases에서 **설치하려는 버전의 소스 ZIP**을 받아 압축을 풉니다. `projects`와 `shared`가 보이는 최상위 폴더에서 자신의 운영체제에 맞는 명령을 차례로 실행합니다. 각 명령이 성공하면 다음 줄로 넘어가세요.

**Windows PowerShell**

```powershell
tar.exe -czf "$env:TEMP\uhand-server-update.tar.gz" projects/uhand-server/run_server.py projects/uhand-server/src/uhand_server projects/uhand-server/config/hardware-profile.json projects/uhand-server/systemd/uhand-server.service shared/uhand-server-lifecycle/src/uhand_server_lifecycle
scp "$env:TEMP\uhand-server-update.tar.gz" pi@192.168.61.1:~/uhand-server-update.tar.gz
ssh pi@192.168.61.1
```

**macOS 터미널**

```sh
archive="${TMPDIR:-/tmp}/uhand-server-update.tar.gz"
tar -czf "$archive" projects/uhand-server/run_server.py projects/uhand-server/src/uhand_server projects/uhand-server/config/hardware-profile.json projects/uhand-server/systemd/uhand-server.service shared/uhand-server-lifecycle/src/uhand_server_lifecycle
scp "$archive" pi@192.168.61.1:~/uhand-server-update.tar.gz
ssh pi@192.168.61.1
```

### 2. 로봇손에서 새 버전 준비

이제부터는 **SSH로 접속한 로봇손 터미널**에서 실행합니다. 아래 첫 줄의 `X.Y.Z`를 내려받은 릴리스 번호로 바꾸세요. 이 절차는 현재 uHandServer가 실행 중이며 배포 기본 유닛을 사용하는 장비를 대상으로 합니다. 먼저 `uhand-mode status`에서 `uhand-server.service`가 `active/running`인지 확인하세요. 위의 `DropInPaths`에 별도 설정 파일이 표시되면 실행 경로를 재정의하는지 먼저 확인합니다.

```sh
version='X.Y.Z'
release="/home/pi/uhand-server/releases/$version"
(
  set -eu
  work=$(mktemp -d)
  tar -xzf "$HOME/uhand-server-update.tar.gz" -C "$work"
  source_dir="$work/projects/uhand-server"
  unit="$source_dir/systemd/uhand-server.service"
  grep -Fx "WorkingDirectory=$release" "$unit" >/dev/null
  grep -F "ExecStart=/usr/bin/python3 -B $release/run_server.py " "$unit" | grep -F -- "--profile $release/config/hardware-profile.json" >/dev/null
  sudo mkdir "$release"
  sudo install -d "$release/src" "$release/config"
  sudo install -m 0644 "$source_dir/run_server.py" "$release/run_server.py"
  sudo cp -R "$source_dir/src/uhand_server" "$work/shared/uhand-server-lifecycle/src/uhand_server_lifecycle" "$release/src/"
  sudo install -m 0644 "$source_dir/config/hardware-profile.json" "$release/config/hardware-profile.json"
  sudo install -m 0644 "$unit" "$release/uhand-server.service"
  cd "$release"
  /usr/bin/python3 -B -c 'import pathlib, runpy, sys; runpy.run_path("run_server.py"); import uhand_server, uhand_server_lifecycle; root = pathlib.Path.cwd(); assert uhand_server.__version__ == sys.argv[1]; assert all(pathlib.Path(m.__file__).resolve().is_relative_to(root) for m in (uhand_server, uhand_server_lifecycle))' "$version"
  echo "새 버전 준비 완료"
)
```

**‘새 버전 준비 완료’가 표시됐을 때만** 다음 단계로 진행합니다. 버전 폴더가 이미 있거나 서비스 파일의 경로가 다르면 준비 단계가 중단됩니다. 이때 현재 서버는 계속 실행됩니다. 릴리스 번호, 기존 폴더, 해당 버전의 설치 안내를 다시 확인하세요. 마지막 Python 검사에서 실패하면 서버 버전이 다르거나 공통 모듈을 새 폴더 밖에서 읽었을 수 있습니다. 운영 중인 공통 파일을 덮어쓰지 말고 해당 릴리스의 설치 경로를 확인하세요.

### 3. 서비스 전환과 확인

클라이언트에서 실행 중인 동작을 마치고 연결을 해제합니다. 재시작하면 손이 기본 자세로 복귀하므로 움직일 공간을 확보하세요. **같은 SSH 터미널**에서 기존 서비스 파일을 백업하고 새 파일을 적용합니다.

```sh
(
  set -eu
  test ! -e "$release/previous-uhand-server.service"
  sudo cp -p /etc/systemd/system/uhand-server.service "$release/previous-uhand-server.service"
  sudo install -m 0644 "$release/uhand-server.service" /etc/systemd/system/uhand-server.service
  sudo systemctl daemon-reload
  sudo systemctl restart uhand-server.service
)
systemctl show uhand-server.service -p WorkingDirectory -p ActiveState
uhand-mode status
```

준비음이 끝난 뒤 `WorkingDirectory`가 새 버전 경로인지, `uhand-mode status`가 `active/running`과 `boot=enabled`를 표시하는지 확인합니다. Windows 또는 Mac의 uHandMotionCreator에서 `192.168.61.1:5000`으로 연결하여 상태를 조회하고 LED를 잠시 켰다가 꺼 보세요. 시작 실패 또는 반복 재시작은 `sudo journalctl -u uhand-server.service -b -n 50 --no-pager`로 확인합니다.

### 4. 문제가 있으면 이전 버전으로 복귀

이 절차는 **수동 업데이트 직전의 릴리스 폴더**와 **3단계에서 만든 `previous-uhand-server.service`**가 모두 있는 장비에 적용합니다. 1.0.1 이미지 제작용 로봇손에는 1.0.1만 설치되어 있어, 아래 명령으로 1.0.0에 복귀할 수 없습니다. 현재 배포하는 1.0.1 이미지를 새 카드에 기록하는 방법은 [이미지와 카드 준비](../../docs/hardware-setup.md#1-이미지와-카드-준비)에서 확인하세요.

수동 업데이트를 진행한 SSH 터미널에서 아래 명령을 실행합니다. 다시 로그인했다면 먼저 `release`에 이번에 설치한 새 버전 폴더의 전체 경로를 지정하세요.

```sh
(
  set -eu
  backup="$release/previous-uhand-server.service"
  test -f "$backup" || { echo "이전 서비스 설정 백업이 없습니다."; exit 1; }
  previous=$(sed -n 's/^WorkingDirectory=//p' "$backup")
  test -n "$previous" && test -f "$previous/run_server.py" || { echo "이전 릴리스의 실행 파일을 찾을 수 없습니다."; exit 1; }
  sudo install -m 0644 "$backup" /etc/systemd/system/uhand-server.service
  sudo systemctl daemon-reload
  sudo systemctl restart uhand-server.service
)
systemctl show uhand-server.service -p WorkingDirectory -p ActiveState
```

이전 버전 경로와 `ActiveState=active`를 확인하고 클라이언트를 다시 연결합니다. `uhand-mode vendor`는 제조사 프로그램을 실행하는 명령이므로, **서버 버전 복귀**에는 위의 백업 유닛을 사용하세요.
