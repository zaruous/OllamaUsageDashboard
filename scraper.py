"""
ollama.com 계정별 사용량 스크래퍼 (쿠키 세션 방식)

로그인 방식:
  - Google / GitHub : 대시보드 '세션 등록' 탭에서 브라우저 쿠키를 붙여넣어 세션 저장
  - email           : account.json의 password로 자동 로그인

account.json 필드:
  - provider : "google" | "github" | "email"
  - active   : true | false  (false면 수집 건너뜀)
  - password : provider가 "email"일 때만 필요
"""

import asyncio
import sys
import json
import re
import threading
from pathlib import Path
from datetime import datetime

from playwright.async_api import async_playwright, Page, BrowserContext

# Windows에서 Playwright subprocess 생성을 위해 ProactorEventLoop 강제 설정
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

ACCOUNTS_FILE = Path(__file__).parent / "account.json"
USAGE_FILE    = Path(__file__).parent / "usage_data.json"
SESSIONS_DIR  = Path(__file__).parent / "sessions"

BASE_URL     = "https://ollama.com"
SIGNIN_URL   = f"{BASE_URL}/signin"
SETTINGS_URL = f"{BASE_URL}/settings"


# ─────────────────────────────────────────────
# 계정 / 세션 파일 관리
# ─────────────────────────────────────────────

def load_accounts() -> list[dict]:
    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def session_path(email: str) -> Path:
    safe = email.replace("@", "_at_").replace(".", "_")
    return SESSIONS_DIR / f"{safe}.json"


def load_session(email: str) -> dict | None:
    p = session_path(email)
    if p.exists():
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def save_session(email: str, storage_state: dict):
    SESSIONS_DIR.mkdir(exist_ok=True)
    with open(session_path(email), "w", encoding="utf-8") as f:
        json.dump(storage_state, f, ensure_ascii=False, indent=2)


def delete_session(email: str) -> bool:
    p = session_path(email)
    if p.exists():
        p.unlink()
        return True
    return False


def has_session(email: str) -> bool:
    return session_path(email).exists()


def save_session_from_cookie_string(email: str, cookie_str: str) -> bool:
    """
    브라우저 DevTools에서 복사한 쿠키 문자열을
    Playwright storage_state 형식으로 변환해 저장합니다.

    지원 형식:
      - Network 탭 Cookie 헤더 값:  name1=val1; name2=val2; ...
      - Console의 document.cookie:  name1=val1; name2=val2; ...
    """
    cookie_str = cookie_str.strip()
    if not cookie_str:
        return False

    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name  = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append({
            "name":     name,
            "value":    value,
            "domain":   "ollama.com",
            "path":     "/",
            "expires":  -1,
            "httpOnly": False,
            "secure":   True,
            "sameSite": "Lax",
        })

    if not cookies:
        return False

    storage_state = {"cookies": cookies, "origins": []}
    save_session(email, storage_state)
    return True


# ─────────────────────────────────────────────
# 로그인 / 수집 (Playwright)
# ─────────────────────────────────────────────

async def is_logged_in(page: Page) -> bool:
    try:
        await page.goto(BASE_URL, wait_until="networkidle", timeout=20000)
        content = await page.content()
        indicators = ["/settings", "sign out", "logout", "profile", "my account"]
        return any(ind.lower() in content.lower() for ind in indicators)
    except Exception:
        return False


async def email_login(context: BrowserContext, account: dict) -> bool:
    """이메일 + 비밀번호로 자동 로그인합니다."""
    page     = await context.new_page()
    email    = account["email"]
    name     = account["name"]
    password = account.get("password", "")

    if not password:
        print(f"[{name}] 이메일 로그인 실패: account.json에 password가 없습니다.")
        await page.close()
        return False

    print(f"[{name}] 이메일 로그인 시도 중...")
    logged_in = False
    try:
        await page.goto(SIGNIN_URL, wait_until="networkidle", timeout=30000)

        email_el = await page.wait_for_selector(
            'input[type="email"], input[name="email"], input[placeholder*="email" i]',
            timeout=8000
        )
        await email_el.fill(email)

        pw_el = await page.wait_for_selector(
            'input[type="password"], input[name="password"]',
            timeout=8000
        )
        await pw_el.fill(password)

        submit = await page.wait_for_selector(
            'button[type="submit"], button:has-text("Sign in"), button:has-text("Log in")',
            timeout=8000
        )
        await submit.click()
        await page.wait_for_url(lambda url: "signin" not in url, timeout=15000)

        logged_in = await is_logged_in(page)
        if logged_in:
            state = await context.storage_state()
            save_session(email, state)
            print(f"[{name}] 이메일 로그인 성공, 세션 저장 완료.")
        else:
            print(f"[{name}] 이메일 로그인 실패: 계정 정보를 확인하세요.")

    except Exception as e:
        print(f"[{name}] 이메일 로그인 오류: {e}")
    finally:
        await page.close()

    return logged_in


