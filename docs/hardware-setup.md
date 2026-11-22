# 실물 로봇손 설치 가이드

이 이미지는 Hiwonder uHandPi용 Raspberry Pi OS 배포본입니다. Windows PC에서 microSD 카드에 기록하고 로봇손에 넣으면 uHandServer가 부팅 시 자동으로 시작되도록 구성합니다.

이미 SD 이미지로 사용 중인 로봇손에서 서버 버전만 올리려면 [uHandServer 업데이트 및 이전 버전 복귀](../projects/uhand-server/README.md#서버-소프트웨어만-업데이트하기)를 따르세요.

## 사용 장비와 주요 사양

| 항목 | 이번 프로젝트에 사용한 장비 |
| --- | --- |
| 제조사·제품명 | Hiwonder uHandPi 로봇손 |
| 메인 컴퓨터 | Raspberry Pi 4 Model B Rev 1.5 (프로젝트 실물에서 확인) |
| 제어 축 | 서보 6개. 다섯 손가락을 각각 제어하며 손목은 수직축을 중심으로 좌우 회전합니다(YAW). |
| 소리 출력 | 내장 부저. 프로젝트 제어 범위는 0~10,000 Hz이며 0 Hz는 무음입니다. |
| 빛 출력 | RGB LED 2개. 두 LED에 같은 색과 밝기를 적용합니다. |
| 프로젝트 연결 방식 | Ethernet 직결, 로봇손 고정 IP `192.168.61.1/24` |

현재 제조사 제품 소개는 Raspberry Pi 5 모델을 기준으로 설명합니다. 위 표는 이 프로젝트의 OS 이미지를 준비한 실물 장비 기준입니다. 제품 소개와 제조사 예제는 공식 튜토리얼에서 확인할 수 있습니다. [Hiwonder uHandPi 공식 튜토리얼](https://wiki.hiwonder.com/projects/uHandPi/en/latest/)

## 1. 이미지와 카드 준비

ZIP을 내려받아 압축을 풀면 **uHandControl-1.0.1.img**가 나옵니다. 아래 SHA-256으로 다운로드한 ZIP과 카드에 기록할 IMG를 각각 확인할 수 있습니다.

| 항목 | 배포 정보 |
| --- | --- |
| 대상 서버 | uHandServer 1.0.1 |
| 다운로드 | [로봇손 SD 카드 이미지 ZIP 받기 (Google Drive)](https://drive.google.com/file/d/1L85k0Egico9ijK62MaR7uK4jhVI6I-Tf/view?usp=sharing) |
| 다운로드한 ZIP | `uHandControl-1.0.1.zip` · 3,797,110,300바이트 |
| ZIP의 SHA-256 | `F70DD3A712F302C12C11212FAE9DF115FE5CCDCE631B8D3908FE795F92E4E2FC` |
| 압축을 푼 IMG | `uHandControl-1.0.1.img` · 31,266,439,168바이트 |
| IMG의 SHA-256 | `999B2B3FCD2CFD9FD51601034EAC5CE0973F2980AC235E328758913EC6D27F67` |

준비물은 Windows PC, microSD 카드 리더기, 내용을 지워도 되는 32 GB microSD 카드, Ethernet 케이블입니다. 같은 32 GB 제품이라도 실제 용량이 다를 수 있습니다. 대상 카드의 바이트 수가 압축 해제한 이미지 크기 이상이어야 전체 이미지를 기록할 수 있습니다.

## 2. Windows에서 카드에 기록

1. 위 표의 **Google Drive**에서 ZIP을 내려받고 다운로드 폴더에서 PowerShell을 엽니다. 아래 첫 명령의 결과를 표의 **ZIP의 SHA-256**과 비교합니다. 값이 일치하면 압축을 풀고 두 번째 명령으로 **IMG의 SHA-256**도 확인합니다. IMG를 다른 폴더에 풀었다면 해당 위치에서 두 번째 명령을 실행하세요.

   ```powershell
   Get-FileHash -Algorithm SHA256 -LiteralPath ".\uHandControl-1.0.1.zip"
   Get-FileHash -Algorithm SHA256 -LiteralPath ".\uHandControl-1.0.1.img"
   ```

   해시가 다르면 카드에 기록하기 전에 다운로드 또는 압축 해제를 다시 진행하세요.
2. 대상 카드를 PC에 꽂고 Windows 탐색기에서 드라이브 문자를 확인합니다. **Write를 누르면 선택한 카드의 기존 내용이 덮어써집니다.**
3. Win32 Disk Imager에서 **Image File**에 압축을 푼 `uHandControl-1.0.1.img`를, **Device**에 대상 카드의 드라이브 문자를 지정합니다. 두 항목을 다시 확인하고 **Write**를 누릅니다. [Win32 Disk Imager 공식 배포처](https://sourceforge.net/projects/win32diskimager/)
4. 완료 메시지가 나오면 카드를 안전하게 꺼냅니다. 전원이 꺼진 로봇손에 카드를 넣고 PC와 로봇손을 Ethernet 케이블로 연결한 뒤 전원을 켭니다. 손이 초기 자세로 돌아가고 준비음이 끝날 때까지 기다립니다.

## 3. 첫 로그인과 제어 연결

| 용도 | 값 |
| --- | --- |
| 로봇손 Ethernet 고정 IP | `192.168.61.1` |
| 서브넷 마스크 | `255.255.255.0` (/24) |
| 네트워크 구성 | Ethernet 전용, 로봇손 Wi-Fi 비활성, DHCP 미사용 |
| SSH 관리 계정 | `pi` |
| 배포 이미지 초기 비밀번호 | `1234qwer` |
| SSH 로그인 포트 | TCP `22` |
| uHandServer 제어 포트 | TCP `5000` |

1. PC와 로봇손을 직접 연결한다면 PC **Ethernet 어댑터**의 IPv4 주소를 예를 들어 `192.168.61.2`, 서브넷 마스크를 `255.255.255.0`으로 설정합니다. 이 직결 구성에서는 게이트웨이와 DNS를 비워 둘 수 있습니다.
2. Windows PowerShell에서 `ssh -p 22 pi@192.168.61.1`로 접속합니다. 위의 초기 비밀번호로 로그인합니다. 자신의 장비에서 비밀번호 변경을 원하면 `passwd`를 실행합니다. `pi`는 `sudo`로 장비를 관리할 수 있는 계정입니다.
3. SSH 창에서 `uhand-mode status`를 실행합니다. 기본 구성에서는 `uhand-server.service` 줄에 `active/running`과 `boot=enabled`가 표시됩니다.
4. Windows 또는 macOS의 uHandMotionCreator에서 **서버 연결·테스트**를 열고 IP `192.168.61.1`, 포트 `5000`으로 연결합니다. 연결 초기화와 연결음이 끝나면 LED 색상을 적용해 실물 두 LED가 함께 바뀌는지 확인할 수 있습니다.

## 4. 제조사 튜토리얼 실행과 프로젝트 복귀

**제조사 튜토리얼에서 로봇손을 조작하기 전에 제조사 모드로 전환하세요.** 프로젝트 서버와 제조사 프로그램은 같은 장치에 명령을 보냅니다. 이 배포 이미지에서는 제조사 모드에서도 Ethernet 연결을 사용하므로 튜토리얼의 Wi-Fi 핫스폿 연결 단계는 건너뛰고 유선 주소 `192.168.61.1`을 사용하세요.

1. uHandMotionCreator나 Python 클라이언트에서 실행 중인 동작을 마치고 연결을 해제합니다.
2. 위에서 접속한 **로봇손의 SSH 창**에서 다음 두 명령을 차례로 실행합니다.

   ```sh
   sudo uhand-mode vendor
   uhand-mode status
   ```

3. `uhandpi.service` 줄에 `active/running`이 표시되면 제조사 예제를 진행합니다. [Hiwonder uHandPi 공식 튜토리얼](https://wiki.hiwonder.com/projects/uHandPi/en/latest/)
4. 실습을 마치면 제조사 예제 프로그램을 종료하고 같은 SSH 창에서 프로젝트 모드로 복귀합니다.

   ```sh
   sudo uhand-mode server
   uhand-mode status
   ```

5. `uhand-server.service`가 `active/running`이고 준비음이 끝나면 uHandMotionCreator에서 `192.168.61.1:5000`으로 다시 연결합니다.

위 명령은 현재 실행할 서비스를 바꿉니다. 배포 기본 설정에서는 제조사 모드로 실습한 뒤 재부팅하면 uHandServer가 자동으로 시작됩니다. 이후 부팅할 서비스까지 바꾸는 방법은 서버 안내에서 확인하세요. [서비스 전환 명령](../projects/uhand-server/README.md#서비스-전환)

## 배포 담당자용

- 운영 중인 실물 장비도 위 표와 같은 비밀번호를 유지합니다. 이 주소로 SSH 접속할 수 있는 사람은 공개된 계정으로 로그인하고 `sudo`를 사용할 수 있으므로 실습 PC와 로봇손을 Ethernet으로 직접 연결해 사용합니다.
- 원본 카드를 보존하고 배포용 카드를 준비합니다. 개인 SSH 인증 키·허용 키, 토큰, 개인 파일·로그와 삭제된 데이터가 전체 디스크 이미지에 포함되지 않도록 정리합니다. SSH 호스트 키는 복제 장비마다 첫 부팅에서 새로 생성되는지 확인합니다. 제조사 소프트웨어 등 이미지에 포함한 파일의 재배포 조건도 확인합니다.
- 로봇손을 정상 종료한 뒤 배포용 카드를 PC에 연결합니다. Win32 Disk Imager의 **Device**에서 원본이 될 배포용 카드를 선택하고 **Image File**에 새 파일 경로를 지정한 뒤 **Read**로 추출합니다.
- 1.0.1 추출본을 별도의 32 GB 카드에 **Write**로 복원한 뒤, LAN 케이블을 뽑은 상태에서 전원을 켭니다. **도 → 미 → 솔**은 uHandServer 초기화가 끝났다는 신호입니다. 준비음이 끝나면 케이블을 연결하고, 재부팅 없이 `192.168.61.1:5000`에 접속해 상태를 조회합니다.
- 복원한 카드에서 초기 비밀번호 로그인, 서버 자동 시작, 실물 LED 제어, 제조사 서비스 일시 전환 및 서버 복귀도 확인합니다.
- 검증한 파일을 Google Drive에 보기·다운로드 권한으로 공유합니다. 로그인하지 않은 브라우저에서도 다운로드 가능한지 확인하고, 위 표에 공유 링크와 시험한 카드를 기록합니다. ZIP과 압축 해제한 IMG 각각의 파일명, 바이트 수, SHA-256을 새 파일에서 확인해 함께 갱신합니다. Git에는 가이드와 다운로드 정보만 관리합니다.
