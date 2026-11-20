# uHandServer

uHandServer는 Hiwonder uHandPi의 Raspberry Pi OS에서 실행되는 실물 제어 서버입니다. Windows의 uHandMotionCreator 또는 uHandClientModule에서 보내는 명령을 받아 다섯 손가락과 손목, 부저, 두 RGB LED를 구동합니다.

처음 설치할 때는 준비된 OS 이미지를 microSD 카드에 기록합니다. 다운로드 정보, Windows 기록 절차, SSH 계정과 초기 비밀번호는 설치 가이드에서 확인하세요. [실물 로봇손 설치 가이드](../../docs/hardware-setup.md)

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
