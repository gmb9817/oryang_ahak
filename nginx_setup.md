# Nginx 설정 가이드

## 1. Nginx 설치

### Windows에서 설치:
1. [nginx 공식 사이트](http://nginx.org/en/download.html)에서 Windows 버전 다운로드
2. 압축 해제 (예: `C:\nginx`)

또는 Chocolatey 사용:
```powershell
choco install nginx
```

## 2. 설정 파일 복사

1. 현재 디렉토리의 `nginx.conf` 파일을 nginx 설치 폴더의 `conf` 디렉토리에 복사
   ```powershell
   Copy-Item nginx.conf C:\nginx\conf\nginx.conf
   ```

2. 또는 nginx 설치 폴더의 기존 `nginx.conf`를 편집하여 위 내용으로 변경

## 3. Nginx 실행

### 관리자 권한으로 PowerShell 실행 후:

```powershell
# Nginx 시작
cd C:\nginx
start nginx

# 또는 Chocolatey로 설치한 경우:
nginx
```

## 4. Nginx 관리 명령어

```powershell
# Nginx 정지
nginx -s stop

# Nginx 재시작 (설정 변경 후)
nginx -s reload

# Nginx 정상 종료
nginx -s quit

# 설정 파일 테스트
nginx -t
```

## 5. Flask 앱 실행

별도 터미널에서 Flask 앱 실행:
```powershell
cd C:\Users\dawns\Documents\Fuck_hacker\oryang_ahak
python app.py
```

## 6. 접속 테스트

브라우저에서 `http://localhost` 또는 `http://127.0.0.1` 접속

## 포트 80 사용 문제 해결

만약 포트 80이 이미 사용 중이면:

1. **다른 프로그램 확인**:
   ```powershell
   netstat -ano | findstr :80
   ```

2. **IIS 중지** (실행 중인 경우):
   ```powershell
   iisreset /stop
   ```

3. **World Wide Web Publishing Service 중지**:
   ```powershell
   net stop http
   ```
   (주의: 이 명령은 시스템에 영향을 줄 수 있습니다)

## Windows 서비스로 등록 (선택사항)

NSSM (Non-Sucking Service Manager)를 사용하여 nginx를 Windows 서비스로 등록:

```powershell
# NSSM 설치
choco install nssm

# Nginx 서비스 등록
nssm install nginx "C:\nginx\nginx.exe"
nssm start nginx
```
