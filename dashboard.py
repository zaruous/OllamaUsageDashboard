"""
ollama.com 계정별 사용량 대시보드
실행: streamlit run dashboard.py
"""

import json
import time
from pathlib import Path
from datetime import datetime

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from scraper import (
    scrape,
    save_session_from_cookie_string,
    delete_session,
    has_session,
    SIGNIN_URL,
)

USAGE_FILE    = Path(__file__).parent / "usage_data.json"
ACCOUNTS_FILE = Path(__file__).parent / "account.json"

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Ollama 계정 사용량 대시보드",
    page_icon="🦙",
    layout="wide",
)

PLAN_COLORS = {
    "Free":    "#6366f1",
    "Pro":     "#10b981",
    "Max":     "#f59e0b",
    "Unknown": "#6b7280",
}

PROVIDER_META = {
    "google": {"icon": "🔵", "label": "Google",  "bg": "#4285F4"},
    "github": {"icon": "⚫", "label": "GitHub",  "bg": "#24292e"},
    "email":  {"icon": "📧", "label": "Email",   "bg": "#6b7280"},
}


# ─────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────
def load_usage_data() -> list[dict]:
    if USAGE_FILE.exists():
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def load_accounts() -> list[dict]:
    if ACCOUNTS_FILE.exists():
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_accounts(accounts: list[dict]):
    with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=2)


def get_pct(usage: dict, key: str = "weekly_used_pct") -> float:
    v = usage.get(key)
    return float(v) if v is not None else 0.0


def pct_color(pct: float) -> str:
    if pct >= 90:
        return "#ef4444"
    elif pct >= 70:
        return "#f59e0b"
    return "#10b981"


def provider_badge(provider: str) -> str:
    m = PROVIDER_META.get(provider, PROVIDER_META["email"])
    return (
        f"<span style='background:{m['bg']};color:white;"
        f"padding:2px 8px;border-radius:4px;font-size:12px'>"
        f"{m['icon']} {m['label']}</span>"
    )


def plan_badge(plan: str) -> str:
    color = PLAN_COLORS.get(plan, "#6b7280")
    return (
        f"<span style='background:{color};color:white;"
        f"padding:2px 8px;border-radius:4px;font-size:12px'>{plan}</span>"
    )


def active_badge(active: bool) -> str:
    if active:
        return "<span style='background:#10b981;color:white;padding:2px 8px;border-radius:4px;font-size:12px'>● 활성</span>"
    return "<span style='background:#9ca3af;color:white;padding:2px 8px;border-radius:4px;font-size:12px'>○ 비활성</span>"


