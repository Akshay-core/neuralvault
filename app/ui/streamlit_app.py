# Akshay-core
__author__ = "Akshay-core"

# FILE: app/ui/streamlit_app.py
import html
import importlib
import os
import secrets
import hashlib
import sys
import tempfile
import textwrap
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from analytics.usage_tracker import get_user_stats
from app.core.document_intelligence import analyze_patterns, list_document_profiles
from app.database.sqlite_db import get_conn, init_db
from app.ingestion import file_manager
from app.memory.adaptive_memory import (
    add_memory,
    delete_memory,
    feedback_summary,
    list_memory_conflicts,
    list_memories,
    save_feedback,
)
from app.memory.memory_graph import build_memory_graph, search_everything
from app.memory.session_memory import (
    clear_session,
    create_conversation,
    delete_conversation,
    delete_message,
    fork_conversation,
    get_or_create_default_conversation,
    get_persisted_history,
    list_conversations,
    load_history_from_db,
    set_conversation_pinned,
    storage_user_id,
)
from app.memory.workspaces import (
    create_workspace,
    get_or_create_workspace,
    list_workspaces,
    workspace_label,
)
from app.models.ollama_client import is_ollama_running, list_available_models
from app.config import MODEL_PROFILES
from app.ownership import OWNER_NAME, export_header, is_local_first, signature_label
from app.utils.device_check import get_performance_budget
from orchestration.ai_kernel import process
from plugins.plugin_manager import get_plugin_manager
from runtime.device_profiler import profile as sys_profile
from security.prompt_firewall import analyze_risk
from users.auth import create_user, login, logout, validate_session


init_db()

st.set_page_config(
    page_title="Baby-GPT",
    page_icon="app/ui/assets/Baby-gpt.svg",
    layout="wide",
    initial_sidebar_state="expanded",
)


st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
  color-scheme: dark;
  color: #e6edf3;
  background: #0b0f17;
  font-family: Inter, sans-serif;
}

html, body, [class*="css"] { font-family: Inter, sans-serif; }
.stApp {
  background: #0b0f17;
  color: #e6edf3;
}
#MainMenu, footer, header, [data-testid="collapsedControl"] { visibility: hidden; }

[data-testid="stSidebar"] {
  background: #20232e !important;
  color: #e6edf3 !important;
  border-right: 1px solid rgba(255,255,255,.08);
  min-width: 250px;
}
[data-testid="stSidebar"] .css-1d391kg { background: transparent; }

.block-container { padding-top: 1rem; max-width: 1320px; }

.stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
  border-radius: 16px !important;
  background: #1b202a !important;
  border: 1px solid rgba(255,255,255,.12) !important;
  color: #e6edf3 !important;
}

.stButton > button, .stDownloadButton > button {
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,.1);
  background: #34394f;
  color: #e6edf3;
  padding: .88rem 1rem;
}

.stButton > button[kind="primary"], .stFormSubmitButton button[kind="primary"] {
  background: #4d57ce;
  color: #fff;
}

.stChatMessage {
  border-radius: 18px;
  padding: 1rem 1.1rem;
  background: rgba(255,255,255,.06);
  border: 1px solid rgba(255,255,255,.08);
  color: #e6edf3;
}
.stChatMessage[data-testid="stHorizontalBlock"] {
  margin-bottom: 0.75rem;
}

.stChatMessage .markdown-text-container {
  color: #e6edf3;
}

.css-1v0mbdj.e16nr0p32 {
  padding: 0 !important;
}

.sidebar-header {
  margin-bottom: 1rem;
}
.sidebar-heading {
  font-size: 0.95rem;
  font-weight: 700;
  margin-bottom: .6rem;
  color: #f8fbff;
}
.sidebar-note {
  color: #9aa4b7;
  font-size: .88rem;
  margin-bottom: 1rem;
}
.sidebar-group {
  margin-bottom: 1.25rem;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 1rem;
  margin-bottom: 1rem;
}
.chat-title {
  margin: 0;
  font-size: 2rem;
  font-weight: 700;
}
.chat-subtitle {
  margin: .25rem 0 0;
  color: #9aa4b7;
  font-size: .95rem;
}

.message-footer {
  margin-top: 1rem;
  color: #9aa4b7;
  font-size: .85rem;
}

[data-testid="stAppViewContainer"] {
  padding-left: 0 !important;
}

@media (max-width: 900px) {
  .stSidebar { width: 100% !important; }
}
</style>
""",
    unsafe_allow_html=True,
)


def ss_init():
    defaults = {
        "logged_in": False,
        "user_id": None,
        "username": None,
        "session_token": None,
        "active_tab": "chat",
        "mode_override": "",
        "last_result": None,
        "active_conversation_id": "",
        "active_workspace_id": "core",
        "theme": "dark",
        "sidebar_compact": False,
        "chat_render_limit": 18,
        "right_panel_tab": "Claim Validation",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


ss_init()


def render_theme_overrides():
    if st.session_state.theme == "light":
        st.markdown(
            """
<style>
:root {
  --bg: #F7F8FA;
  --bg-2: #FFFFFF;
  --bg-3: #EEF2F7;
  --panel: rgba(255,255,255,.94);
  --panel-2: rgba(10,18,28,.035);
  --line: rgba(20,31,45,.12);
  --text: #141C27;
  --muted: #667386;
  --blue: #236BFE;
  --blue-soft: #4F8CFF;
  --green: #19A974;
  --green-soft: #38C998;
  --ivory: #141C27;
  --ivory-2: #344256;
  --sand: #D8DEE8;
  --amber: #B7791F;
  --red: #C24141;
  --shadow: 0 16px 46px rgba(20,31,45,.10);
}
[data-testid="stSidebar"] { background: rgba(255,255,255,.92); }
[data-testid="stSidebar"] * { color: var(--text); }
[data-testid="stChatMessage"], .pipeline-panel { background: rgba(255,255,255,.86); }
</style>
""",
            unsafe_allow_html=True,
        )


def render_atmosphere():
    return
    st.markdown(
        """
<div class="knowledge-atmosphere" aria-hidden="true">
  <span></span><span></span><span></span><span></span>
  <span></span><span></span><span></span><span></span>