async def scrape_usage(page: Page) -> dict:
    """
    설정 페이지에서 사용량 정보를 추출합니다.

    페이지 구조:
      Session usage  →  X% used  →  Resets in N hours
      Weekly usage   →  X% used  →  Resets in N hours
    """
    usage = {
        "plan":               "Unknown",
        "session_used_pct":   None,
        "session_reset":      None,
        "weekly_used_pct":    None,
        "weekly_reset":       None,
        "raw_text":           [],
    }

    try:
        await page.goto(SETTINGS_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)

        page_text = await page.inner_text("body")
        lines = [l.strip() for l in page_text.splitlines() if l.strip()]
        usage["raw_text"] = lines

        # 플랜 감지 (Free / Pro / Max)
        for plan in ["Free", "Pro", "Max"]:
            if plan in lines:
                usage["plan"] = plan
                break

        # 줄 기반 파싱: "Session usage" / "Weekly usage" 섹션
        for i, line in enumerate(lines):
            if line == "Session usage":
                # 다음 줄: "X% used"
                if i + 1 < len(lines):
                    m = re.match(r'([\d.]+)%\s*used', lines[i + 1], re.IGNORECASE)
                    if m:
                        usage["session_used_pct"] = float(m.group(1))
                # 그 다음 줄: "Resets in ..."
                if i + 2 < len(lines):
                    m = re.match(r'Resets in (.+)', lines[i + 2], re.IGNORECASE)
                    if m:
                        usage["session_reset"] = m.group(1).strip()

            elif line == "Weekly usage":
                if i + 1 < len(lines):
                    m = re.match(r'([\d.]+)%\s*used', lines[i + 1], re.IGNORECASE)
                    if m:
                        usage["weekly_used_pct"] = float(m.group(1))
                # "Resets in ..." 는 "Upgrade for..." 줄 건너뛰고 있을 수 있으므로 탐색
                for j in range(i + 2, min(i + 5, len(lines))):
                    m = re.match(r'Resets in (.+)', lines[j], re.IGNORECASE)
                    if m:
                        usage["weekly_reset"] = m.group(1).strip()
                        break

    except Exception as e:
        print(f"  [사용량 파싱 오류] {e}")

    return usage


async def process_account(playwright, account: dict) -> dict:
    """단일 계정 처리: 비활성 건너뜀 → 세션 확인 → 수집."""
    email    = account["email"]
    name     = account["name"]
    provider = account.get("provider", "google").lower()
    active   = account.get("active", True)

    result = {
        "id":            account["id"],
        "name":          name,
        "email":         email,
        "provider":      provider,
        "active":        active,
        "scraped_at":    datetime.now().isoformat(),
        "login_success": False,
        "session_exists": has_session(email),
        "usage":         {},
    }

    if not active:
        print(f"[{name}] 비활성 계정 — 건너뜀")
        return result

    saved_session = load_session(email)

    # 세션 없음 + email이 아닌 경우 → 대시보드에서 쿠키 등록 필요
    if not saved_session and provider != "email":
        print(f"[{name}] 세션 없음 → 대시보드 '세션 등록' 탭에서 쿠키를 등록하세요.")
        return result

    browser = await playwright.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"]
    )
    context_kwargs = dict(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    )
    if saved_session:
        context_kwargs["storage_state"] = saved_session

    context = await browser.new_context(**context_kwargs)

    try:
        page = await context.new_page()
        logged_in = await is_logged_in(page)
        await page.close()

        # 세션 만료 + email 계정이면 재로그인 시도
        if not logged_in and provider == "email":
            print(f"[{name}] 세션 만료 → 이메일 재로그인 시도")
            logged_in = await email_login(context, account)

        # 세션 만료 + OAuth 계정이면 재등록 안내
        if not logged_in and provider != "email":
            print(f"[{name}] 세션 만료 → 대시보드 '세션 등록' 탭에서 쿠키를 다시 등록하세요.")
            delete_session(email)  # 만료된 세션 삭제
            result["session_exists"] = False

        result["login_success"] = logged_in

        if logged_in:
            print(f"[{name}] 사용량 수집 중...")
            page = await context.new_page()
            result["usage"] = await scrape_usage(page)
            await page.close()

            plan = result["usage"].get("plan", "Unknown")
            pct  = result["usage"].get("weekly_used_pct")
            print(f"[{name}] 완료 — 플랜: {plan}, 주간 사용률: {pct}%")

            state = await context.storage_state()
            save_session(email, state)
        else:
            print(f"[{name}] 로그인 실패, 건너뜀")

    finally:
        await context.close()
        await browser.close()

    return result


async def run_scraper() -> list[dict]:
    accounts = load_accounts()
    results  = []

    async with async_playwright() as p:
        for account in accounts:
            result = await process_account(p, account)
            results.append(result)
            await asyncio.sleep(1)

    USAGE_FILE.parent.mkdir(exist_ok=True)
    with open(USAGE_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n결과 저장 완료: {USAGE_FILE}")
    return results


def scrape(**_) -> list[dict]:
    """대시보드 호출용 동기 진입점 (별도 스레드 + 새 이벤트 루프)."""
    results = []
    errors  = []

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            results.extend(loop.run_until_complete(run_scraper()))
        except Exception as e:
            errors.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_run)
    t.start()
    t.join()

    if errors:
        raise errors[0]
    return results


if __name__ == "__main__":
    scrape()