# ─────────────────────────────────────────────
# 사이드바
# ─────────────────────────────────────────────
with st.sidebar:
    st.image("https://ollama.com/public/ollama.png", width=60)
    st.title("Ollama 대시보드")
    st.markdown("---")

    # 계정 활성/비활성 토글
    st.subheader("계정 관리")
    accounts = load_accounts()
    changed  = False
    for acc in accounts:
        col_a, col_b = st.columns([3, 1])
        col_a.markdown(
            f"**{acc['name']}**  \n"
            f"<small style='color:gray'>{acc['email']}</small>",
            unsafe_allow_html=True
        )
        new_active = col_b.toggle(
            "활성",
            value=acc.get("active", True),
            key=f"toggle_{acc['id']}",
            label_visibility="collapsed",
        )
        if new_active != acc.get("active", True):
            acc["active"] = new_active
            changed = True

    if changed:
        save_accounts(accounts)
        st.toast("계정 설정이 저장되었습니다.")

    st.markdown("---")

    st.info(
        "• Google/GitHub: 첫 실행 시 브라우저가 열립니다.\n"
        "• Email: 비밀번호로 자동 로그인합니다."
    )

    if st.button("🔄 데이터 새로고침", use_container_width=True, type="primary"):
        with st.spinner("사용량 수집 중... (OAuth 계정은 콘솔 창 확인)"):
            try:
                scrape()
                st.success("업데이트 완료!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"수집 실패: {e}")

    st.markdown("---")

    auto_refresh = st.toggle("⏱ 5분 자동 새로고침", value=True, key="auto_refresh_toggle")

    data_all = load_usage_data()
    if data_all:
        ts = data_all[0].get("scraped_at", "")
        if ts:
            dt = datetime.fromisoformat(ts)
            st.caption(f"마지막 수집: {dt.strftime('%Y-%m-%d %H:%M')}")
    if auto_refresh:
        st.caption("🟢 자동 새로고침 활성 (5분 간격)")
    else:
        st.caption("⭕ 자동 새로고침 비활성")

    st.caption("account.json 기반으로 ollama.com 사용량을 수집합니다.")


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────
st.title("🦙 Ollama 계정별 사용량 대시보드")

data = load_usage_data()
if not data:
    st.info("데이터가 없습니다. 사이드바에서 **데이터 새로고침** 버튼을 눌러 수집을 시작하세요.")
    st.stop()

# 분류
active_data   = [d for d in data if d.get("active", True)]
inactive_data = [d for d in data if not d.get("active", True)]
success_data  = [d for d in active_data if d.get("login_success")]
fail_data     = [d for d in active_data if not d.get("login_success")]

# ─────────────────────────────────────────────
# 요약 카드
# ─────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("전체 계정",   len(data))
c2.metric("활성",        len(active_data))
c3.metric("비활성",      len(inactive_data))
c4.metric("수집 성공",   len(success_data))
c5.metric("수집 실패",   len(fail_data),
          delta=f"-{len(fail_data)}" if fail_data else None,
          delta_color="inverse")

if success_data:
    avg_pct = sum(get_pct(d["usage"], "weekly_used_pct") for d in success_data) / len(success_data)
    st.markdown(
        f"<p style='color:gray;font-size:13px'>활성 계정 평균 주간 사용률: "
        f"<b style='color:{pct_color(avg_pct)}'>{avg_pct:.1f}%</b></p>",
        unsafe_allow_html=True
    )

st.markdown("---")

# ─────────────────────────────────────────────
# 탭
# ─────────────────────────────────────────────
tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📊 계정별 현황", "📈 사용량 비교 차트", "⚙️ 계정 목록", "🔑 계정 관리", "📋 원본 데이터"]
)


# ── 탭 1: 계정별 현황 ──────────────────────────
with tab1:
    if not success_data:
        st.warning("수집된 계정이 없습니다. 새로고침을 시도하세요.")
    else:
        cols = st.columns(min(len(success_data), 3))
        for idx, acc in enumerate(success_data):
            col      = cols[idx % len(cols)]
            usage    = acc.get("usage", {})
            plan     = usage.get("plan", "Unknown")
            w_pct    = get_pct(usage, "weekly_used_pct")
            s_pct    = get_pct(usage, "session_used_pct")
            provider = acc.get("provider", "google")

            with col:
                with st.container(border=True):
                    st.markdown(
                        f"<h4 style='margin:0 0 2px 0'>{acc['name']}</h4>"
                        f"<small style='color:gray'>{acc['email']}</small><br><br>"
                        f"{plan_badge(plan)}&nbsp;{provider_badge(provider)}&nbsp;"
                        f"{active_badge(acc.get('active', True))}",
                        unsafe_allow_html=True
                    )
                    st.markdown("")

                    # 주간 사용률 게이지
                    fig = go.Figure(go.Indicator(
                        mode="gauge+number",
                        value=w_pct,
                        number={"suffix": "%", "font": {"size": 28}},
                        gauge={
                            "axis": {"range": [0, 100]},
                            "bar":  {"color": pct_color(w_pct)},
                            "steps": [
                                {"range": [0,  70], "color": "#f0fdf4"},
                                {"range": [70, 90], "color": "#fefce8"},
                                {"range": [90,100], "color": "#fef2f2"},
                            ],
                            "threshold": {
                                "line": {"color": "#ef4444", "width": 3},
                                "value": 90
                            }
                        },
                        title={"text": "주간 사용률", "font": {"size": 13}}
                    ))
                    fig.update_layout(height=200, margin=dict(l=20, r=20, t=30, b=10))
                    st.plotly_chart(fig, use_container_width=True, key=f"gauge_{acc['id']}")

                    # 세션 / 주간 리셋 정보
                    m1, m2 = st.columns(2)
                    m1.metric("세션 사용률", f"{s_pct:.1f}%")
                    m2.metric("주간 사용률", f"{w_pct:.1f}%")

                    if usage.get("weekly_reset"):
                        st.caption(f"주간 리셋: {usage['weekly_reset']}")
                    if usage.get("session_reset"):
                        st.caption(f"세션 리셋: {usage['session_reset']}")

    # 수집 실패 계정
    if fail_data:
        st.markdown("---")
        st.subheader("⚠️ 수집 실패 계정")
        for acc in fail_data:
            st.error(
                f"**{acc['name']}** ({acc['email']}) — 로그인 실패  "
                f"[{PROVIDER_META.get(acc.get('provider','google'),{}).get('label','')}]"
            )

    # 비활성 계정
    if inactive_data:
        st.markdown("---")
        with st.expander(f"○ 비활성 계정 ({len(inactive_data)}개)"):
            for acc in inactive_data:
                st.markdown(
                    f"**{acc['name']}** ({acc['email']}) &nbsp;"
                    f"{provider_badge(acc.get('provider','google'))}",
                    unsafe_allow_html=True
                )