</div>
""",
        unsafe_allow_html=True,
    )


def activate_local_mode():
    if not is_local_first() or st.session_state.logged_in:
        return
    st.session_state.logged_in = True
    st.session_state.user_id = "global"
    st.session_state.username = OWNER_NAME
    st.session_state.session_token = "local-first"
    st.session_state.active_workspace_id = get_or_create_workspace("global", st.session_state.active_workspace_id)
    st.session_state.active_conversation_id = get_or_create_default_conversation(
        "global",
        workspace_id=st.session_state.active_workspace_id,
    )


@st.cache_data(ttl=8, show_spinner=False)


def cached_ollama_status():
    return is_ollama_running()


@st.cache_data(ttl=20, show_spinner=False)


def cached_available_models():
    return list_available_models()


def verify_session():
    token = st.session_state.get("session_token")
    if token == "local-first" and is_local_first():
        return True
    if not token:
        return False
    now = time.time()
    if (
        st.session_state.get("session_valid_until", 0) > now
        and st.session_state.get("session_checked_token") == token
    ):
        return True

    result = validate_session(token)
    valid = result.get("valid", False)
    if valid:
        st.session_state.session_valid_until = now + 60
        st.session_state.session_checked_token = token
    return valid


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_txt_export(history: list) -> bytes:
    lines = [export_header("chat export"), ""]
    for row in history:
        lines.append(f"[{row.get('timestamp', '')}] {row.get('role', '').upper()}")
        lines.append(row.get("content", ""))
        if row.get("model_used"):
            lines.append(f"Model: {row['model_used']}")
        lines.append("")
    return "\n".join(lines).encode("utf-8")


def make_pdf_export(history: list) -> bytes:
    text = make_txt_export(history).decode("utf-8", errors="replace")
    wrapped = []
    for line in text.splitlines():
        wrapped.extend(textwrap.wrap(line, width=92) or [""])
    pages = [wrapped[i : i + 42] for i in range(0, len(wrapped), 42)] or [[]]

    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = []
    next_id = 3
    font_id = 3 + (2 * len(pages))
    for page in pages:
        stream_lines = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        for line in page:
            stream_lines.append(f"({escape_pdf_text(line[:110])}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream = "\n".join(stream_lines).encode("latin-1", errors="replace")
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        kids.append(f"{page_id} 0 R")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream")
    objects.insert(1, f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    info_id = len(objects) + 1
    objects.append(
        "<< "
        f"/Title ({escape_pdf_text('AI Second Brain Export')}) "
        f"/Author ({escape_pdf_text(OWNER_NAME)}) "
        f"/Creator ({escape_pdf_text(signature_label())}) "
        f"/Subject ({escape_pdf_text(export_header('PDF export'))}) "
        ">>"
    )

    pdf = ["%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(sum(len(part.encode("latin-1")) for part in pdf))
        pdf.append(f"{i} 0 obj\n{obj}\nendobj\n")
    xref_at = sum(len(part.encode("latin-1")) for part in pdf)
    pdf.append(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.append(f"{offset:010d} 00000 n \n")
    pdf.append(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info {info_id} 0 R >>\nstartxref\n{xref_at}\n%%EOF")
    return "".join(pdf).encode("latin-1", errors="replace")


def mode_label(mode: str) -> str:
    if (mode or "").startswith("model:"):
        return "Model " + mode.split(":", 1)[1]
    return {
        "": "Auto",
        "micro": "Safe",
        "balanced": "Balanced",
        "heavy": "Brutal",
        "study": "Study",
        "research": "Research",
        "analysis": "Deep Analysis",
        "coding": "Coding",
    }.get(mode, mode.title())


def logo_path() -> str:
    return str(Path(__file__).parent / "assets" / "Baby-gpt.svg")


def render_top_bar():
    ws_name = workspace_label(st.session_state.user_id, st.session_state.active_workspace_id)
    st.markdown(
        f"""
<div class="akx-topbar">
  <div class="brand" style="margin:0">
    <img class="brand-logo" src="app/ui/assets/Baby-gpt.svg" />
    <div>
      <div class="brand-title">Baby-GPT</div>
      <div class="brand-sub">{html.escape(ws_name)} · local chat-first assistant</div>
    </div>
  </div>
  <div style="display:flex; gap:.45rem; align-items:center;">
    <div class="akx-mode-pill">{html.escape(mode_label(st.session_state.mode_override))}</div>
    <div class="akx-mode-pill">{html.escape(st.session_state.theme.title())}</div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        """
<div style='margin-top:0.8rem; display:flex; gap:0.5rem; flex-wrap:wrap;'>
  <span style='color: var(--muted); font-size: .92rem;'>Fast local chat with document grounding and memory.</span>
</div>
""",
        unsafe_allow_html=True,
    )


