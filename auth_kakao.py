#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
auth_kakao.py

카카오 OAuth 토큰 발급 스크립트 (최초 1회 실행)
발급된 refresh_token 을 .env 에 자동 저장합니다.

사용법:
  1. .env 에 KAKAO_REST_API_KEY=발급받은키 추가
  2. python3 auth_kakao.py
  3. 브라우저가 열리면 카카오 로그인 후 리다이렉트된 URL을 붙여넣기
"""

import os
import sys
import json
import urllib.request
import urllib.parse
import webbrowser

# ── .env 로드 ──
_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

def _load_env(path):
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(path, override=False)
        return
    except ImportError:
        pass
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = val.split(" #", 1)[0].strip().strip('"').strip("'")
            if key.strip():
                os.environ.setdefault(key.strip(), val)

_load_env(_ENV_PATH)

REDIRECT_URI = "http://localhost:5000"
REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")

if not REST_API_KEY:
    sys.exit(
        "[error] KAKAO_REST_API_KEY 가 없습니다.\n"
        f".env 파일({_ENV_PATH})에 KAKAO_REST_API_KEY=여기에_REST_API_키 를 추가하세요.\n"
        "카카오 개발자 콘솔: https://developers.kakao.com"
    )


def get_auth_code() -> str:
    auth_url = (
        "https://kauth.kakao.com/oauth/authorize"
        f"?client_id={REST_API_KEY}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        "&response_type=code"
        "&scope=talk_message"
    )
    print("\n[1단계] 브라우저에서 카카오 로그인을 진행하세요.")
    print(f"  URL: {auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    print("로그인 후 리다이렉트된 전체 URL을 붙여넣으세요.")
    print("  예) http://localhost:5000/?code=AbCdEf12345...")
    raw = input("URL > ").strip()

    parsed = urllib.parse.urlparse(raw)
    params = urllib.parse.parse_qs(parsed.query)
    codes = params.get("code", [])
    if not codes:
        # URL 대신 code 값만 붙여넣은 경우 허용
        if raw and "?" not in raw and "&" not in raw:
            return raw
        sys.exit("[error] URL에서 code 값을 찾을 수 없습니다.")
    return codes[0]


def exchange_code(code: str) -> dict:
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": REST_API_KEY,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }).encode()
    req = urllib.request.Request(
        "https://kauth.kakao.com/oauth/token",
        data=data,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def save_token(refresh_token: str) -> None:
    """refresh_token 을 .env 에 추가/업데이트"""
    lines = []
    found = False
    if os.path.exists(_ENV_PATH):
        with open(_ENV_PATH, encoding="utf-8") as f:
            for line in f:
                if line.startswith("KAKAO_REFRESH_TOKEN="):
                    lines.append(f"KAKAO_REFRESH_TOKEN={refresh_token}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"KAKAO_REFRESH_TOKEN={refresh_token}\n")
    with open(_ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"\n[완료] KAKAO_REFRESH_TOKEN 을 {_ENV_PATH} 에 저장했습니다.")


def main():
    code = get_auth_code()
    print("\n[2단계] 토큰 발급 중...")
    try:
        tokens = exchange_code(code)
    except Exception as e:
        sys.exit(f"[error] 토큰 발급 실패: {e}")

    print(f"  access_token  : {tokens.get('access_token','')[:20]}...")
    print(f"  refresh_token : {tokens.get('refresh_token','')[:20]}...")

    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        sys.exit("[error] refresh_token 이 없습니다. scope 권한을 확인하세요.")

    save_token(refresh_token)
    print("\n이제 send_kakao.py 또는 daily_briefing.py 로 메시지를 전송할 수 있습니다.")


if __name__ == "__main__":
    main()