# ── 탭 2: 비교 차트 ────────────────────────────
with tab2:
    if not success_data:
        st.warning("수집된 계정이 없습니다.")
    else:
        def provider_label(p):
            return PROVIDER_META.get(p, {}).get("label", p.capitalize())

        df = pd.DataFrame([
            {
                "계정":           acc["name"],
                "이메일":         acc["email"],
                "로그인":         provider_label(acc.get("provider", "google")),
                "플랜":           acc["usage"].get("plan", "Unknown"),
                "주간사용률(%)":  get_pct(acc["usage"], "weekly_used_pct"),
                "세션사용률(%)":  get_pct(acc["usage"], "session_used_pct"),
                "주간리셋":       acc["usage"].get("weekly_reset", "—"),
                "세션리셋":       acc["usage"].get("session_reset", "—"),
            }
            for acc in success_data
        ])

        st.subheader("주간 사용률 비교")
        fig_bar = px.bar(
            df.sort_values("주간사용률(%)", ascending=True),
            x="주간사용률(%)", y="계정",
            orientation="h",
            color="주간사용률(%)",
            color_continuous_scale=["#10b981", "#f59e0b", "#ef4444"],
            range_color=[0, 100],
            text="주간사용률(%)",
            hover_data=["로그인", "플랜", "세션사용률(%)", "주간리셋"],
        )
        fig_bar.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
        fig_bar.update_layout(
            height=max(300, len(success_data) * 60),
            coloraxis_showscale=False,
            xaxis_range=[0, 115],
            margin=dict(l=10, r=50, t=20, b=20),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        col_a, col_b = st.columns(2)
        with col_a:
            st.subheader("플랜 분포")
            plan_df = df["플랜"].value_counts().reset_index()
            plan_df.columns = ["플랜", "계정 수"]
            fig_pie = px.pie(
                plan_df, names="플랜", values="계정 수",
                color="플랜", color_discrete_map=PLAN_COLORS, hole=0.4,
            )
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_b:
            st.subheader("로그인 방식 분포")
            login_df = df["로그인"].value_counts().reset_index()
            login_df.columns = ["로그인", "계정 수"]
            login_colors = {"Google": "#4285F4", "GitHub": "#24292e", "Email": "#6b7280"}
            fig_pie2 = px.pie(
                login_df, names="로그인", values="계정 수",
                color="로그인", color_discrete_map=login_colors, hole=0.4,
            )
            fig_pie2.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie2.update_layout(height=300, margin=dict(l=10, r=10, t=20, b=10))
            st.plotly_chart(fig_pie2, use_container_width=True)

        st.subheader("요약 테이블")
        st.dataframe(
            df.style.background_gradient(
                subset=["주간사용률(%)", "세션사용률(%)"], cmap="RdYlGn_r", vmin=0, vmax=100
            ).format({"주간사용률(%)": "{:.1f}%", "세션사용률(%)": "{:.1f}%"}),
            use_container_width=True,
            hide_index=True,
        )


# ── 탭 3: 계정 목록 (활성/비활성 전체) ─────────
with tab3:
    st.subheader("전체 계정 목록")
    accounts_now = load_accounts()
    rows = []
    for acc in accounts_now:
        matched = next((d for d in data if d["id"] == acc["id"]), {})
        rows.append({
            "ID":      acc["id"],
            "이름":    acc["name"],
            "이메일":  acc["email"],
            "로그인":  PROVIDER_META.get(acc.get("provider","google"),{}).get("label",""),
            "활성":    "● 활성" if acc.get("active", True) else "○ 비활성",
            "수집":    "✅ 성공" if matched.get("login_success") else ("⏸ 건너뜀" if not acc.get("active", True) else "❌ 실패"),
            "플랜":    matched.get("usage", {}).get("plan", "—"),
            "주간사용률": f"{get_pct(matched.get('usage', {}), 'weekly_used_pct'):.1f}%" if matched.get("login_success") else "—",
            "세션사용률": f"{get_pct(matched.get('usage', {}), 'session_used_pct'):.1f}%" if matched.get("login_success") else "—",
        })

    acc_df = pd.DataFrame(rows)
    st.dataframe(acc_df, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.caption("활성/비활성은 사이드바 토글로 변경할 수 있습니다.")


# ── 탭 4: 계정 관리 ────────────────────────────
with tab4:
    st.subheader("🔑 계정 관리")

    with st.expander("📋 쿠키 복사 방법 (Google/GitHub 계정)", expanded=False):
        st.markdown("""
**방법 1 — Network 탭 (권장, httpOnly 쿠키 포함)**
1. 아래 **로그인 페이지 열기** 버튼 클릭 → 일반 브라우저에서 로그인 완료
2. 로그인 후 그 페이지에서 `F12` → **Network** 탭 열기
3. 페이지 새로고침 (`F5`)
4. 목록에서 `ollama.com` 요청 아무거나 클릭
5. **Request Headers** 섹션에서 `cookie:` 항목 값을 전체 복사
6. 아래 텍스트 박스에 붙여넣기 후 **저장**

**방법 2 — Console (간단, httpOnly 쿠키 제외)**
1. 로그인 후 ollama.com 페이지에서 `F12` → **Console** 탭
2. `document.cookie` 입력 후 Enter
3. 출력된 값 전체 복사 → 아래 붙여넣기
        """)

    # ── 새 계정 추가 ──
    with st.expander("➕ 새 계정 추가", expanded=False):
        na_c1, na_c2 = st.columns(2)
        new_name     = na_c1.text_input("계정 이름 *", key="new_acc_name", placeholder="예) Google 계정 1")
        new_email    = na_c2.text_input("이메일 *",    key="new_acc_email", placeholder="example@gmail.com")
        na_c3, na_c4 = st.columns(2)
        new_provider = na_c3.selectbox("로그인 방식", ["google", "github", "email"], key="new_acc_provider")
        new_password = na_c4.text_input(
            "비밀번호 (email 전용)",
            type="password",
            key="new_acc_password",
            placeholder="provider가 email일 때만 입력",
        )
        if st.button("➕ 계정 추가", key="add_acc_btn", type="primary"):
            if not new_name.strip() or not new_email.strip():
                st.warning("이름과 이메일을 입력하세요.")
            else:
                accounts_for_add = load_accounts()
                if any(a["email"] == new_email.strip() for a in accounts_for_add):
                    st.error("이미 등록된 이메일입니다.")
                else:
                    new_id  = max((a["id"] for a in accounts_for_add), default=0) + 1
                    new_acc = {
                        "id":       new_id,
                        "name":     new_name.strip(),
                        "email":    new_email.strip(),
                        "provider": new_provider,
                        "active":   True,
                    }
                    if new_provider == "email" and new_password.strip():
                        new_acc["password"] = new_password.strip()
                    accounts_for_add.append(new_acc)
                    save_accounts(accounts_for_add)
                    st.success(f"✅ 계정 '{new_name.strip()}' 추가 완료!")
                    st.rerun()

    st.markdown("---")

    # ── 기존 계정 목록 ──
    accounts_now = load_accounts()

    for acc in accounts_now:
        provider   = acc.get("provider", "google")
        active     = acc.get("active", True)
        session_ok = has_session(acc["email"])

        with st.container(border=True):
            # 헤더 행: 이름 편집 | 활성 토글 | 저장 버튼
            hc1, hc2, hc3 = st.columns([4, 2, 1])
            edit_name   = hc1.text_input(
                "이름",
                value=acc["name"],
                key=f"edit_name_{acc['id']}",
                label_visibility="collapsed",
            )
            new_active  = hc2.toggle(
                "활성",
                value=active,
                key=f"edit_active_{acc['id']}",
            )
            if hc3.button("💾", key=f"save_acc_{acc['id']}", help="이름 / 활성 저장"):
                name_changed   = edit_name.strip() and edit_name.strip() != acc["name"]
                active_changed = new_active != active
                if name_changed or active_changed:
                    acc["name"]   = edit_name.strip() if edit_name.strip() else acc["name"]
                    acc["active"] = new_active
                    save_accounts(accounts_now)
                    st.toast(f"저장 완료: {acc['name']}")
                    st.rerun()
                else:
                    st.toast("변경 사항이 없습니다.")

            # 이메일 + 프로바이더 + 세션 상태
            sess_color = "#10b981" if session_ok else "#ef4444"
            sess_text  = "세션 있음 ✅" if session_ok else "세션 없음 ❌"
            st.markdown(
                f"<small style='color:gray'>{acc['email']}</small> &nbsp;"
                f"{provider_badge(provider)} &nbsp;"
                f"<span style='color:{sess_color};font-size:13px'>{sess_text}</span>",
                unsafe_allow_html=True,
            )

            # 세션 쿠키 (OAuth 계정)
            if provider == "email":
                st.info("Email 계정은 password로 자동 로그인합니다. 쿠키 등록 불필요.")
            else:
                btn_col, _ = st.columns([2, 3])
                with btn_col:
                    st.link_button("🌐 로그인 페이지 열기", SIGNIN_URL, use_container_width=True)

                cookie_input = st.text_area(
                    "쿠키 붙여넣기",
                    key=f"cookie_{acc['id']}",
                    placeholder="name1=value1; name2=value2; ...",
                    height=80,
                    label_visibility="collapsed",
                )

                sc1, sc2, _ = st.columns([1, 1, 2])
                with sc1:
                    if st.button("💾 세션 저장", key=f"save_sess_{acc['id']}", use_container_width=True):
                        if cookie_input.strip():
                            ok = save_session_from_cookie_string(acc["email"], cookie_input)
                            if ok:
                                st.session_state[f"session_saved_{acc['id']}"] = True
                                st.rerun()
                            else:
                                st.error("쿠키 형식이 올바르지 않습니다.")
                        else:
                            st.warning("쿠키를 먼저 붙여넣어 주세요.")
                if st.session_state.pop(f"session_saved_{acc['id']}", False):
                    st.success(f"✅ 세션 저장 완료!")

                with sc2:
                    if session_ok:
                        if st.button("🗑 세션 삭제", key=f"del_sess_{acc['id']}", use_container_width=True):
                            delete_session(acc["email"])
                            st.session_state[f"session_deleted_{acc['id']}"] = True
                            st.rerun()
                        if st.session_state.pop(f"session_deleted_{acc['id']}", False):
                            st.warning("세션이 삭제되었습니다.")

            # 계정 삭제
            with st.expander("⚠️ 계정 삭제"):
                st.warning(f"**{acc['name']}** 계정을 삭제하면 세션 파일도 함께 제거됩니다.")
                if st.button("🗑 계정 영구 삭제", key=f"del_acc_{acc['id']}", type="secondary"):
                    delete_session(acc["email"])
                    updated = [a for a in accounts_now if a["id"] != acc["id"]]
                    save_accounts(updated)
                    st.rerun()


# ─────────────────────────────────────────────
# 5분 자동 새로고침
# ─────────────────────────────────────────────
@st.fragment(run_every=300)
def _auto_refresh():
    if st.session_state.get("auto_refresh_toggle", True):
        try:
            scrape()
        except Exception:
            pass
        st.rerun()

_auto_refresh()


# ── 탭 5: 원본 데이터 ──────────────────────────
with tab5:
    for acc in data:
        active_mark = "● " if acc.get("active", True) else "○ "
        login_mark  = "✅" if acc.get("login_success") else (
                      "⏸" if not acc.get("active", True) else
                      ("🔑" if not acc.get("session_exists") else "❌")
        )
        with st.expander(
            f"{active_mark}{login_mark} {acc['name']} ({acc['email']})"
        ):
            st.json(acc)