def render_health_strip():
    p = sys_profile()
    ollama_ok = cached_ollama_status()
    perf = get_performance_budget()
    models = cached_available_models() if ollama_ok else []
    model_text = ", ".join(m.split(":")[0] for m in models[:3]) if models else "No local models"
    ollama_text = "Online" if ollama_ok else "Offline"
    ollama_class = "status-clean" if ollama_ok else "status-critical"

    st.markdown(
        f"""
<div class="stat-grid">
  <div class="stat-card">
    <div class="stat-label">Ollama</div>
    <div class="stat-value {ollama_class}">{ollama_text}</div>
    <div class="stat-note">{html.escape(model_text)}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Mode</div>
    <div class="stat-value">{mode_label(st.session_state.mode_override)}</div>
    <div class="stat-note">Recommended: {html.escape(perf["recommended_model"])}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">CPU</div>
    <div class="stat-value">{p["cpu_usage_pct"]:.0f}%</div>
    <div class="bar"><span style="width:{min(p["cpu_usage_pct"], 100)}%"></span></div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Memory</div>
    <div class="stat-value">{p["ram_used_pct"]:.0f}%</div>
    <div class="bar"><span style="width:{min(p["ram_used_pct"], 100)}%"></span></div>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def render_engine_overlay(meta: dict):
    confidence = meta.get("confidence") or {}
    timings = meta.get("timings") or {}
    knowledge = meta.get("knowledge_graph") or {}
    concepts = knowledge.get("confidence_map") or []
    items = [
        ("Mode", mode_label(st.session_state.mode_override)),
        ("Model", meta.get("model", "local")),
        ("Latency", f"{meta.get('response_time_ms', 0)}ms"),
        ("Token/s", f"{timings.get('token_per_second', 0):.1f}"),
        ("Chunks", str(meta.get("chunks_used", 0))),
        ("Concepts", str(len(concepts))),
        ("Confidence", f"{confidence.get('level', 'n/a')} {confidence.get('score', '')}"),
    ]
    html_items = "".join(
        f"<span class='engine-pill'><strong>{html.escape(label)}</strong> {html.escape(value)}</span>"
        for label, value in items
    )
    st.markdown(f"<div class='engine-overlay'>{html_items}</div>", unsafe_allow_html=True)
    if concepts:
        st.caption(
            "Knowledge confidence: "
            + ", ".join(
                f"{c.get('concept')} ({c.get('confidence', 0):.2f})"
                for c in concepts[:5]
            )
        )


def render_memory_graph_visual(user_id: str, workspace_id: str = ""):
    graph = build_memory_graph(user_id, workspace_id=workspace_id)
    if not graph.get("topics"):
        st.info("Memory graph will appear after chats or document ingestion.")
        return
    max_weight = max(t["weight"] for t in graph["topics"]) or 1
    bars = []
    for topic in graph["topics"][:12]:
        width = max(8, int((topic["weight"] / max_weight) * 100))
        bars.append(
            "<div class='graph-bar'>"
            f"<span>{html.escape(topic['topic'])}</span>"
            f"<div class='bar'><span class='graph-bar-fill' style='width:{width}%'></span></div>"
            f"<span>{topic['weight']}</span>"
            "</div>"
        )
    st.markdown("".join(bars), unsafe_allow_html=True)
    if graph.get("edges"):
        edge_text = "  ".join(
            f"{edge['from']} -> {edge['to']} ({edge['weight']})"
            for edge in graph["edges"][:6]
        )
        st.caption(edge_text)


def render_pipeline(rows: list, confidence: dict = None, sources: list = None):
    rows_html = []
    for row in rows[-8:]:
        rows_html.append(
            f"<div class='pipeline-row'><span>{html.escape(row.get('label', 'Working'))}</span>"
            f"<span>{html.escape(row.get('meta', ''))}</span></div>"
        )
    conf_html = ""
    if confidence:
        level = confidence.get("level", "low")
        cls = "status-clean" if level == "high" else "status-watch" if level == "medium" else "status-critical"
        conf_html = (
            f"<div class='pipeline-row'><span>Grounding</span>"
            f"<span class='{cls}'>{html.escape(level)} {confidence.get('score', 0)}</span></div>"
        )
        if confidence.get("validation"):
            conf_html += (
                f"<div class='pipeline-row'><span>Validation</span>"
                f"<span>{html.escape(str(confidence['validation'])[:72])}</span></div>"
            )
    source_html = ""
    if sources:
        chips = []
        for src in sources[:5]:
            preview = html.escape(str(src.get("preview", ""))[:180])
            chips.append(
                f"<span class='source-chip' title='{preview}'>{html.escape(src.get('filename') or 'source')}"
                f" {html.escape(str(src.get('priority_score') or src.get('score', '')))}</span>"
            )
        source_html = "<div style='margin-top:.45rem'>" + "".join(chips) + "</div>"
    st.markdown(
        "<div class='pipeline-panel'>"
        + "".join(rows_html)
        + conf_html
        + source_html
        + "</div>",
        unsafe_allow_html=True,
    )


def render_claim_blocks(validation: dict):
    claim_graph = (validation or {}).get("claim_graph") or {}
    claims = claim_graph.get("claims") or []
    links = claim_graph.get("evidence_links") or []
    links_by_claim = {}
    for link in links:
        links_by_claim.setdefault(link.get("claim_id"), []).append(link)
    if not claims:
        st.caption("Claim validation appears after an answer is generated.")
        return
    metrics = claim_graph.get("metrics") or {}
    width = int((metrics.get("retrieval_confidence") or 0) * 100)
    st.markdown(
        f"<span class='confidence-bar'><span style='width:{width}%'></span></span>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"retrieval confidence {metrics.get('retrieval_confidence', 0):.2f} · "
        f"unsupported {metrics.get('unsupported_ratio', 0):.2f} · "
        f"contradictions {metrics.get('contradiction_count', 0)}"
    )
    for claim in claims[:8]:
        confidence = claim.get("confidence", "low")
        cls = "claim-low" if confidence == "low" else "claim-medium" if confidence == "medium" else ""
        evidence = links_by_claim.get(claim.get("id"), [])[:2]
        evidence_html = "".join(
            "<div class='evidence-line'>"
            f"{html.escape(e.get('filename') or 'SQLite chunk')} · "
            f"support {e.get('support_score', 0)} · span {e.get('span_alignment', 0)}"
            "</div>"
            for e in evidence
        )
        st.markdown(
            f"""
<div class="claim-row {cls}">
  <strong>{html.escape(claim.get('verdict', confidence).title())}</strong>
  <div>{html.escape(claim.get('claim', ''))}</div>
  <div class="evidence-line">strength {claim.get('evidence_strength', 0)} · contradiction {claim.get('contradiction_score', 0)}</div>
  {evidence_html}
</div>
""",
            unsafe_allow_html=True,
        )


def render_intelligence_panel(result: dict | None):
    st.markdown("<div class='right-panel'>", unsafe_allow_html=True)
    tab = st.session_state.get("right_panel_tab", "Claim Validation")
    st.markdown(f"#### {tab}")
    if not result:
        st.caption("This panel wakes up when the workspace has evidence, memory, or a fresh response.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    validation = result.get("validation") or {}
    if tab == "Claim Validation":
        render_claim_blocks(validation)
    elif tab == "Evidence Graph":
        sources = result.get("source_chunks") or result.get("sources") or []
        if not sources:
            st.caption("No evidence chunks were attached to the latest response.")
        for src in sources[:8]:
            if isinstance(src, str):
                st.markdown(f"<span class='source-chip'>{html.escape(src)}</span>", unsafe_allow_html=True)
            else:
                st.markdown(
                    f"<span class='source-chip' title='{html.escape(str(src.get('preview', ''))[:220])}'>"
                    f"{html.escape(src.get('filename') or src.get('chunk_id') or 'source')} "
                    f"{html.escape(str(src.get('score', '')))}</span>",
                    unsafe_allow_html=True,
                )
    elif tab == "Retrieval Trace":
        confidence = result.get("confidence") or {}
        timings = result.get("timings") or {}
        st.json({"confidence": confidence, "timings": timings, "model": result.get("model")})
    elif tab == "System Audit":
        stats = get_user_stats(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
        pipeline = stats.get("pipeline") or {}
        st.metric("Grounding", f"{pipeline.get('grounding_score') or 0:.2f}")
        st.metric("Unsupported", f"{pipeline.get('validation_unsupported') or 0:.2f}")
        st.caption("Audit data is loaded only when this panel is selected.")
    elif tab == "Memory Inspector":
        memories = list_memories(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)[:8]
        conflicts = list_memory_conflicts(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
        st.metric("Open conflicts", sum(1 for c in conflicts if c.get("status") == "open"))
        for memory in memories:
            st.markdown(
                f"<div class='settings-row'><strong>{html.escape(memory.get('title', 'Memory'))}</strong><br>"
                f"{html.escape(memory.get('layer', 'semantic'))} · {html.escape(memory.get('status', 'active'))} · "
                f"decay {memory.get('decay_score', 1)}</div>",
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)


def render_login():
    left, center, right = st.columns([1, 1.25, 1])
    with center:
        st.markdown("<div style='height:6vh'></div>", unsafe_allow_html=True)
        st.markdown(
            """
<div class="hero">
  <div class="brand">
    <img class="brand-logo" src="app/ui/assets/Baby-gpt.svg" />
    <div>
      <div class="brand-title">Baby-GPT</div>
      <div class="brand-sub">Private local intelligence for documents, memory, and tools</div>
    </div>
  </div>
  <h1>Your local command center.</h1>
  <p>Fast answers, safer prompts, document search, plugins, and persistent memory on your machine.</p>
</div>
""",
            unsafe_allow_html=True,
        )
        tab_login, tab_signup = st.tabs(["Sign In", "Create Account"])

        with tab_login:
            uname = st.text_input("Username", key="login_user", placeholder="your_username")
            passwd = st.text_input("Password", type="password", key="login_pass", placeholder="password")
            if st.button("Sign In", key="btn_login", type="primary", use_container_width=True):
                if uname and passwd:
                    result = login(uname, passwd)
                    if result["success"]:
                        st.session_state.logged_in = True
                        st.session_state.user_id = result["user_id"]
                        st.session_state.username = result["username"]
                        st.session_state.session_token = result["token"]
                        st.session_state.active_conversation_id = get_or_create_default_conversation(result["user_id"])
                        load_history_from_db(result["user_id"], conversation_id=st.session_state.active_conversation_id)
                        st.rerun()
                    st.error(result.get("error", "Login failed"))
                else:
                    st.warning("Enter username and password.")

        with tab_signup:
            new_user = st.text_input("Choose username", key="reg_user")
            new_pass = st.text_input("Choose password", type="password", key="reg_pass")
            if st.button("Create Account", key="btn_register", use_container_width=True):
                if new_user and new_pass:
                    result = create_user(new_user, new_pass)
                    if result["success"]:
                        st.success("Account created. Sign in to continue.")
                    else:
                        st.error(result.get("error", "Registration failed"))
                else:
                    st.warning("Fill in all fields.")


def render_sidebar():
    with st.sidebar:
        st.markdown(
            f"""
<div class='sidebar-header'>
  <div class='sidebar-heading'>Baby-GPT</div>
  <div class='sidebar-note'>A local ChatGPT-style assistant for your documents.</div>
</div>
""",
            unsafe_allow_html=True,
        )

        if st.button("+ New chat", use_container_width=True, key="sidebar_new_chat"):
            st.session_state.active_conversation_id = create_conversation(
                st.session_state.user_id,
                workspace_id=st.session_state.active_workspace_id,
            )
            st.rerun()

        conversations = list_conversations(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
        if conversations:
            labels = {
                f"{'* ' if c.get('pinned') else ''}{c['title'][:32]}": c["id"]
                for c in conversations
            }
            current_label = next(
                (label for label, cid in labels.items() if cid == st.session_state.active_conversation_id),
                next(iter(labels)),
            )
            selected_label = st.selectbox(
                "Chats",
                list(labels.keys()),
                index=list(labels.keys()).index(current_label),
                key="sidebar_switch_chat",
                label_visibility="collapsed",
            )
            selected_id = labels[selected_label]
            if selected_id != st.session_state.active_conversation_id:
                st.session_state.active_conversation_id = selected_id
                load_history_from_db(st.session_state.user_id, conversation_id=selected_id)
                st.rerun()

        with st.expander("Workspace & docs", expanded=False):
            workspaces = list_workspaces(st.session_state.user_id)
            if not st.session_state.active_workspace_id:
                st.session_state.active_workspace_id = get_or_create_workspace(st.session_state.user_id, "core")
            if workspaces:
                labels = {f"{w['name']} ({w['docs']} docs)": w["id"] for w in workspaces}
                current_label = next(
                    (label for label, wid in labels.items() if wid == st.session_state.active_workspace_id),
                    next(iter(labels)),
                )
                selected_workspace = st.selectbox(
                    "Workspace",
                    list(labels.keys()),
                    index=list(labels.keys()).index(current_label),
                    key="sidebar_workspace_select",
                    label_visibility="collapsed",
                )
                selected_workspace_id = labels[selected_workspace]
                if selected_workspace_id != st.session_state.active_workspace_id:
                    st.session_state.active_workspace_id = selected_workspace_id
                    st.session_state.active_conversation_id = get_or_create_default_conversation(
                        st.session_state.user_id,
                        workspace_id=selected_workspace_id,
                    )
                    st.rerun()
            new_ws = st.text_input("New workspace", placeholder="Interview prep", key="sidebar_new_workspace")
            if new_ws and st.button("Create workspace", use_container_width=True, key="sidebar_create_workspace"):
                st.session_state.active_workspace_id = create_workspace(st.session_state.user_id, new_ws)
                st.session_state.active_conversation_id = get_or_create_default_conversation(
                    st.session_state.user_id,
                    workspace_id=st.session_state.active_workspace_id,
                )
                st.rerun()

            uploaded = st.file_uploader(
                "Upload PDF / txt / md",
                type=["pdf", "txt", "md"],
                accept_multiple_files=True,
                key="sidebar_doc_uploader",
            )
            if uploaded and st.button("Ingest files", use_container_width=True, key="sidebar_ingest_files"):
                progress = st.progress(0)
                results = []
                for i, f in enumerate(uploaded):
                    tmp_path = None
                    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(f.name).suffix) as tmp:
                        tmp.write(f.getbuffer())
                        tmp_path = tmp.name
                    try:
                        result = file_manager.ingest_file(
                            tmp_path,
                            user_id=st.session_state.user_id,
                            original_name=f.name,
                            workspace_id=st.session_state.active_workspace_id,
                        )
                        results.append((f.name, result))
                    except Exception as exc:
                        results.append((f.name, {"success": False, "error": str(exc)}))
                    finally:
                        progress.progress((i + 1) / len(uploaded))
                        if tmp_path and os.path.exists(tmp_path):
                            os.unlink(tmp_path)
                for fname, result in results:
                    if result.get("success"):
                        st.success(f"{fname}: {result['chunks']} chunks ingested")
                    else:
                        st.error(f"{fname}: {result.get('error', 'Failed to ingest')}")

        with st.expander("Model settings", expanded=False):
            mode = st.selectbox(
                "Mode",
                ["Auto", "Fast Chat", "Study", "Research", "Deep Analysis", "Coding"],
                index=["Auto", "Fast Chat", "Study", "Research", "Deep Analysis", "Coding"].index(
                    {"": "Auto", "micro": "Fast Chat", "balanced": "Study", "heavy": "Research", "study": "Research", "research": "Research", "analysis": "Deep Analysis", "coding": "Coding"}.get(st.session_state.mode_override, "Auto")
                ),
                key="sidebar_mode_select",
                label_visibility="collapsed",
            )
            st.session_state.mode_override = {
                "Auto": "",
                "Fast Chat": "micro",
                "Study": "balanced",
                "Research": "heavy",
                "Deep Analysis": "heavy",
                "Coding": "heavy",
            }[mode]
            installed_models = cached_available_models() if cached_ollama_status() else []
            if installed_models:
                chosen_model = st.selectbox(
                    "Prefer model",
                    ["Auto route"] + installed_models,
                    key="sidebar_model_switcher",
                    label_visibility="collapsed",
                )
                if chosen_model != "Auto route":
                    st.session_state.mode_override = "model:" + chosen_model

        if st.button("Sign out", use_container_width=True, key="sidebar_sign_out"):
            if st.session_state.session_token == "local-first":
                st.info("Local-first mode keeps the workspace open on this machine.")
            else:
                logout(st.session_state.session_token)
                for key in ["logged_in", "user_id", "username", "session_token", "active_conversation_id"]:
                    st.session_state[key] = None
            st.rerun()


def render_chat():
    ws_name = workspace_label(st.session_state.user_id, st.session_state.active_workspace_id)
    st.markdown(
        f"""
<div class="chat-header">
  <div>
    <h1 class="chat-title">Chat</h1>
    <p class="chat-subtitle">{html.escape(ws_name)} · Ask questions and get grounded answers.</p>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    conversation_id = st.session_state.active_conversation_id or get_or_create_default_conversation(
        st.session_state.user_id,
        workspace_id=st.session_state.active_workspace_id,
    )
    st.session_state.active_conversation_id = conversation_id
    history = get_persisted_history(st.session_state.user_id, limit=120, conversation_id=conversation_id)
    if not history:
        st.info("Start a new chat. Upload documents in the sidebar and ask your first question below.")
    for msg in history:
        role = "user" if msg["role"] == "user" else "assistant"
        with st.chat_message(role):
            st.markdown(msg["content"])
            if msg.get("model_used") and role == "assistant":
                st.caption(f"Model: {msg['model_used']}")

    query = st.chat_input("Ask Baby-GPT anything...")
    if query:
        risk = analyze_risk(query)
        with st.chat_message("user"):
            st.markdown(query)
            if risk["level"] != "clean":
                signals = ", ".join(risk["signals"]) if risk["signals"] else "review"
                danger = "status-watch" if risk["level"] != "critical" else "status-critical"
                st.markdown(
                    f'<span class="risk-pill"><span class="{danger}">Risk {risk["score"]}/100</span> {html.escape(signals)}</span>',
                    unsafe_allow_html=True,
                )

        with st.chat_message("assistant"):
            status = st.status("Thinking... routing through local memory and retrieval.", expanded=True)
            started = time.time()
            result = process(
                query=query,
                user_id=st.session_state.user_id,
                mode_override=st.session_state.mode_override,
                stream=True,
                conversation_id=conversation_id,
                workspace_id=st.session_state.active_workspace_id,
            )
            elapsed = int((time.time() - started) * 1000)
            if hasattr(result, "__iter__") and not isinstance(result, dict):
                buffer = []
                final_meta = {}
                pipeline_box = st.empty()
                def token_stream():
                    nonlocal final_meta
                    for item in result:
                        if not isinstance(item, dict):
                            buffer.append(str(item))
                            yield str(item)
                            continue
                        event_type = item.get("type", "")
                        if event_type == "token":
                            token = item.get("data", {}).get("token", item.get("label", ""))
                            buffer.append(token)
                            yield token
                        elif event_type == "done":
                            final_meta = item.get("data", {})
                            status.write(f"Completed in {final_meta.get('response_time_ms', elapsed)}ms.")
                        else:
                            label = item.get("label", "")
                            status.write(label)
                answer = st.write_stream(token_stream())
                final_answer = "".join(buffer).strip()
                final_meta.setdefault("response_time_ms", elapsed)
                final_meta.setdefault("model", "streamed")
                st.session_state.last_result = {
                    "query": query,
                    "answer": final_answer,
                    "sources": final_meta.get("sources", []),
                    "source_chunks": final_meta.get("chunks", []),
                    "model": final_meta.get("model", "streamed"),
                    "confidence": final_meta.get("confidence", {}),
                    "validation": final_meta.get("validation", {}),
                    "timings": final_meta.get("timings", {}),
                }
                if final_meta.get("sources"):
                    st.markdown("#### Sources")
                    for src in final_meta.get("sources", [])[:5]:
                        st.markdown(f"- {html.escape(str(src))}")
                status.update(label="Ready", state="complete", expanded=False)
            elif isinstance(result, dict):
                st.markdown(result.get("answer", ""))
                st.session_state.last_result = result
                if result.get("sources"):
                    st.markdown("#### Sources")
                    for src in result.get("sources", [])[:5]:
                        st.markdown(f"- {html.escape(str(src))}")
                status.update(label="Ready", state="complete", expanded=False)
            else:
                st.error("The AI pipeline returned an unexpected response.")
                status.update(label="Response failed", state="error", expanded=True)
        st.rerun()

    if st.session_state.get("last_result"):
        with st.expander("Response tools", expanded=False):
            last = st.session_state.last_result
            st.caption("Save feedback to improve local behavior.")
            c1, c2, c3 = st.columns([1, 1, 2])
            notes = c3.text_input("Correction or preference", key="feedback_notes", placeholder="Keep replies shorter, focus on document sources.")
            if c1.button("Helpful", use_container_width=True):
                save_feedback(
                    st.session_state.user_id,
                    st.session_state.active_workspace_id,
                    st.session_state.active_conversation_id,
                    last.get("query", ""),
                    last.get("answer", ""),
                    1,
                    notes,
                    last.get("sources", []),
                )
                st.success("Feedback saved.")
            if c2.button("Needs Fix", use_container_width=True):
                save_feedback(
                    st.session_state.user_id,
                    st.session_state.active_workspace_id,
                    st.session_state.active_conversation_id,
                    last.get("query", ""),
                    last.get("answer", ""),
                    -1,
                    notes,
                    last.get("sources", []),
                )
                st.warning("Feedback saved.")


def render_history():
    st.markdown("### History, Export, and Cleanup")
    conversation_id = st.session_state.active_conversation_id or get_or_create_default_conversation(
        st.session_state.user_id,
        workspace_id=st.session_state.active_workspace_id,
    )
    history = get_persisted_history(st.session_state.user_id, limit=500, conversation_id=conversation_id)
    col1, col2, col3 = st.columns([1, 1, 1])
    with col1:
        st.download_button("Export TXT", data=make_txt_export(history), file_name="ai-second-brain-history.txt", mime="text/plain", use_container_width=True)
    with col2:
        st.download_button("Export PDF", data=make_pdf_export(history), file_name="ai-second-brain-history.pdf", mime="application/pdf", use_container_width=True)
    with col3:
        if st.button("Delete All History", use_container_width=True):
            clear_session(st.session_state.user_id, conversation_id=conversation_id)
            st.success("History deleted.")
            st.rerun()

    st.divider()
    if not history:
        st.info("History is empty.")
        return
    for row in reversed(history):
        with st.expander(f"{row['timestamp']} - {row['role']}"):
            st.markdown(row["content"])
            if row.get("model_used"):
                st.caption(f"Model: {row['model_used']}")
            if st.button("Delete message", key=f"del_{row['id']}"):
                delete_message(st.session_state.user_id, row["id"], conversation_id=conversation_id)
                st.rerun()


def render_documents():
    importlib.reload(file_manager)
    st.markdown("### Documents")
    uploaded = st.file_uploader(
        "Upload PDFs, text, or Markdown",
        type=["pdf", "txt", "md"],
        accept_multiple_files=True,
        key="doc_uploader",
    )

    if uploaded and st.button("Ingest All Files", type="primary"):
        progress = st.progress(0)
        results = []
        for i, f in enumerate(uploaded):
            tmp_path = None
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(f.name).suffix) as tmp:
                tmp.write(f.getbuffer())
                tmp_path = tmp.name
            try:
                result = file_manager.ingest_file(
                    tmp_path,
                    user_id=st.session_state.user_id,
                    original_name=f.name,
                    workspace_id=st.session_state.active_workspace_id,
                )
                results.append((f.name, result))
            except Exception as exc:
                results.append((f.name, {"success": False, "error": str(exc)}))
            finally:
                progress.progress((i + 1) / len(uploaded))
                if tmp_path and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        for fname, result in results:
            if result["success"]:
                st.success(f"{fname}: {result['chunks']} chunks ingested")
            else:
                st.error(f"{fname}: {result['error']}")

    st.divider()
    docs = file_manager.list_documents(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
    if docs:
        for doc in docs:
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{doc['filename']}**")
            c2.write(f"`{doc['file_type']}`")
            c3.write(f"{doc['chunk_count']} chunks")
        profiles = list_document_profiles(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
        if profiles:
            st.markdown("#### Document Intelligence")
            for profile in profiles:
                with st.expander(f"{profile['filename']} | confidence {profile.get('source_confidence', 0)}"):
                    st.write(profile.get("semantic_summary", ""))
                    keywords = profile.get("keyword_map", [])[:10]
                    if keywords:
                        st.caption("Keyword map")
                        st.write(", ".join(f"{k['term']} ({k['count']})" for k in keywords))
                    structure = profile.get("structure_map", {})
                    st.caption(
                        f"Questions: {profile.get('question_count', 0)} | "
                        f"Pages: {profile.get('page_count', 0)} | "
                        f"Headings: {len(structure.get('headings', []))}"
                    )
    else:
        st.info("No documents yet.")


def render_tools():
    st.markdown("### Tools")
    st.caption("Power tools run on your local workspace data and show the evidence basis for their conclusions.")
    tool = st.radio(
        "Tool",
        ["Pattern Analyzer", "Document Router Preview", "API Gateway"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if tool == "Pattern Analyzer":
        result = analyze_patterns(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
        if not result.get("source_count"):
            st.info("Upload multiple PDFs or notes first. The analyzer becomes stronger as document count grows.")
            return
        c1, c2, c3 = st.columns(3)
        c1.metric("Documents", result.get("source_count", 0))
        c2.metric("Detected questions", result.get("question_total", 0))
        c3.metric("Recurring topics", len(result.get("repetitions", [])))
        st.markdown("#### High-Signal Repetitions")
        for item in result.get("repetitions", [])[:12]:
            st.markdown(
                f"<div class='insight-card'><strong>{html.escape(item['topic'])}</strong><br>"
                f"{item['count']} mentions across {item['documents']} documents</div>",
                unsafe_allow_html=True,
            )
        st.markdown("#### Prediction Candidates")
        st.caption("These are statistical recurrence signals, not fake certainty.")
        for item in result.get("predictions", [])[:8]:
            st.progress(item["probability"], text=f"{item['topic']} | {item['probability']:.0%}")
            st.caption(item["basis"])

    elif tool == "Document Router Preview":
        query = st.text_input("Test a search query", placeholder="operating system deadlock previous year questions")
        if query:
            from app.core.document_intelligence import route_documents

            routed = route_documents(
                query,
                st.session_state.user_id,
                workspace_id=st.session_state.active_workspace_id,
                limit=8,
            )
            if not routed:
                st.warning("No document profile strongly matched this query.")
            for doc in routed:
                st.markdown(
                    f"<div class='insight-card'><strong>{html.escape(doc['filename'])}</strong><br>"
                    f"routing score {doc['routing_score']} | hits: {html.escape(', '.join(doc.get('keyword_hits', [])))}</div>",
                    unsafe_allow_html=True,
                )

    else:
        st.markdown("#### Local API Gateway")
        st.caption("Use scoped local keys carefully. Keep admin keys private and prefer read-only keys for tools.")
        label = st.text_input("Key label", placeholder="notebook-readonly")
        scopes = st.multiselect("Scopes", ["read", "chat", "tools", "admin"], default=["read"])
        rate = st.slider("Rate limit per minute", 5, 240, 30)
        sandbox = st.checkbox("Sandbox mode", value=True)
        if st.button("Create local API key", type="primary"):
            raw_key = "bgpt_" + secrets.token_urlsafe(28)
            key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO api_keys
                       (user_id, label, key_hash, scopes, rate_limit_per_min, sandbox)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        storage_user_id(st.session_state.user_id),
                        label or "local-key",
                        key_hash,
                        ",".join(scopes),
                        rate,
                        1 if sandbox else 0,
                    ),
                )
            st.success("API key created. Store it now; only the hash is saved.")
            st.code(raw_key, language="text")
        with st.expander("Read before use", expanded=False):
            st.write(
                "Treat API keys like passwords. Start with read-only scopes, keep sandbox mode enabled for tools, "
                "and use rate limits to prevent accidental loops or expensive local model runs."
            )


def render_memory():
    st.markdown("### Memory")
    stats = feedback_summary(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
    conflicts = list_memory_conflicts(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Feedback items", stats.get("count", 0))
    c2.metric("Average rating", stats.get("avg_rating", 0))
    c3.metric("Open conflicts", sum(1 for c in conflicts if c.get("status") == "open"))

    with st.form("add_memory_form"):
        title = st.text_input("Memory title", placeholder="Answer style preference")
        content = st.text_area("Memory content", placeholder="Prefer concise answers with bullet sources.")
        category = st.selectbox("Category", ["general", "preference", "study", "project", "developer", "event", "correction"])
        importance = st.slider("Importance", 1, 5, 3)
        pinned = st.checkbox("Pin memory")
        submitted = st.form_submit_button("Save Memory", type="primary")
        if submitted and title and content:
            add_memory(
                st.session_state.user_id,
                st.session_state.active_workspace_id,
                title,
                content,
                category,
                importance,
                pinned,
            )
            st.success("Memory saved locally.")

    memories = list_memories(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
    if not memories:
        st.info("No saved memories yet.")
    for memory in memories:
        state = "CONFLICT" if memory.get("status") == "conflict" else memory.get("layer", "semantic").upper()
        with st.expander(f"{'* ' if memory.get('pinned') else ''}{memory['title']} | {state}"):
            st.write(memory["content"])
            st.caption(
                f"Layer {memory.get('layer', 'semantic')} | Status {memory.get('status', 'active')} | "
                f"Decay {memory.get('decay_score', 1)} | Importance {memory['importance']} | {memory['updated_at']}"
            )
            if st.button("Delete memory", key=f"mem_del_{memory['id']}"):
                delete_memory(st.session_state.user_id, memory["id"])
                st.rerun()

    if conflicts:
        st.markdown("#### Conflict Memory")
        for conflict in conflicts[:8]:
            st.markdown(
                f"<div class='insight-card'><strong>{html.escape(conflict.get('status', 'open').upper())}</strong><br>"
                f"{html.escape(conflict.get('reason', 'Conflicting memories need resolution.'))}<br>"
                f"<span class='brand-sub'>{html.escape(conflict.get('created_at', ''))}</span></div>",
                unsafe_allow_html=True,
            )

    if stats.get("recent"):
        st.markdown("#### Recent Feedback")
        for row in stats["recent"]:
            st.caption(f"{row['created_at']} | rating {row['rating']}")
            st.write(row["query"][:180])


def render_plugins():
    st.markdown("### Plugins")
    pm = get_plugin_manager()
    plugins = pm.list_plugins()
    if not plugins:
        st.warning("No plugins loaded.")
        return

    for plugin in plugins:
        with st.expander(f"{plugin['name']} v{plugin['version']}"):
            st.write(plugin["description"])
            if plugin["name"] == "quiz_generator":
                content = st.text_area("Content for quiz", key=f"quiz_content_{plugin['name']}", height=150)
                count = st.slider("Questions", 3, 10, 5, key="quiz_count")
                if st.button("Generate Quiz", key=f"run_{plugin['name']}"):
                    res = pm.run("quiz_generator", {"content": content, "count": count})
                    if res["success"]:
                        for i, q in enumerate(res["result"], start=1):
                            st.markdown(f"**Q{i}:** {q['question']}")
                            st.markdown(f"**A{i}:** {q['answer']}")
                    else:
                        st.error(res.get("error"))
            elif plugin["name"] == "pdf_summarizer":
                content = st.text_area("Content to summarize", key="sum_content", height=150)
                if st.button("Summarize", key=f"run_{plugin['name']}"):
                    res = pm.run("pdf_summarizer", {"content": content})
                    st.markdown(res["result"] if res["success"] else res.get("error"))
            elif plugin["name"] == "calculator":
                expr = st.text_input("Expression", key="calc_expr", placeholder="2 ** 10 + 5 * 3")
                if st.button("Calculate", key=f"run_{plugin['name']}"):
                    res = pm.run("calculator", {"expression": expr})
                    if res["success"]:
                        st.success(f"= {res['result']}")
                    else:
                        st.error(res.get("error"))


def render_analytics():
    st.markdown("### Analytics")
    stats = get_user_stats(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)
    if not stats:
        st.info("No analytics yet.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Total queries", stats.get("total_queries", 0))
    col2.metric("Documents", stats.get("documents_uploaded", 0))
    col3.metric("Avg response", f"{stats.get('avg_response_ms', 0):.0f}ms")

    pipeline = stats.get("pipeline") or {}
    if pipeline:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("Retrieval", f"{pipeline.get('retrieval_ms') or 0:.0f}ms")
        c2.metric("Rerank", f"{pipeline.get('rerank_ms') or 0:.0f}ms")
        c3.metric("Compress", f"{pipeline.get('compression_ms') or 0:.0f}ms")
        c4.metric("Synthesis", f"{pipeline.get('synthesis_ms') or 0:.0f}ms")
        c5.metric("Token/s", f"{pipeline.get('token_per_second') or 0:.1f}")
        c6.metric("Retry", f"{(pipeline.get('retry_rate') or 0) * 100:.0f}%")

        c1, c2, c3 = st.columns(3)
        c1.metric("Grounding", f"{pipeline.get('grounding_score') or 0:.2f}")
        c2.metric("Unsupported", f"{pipeline.get('validation_unsupported') or 0:.2f}")
        c3.metric("Refined", f"{(pipeline.get('refined_rate') or 0) * 100:.0f}%")

    if stats.get("model_usage"):
        st.markdown("#### Model Usage")
        for item in stats["model_usage"]:
            st.write(f"`{item['model_used']}`: {item['cnt']} queries")
    if stats.get("recent_queries"):
        st.markdown("#### Recent Queries")
        for item in stats["recent_queries"][:8]:
            st.write(
                f"{item['query'][:100]} - {item['response_time_ms']}ms "
                f"(retrieval {item.get('retrieval_ms', 0)}ms, grounding {item.get('grounding_score', 0):.2f}, "
                f"unsupported {item.get('validation_unsupported') or 0:.2f}, "
                f"retry {item.get('retry_count') or 0}, {item.get('token_per_second') or 0:.1f} tok/s)"
            )

    st.markdown("#### Memory Graph")
    render_memory_graph_visual(st.session_state.user_id, workspace_id=st.session_state.active_workspace_id)


def render_system():
    st.markdown("### System Health")
    render_health_strip()
    perf = get_performance_budget()
    info = perf["system_info"]
    p = sys_profile()

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Hardware")
        st.write(f"RAM: {info['ram_total_gb']} GB total, {p['ram_available_gb']} GB free")
        st.write(f"CPU: {info['cpu_physical_cores']} physical / {info['cpu_logical_cores']} logical cores")
        st.write(f"Frequency: {info['cpu_freq_mhz']} MHz")
        st.write(f"OS: {info['os']} {p['arch']}")
        st.write(f"Battery: {p['battery_pct']}% {'on battery' if p['on_battery'] else 'plugged in'}")
    with col2:
        st.markdown("#### AI Runtime")
        st.write(f"Recommended mode: `{perf['mode']}`")
        st.write(f"Recommended model: `{perf['recommended_model']}`")
        models = cached_available_models() if cached_ollama_status() else []
        st.write("Available models: " + (", ".join(models) if models else "none"))
        st.code(
            """ollama serve
ollama pull gemma2:2b
ollama pull phi3:mini
ollama pull llama3.1:8b""",
            language="bash",
        )


def render_settings():
    st.markdown("### Settings")
    section = st.radio(
        "Settings section",
        ["General", "Model Hub", "Security", "About Developer"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if section == "General":
        st.markdown("#### Baby-GPT Workspace")
        st.markdown("<div class='settings-row'>Local-first storage: enabled</div>", unsafe_allow_html=True)
        st.markdown("<div class='settings-row'>Adaptive cache: retrieval cache, reranked contexts, and feedback signals</div>", unsafe_allow_html=True)
        st.markdown("<div class='settings-row'>Self-learning mode: controlled optimization only; core logic is not rewritten automatically</div>", unsafe_allow_html=True)
        render_health_strip()

    elif section == "Model Hub":
        st.markdown("#### Local Model Hub")
        installed = cached_available_models() if cached_ollama_status() else []
        for tier, profile in MODEL_PROFILES.items():
            names = [profile["name"], *profile.get("aliases", [])]
            active = next((m for m in installed if any(name.lower() in m.lower() for name in names)), "")
            status = active or "not installed"
            st.markdown(
                f"<div class='insight-card'><strong>{tier.title()}</strong><br>"
                f"Preferred: {html.escape(profile['name'])}<br>Status: {html.escape(status)}</div>",
                unsafe_allow_html=True,
            )
        st.caption("Download with Ollama, then Baby-GPT will route to the strongest installed model your device can handle.")
        st.code(
            "ollama pull gemma2:2b\nollama pull phi3:mini\nollama pull llama3.1:8b\nollama pull qwen2.5:14b",
            language="bash",
        )

    elif section == "Security":
        st.markdown("#### API, Security, and Rate Limits")
        st.write("Prompt firewall, scoped API keys, sandbox mode, and per-key rate limits are designed for cautious local automation.")
        st.warning("Do not expose this local API to the public internet without authentication, TLS, and a reverse proxy rate limiter.")
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT id, label, scopes, rate_limit_per_min, sandbox, active, created_at FROM api_keys WHERE user_id = ? ORDER BY created_at DESC",
                (storage_user_id(st.session_state.user_id),),
            ).fetchall()
        if not rows:
            st.info("No API keys yet. Create one from Tools > API Gateway.")
        for row in rows:
            st.markdown(
                f"<div class='settings-row'><strong>{html.escape(row['label'])}</strong> | "
                f"{html.escape(row['scopes'])} | {row['rate_limit_per_min']}/min | "
                f"{'sandbox' if row['sandbox'] else 'full'} | {'active' if row['active'] else 'disabled'}</div>",
                unsafe_allow_html=True,
            )

    else:
        st.markdown(
            """
<div class="hero">
  <div style="display:flex; gap:1rem; align-items:center; flex-wrap:wrap;">
    <img class="dev-avatar" src="https://lh3.googleusercontent.com/a/ACg8ocLXo5rQkedPZR8VjX81IkX8F4VGRjunLDe7xDlvrb--1oDBjh_4=s96-c" />
    <div>
      <h1>Akshay</h1>
      <p>Built by Akshay-core: a local-first personal AI intelligence workspace for documents, memory, pattern analysis, and controlled model orchestration.</p>
    </div>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
        st.markdown("#### Philosophy")
        st.write(
            "Baby-GPT is built to feel familiar like modern chat tools while staying its own product: calm premium UX, "
            "document-aware RAG, local memory, pattern analysis, workspace modes, and cautious self-improvement through feedback."
        )
        st.markdown("#### Privacy Manifesto")
        st.write(
            "Your documents, memories, feedback, cache, and API keys stay local by default. The system learns from corrections "
            "by tuning retrieval and presentation signals, not by silently rewriting its core behavior."
        )
        st.markdown("#### Architecture Highlights")
        st.write("Document fingerprinting, topic profiles, query-to-document routing, hybrid semantic/keyword retrieval, adaptive cache, prompt firewall, and local Ollama model routing.")
        st.caption(signature_label())


def main():
    activate_local_mode()
    if not st.session_state.logged_in or not verify_session():
        render_theme_overrides()
        render_login()
        return

    render_theme_overrides()
    render_sidebar()
    render_top_bar()
    render_chat()


if __name__ == "__main__":
    main()
