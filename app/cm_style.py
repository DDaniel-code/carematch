"""Shared look for every CareMatch page: warm paper, deep navy ink, a blue accent and one orange highlight (the same
blue and orange as the notebook charts), tight display type, pill buttons.

Presentation only. Native Streamlit controls, keyboard navigation and status messages stay intact. Selectors cover both
the Streamlit that Databricks Apps ships (1.38) and current releases, whose test ids differ.
"""
import streamlit as st

INK, INK_3, ACCENT, CORAL = '#0F1B33', '#6B7588', '#2468C8', '#EB6834'
INK_RGB, MUTED_RGB, CORAL_RGB = [15, 27, 51], [107, 117, 136], [235, 104, 52]

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Inter+Tight:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');
:root{--paper:#F8F7F4;--cream:#EFEDE8;--peach:#FCE6DA;--ink:#0F1B33;--night:#1B2F57;--ink-2:#3F4A5F;--ink-3:#6B7588;
  --line:rgba(15,27,51,.10);--line-2:rgba(15,27,51,.18);--accent:#2468C8;--tint-line:#CFE0F7;--tint:#EAF1FB;
  --coral:#EB6834;--coral-d:#A8431A;--good:#1F6F4F;--good-bg:#E6F3EC;
  --display:'Inter Tight','Inter',system-ui,sans-serif;--body:'Inter',system-ui,-apple-system,'Segoe UI',sans-serif;
  --mono:'JetBrains Mono',ui-monospace,Menlo,monospace;
  --shadow-sm:0 1px 2px rgba(15,27,51,.05),0 10px 26px -16px rgba(15,27,51,.22);
  --shadow:0 30px 60px -34px rgba(15,27,51,.45),0 10px 24px -16px rgba(15,27,51,.18)}

/* Page */
.stApp{background:var(--paper);color:var(--ink);font-family:var(--body)}
[data-testid="stHeader"]{background:transparent}
[data-testid="stMainBlockContainer"],[data-testid="stAppViewBlockContainer"]{max-width:1320px;padding-top:3.4rem}
.stApp [data-testid="stMarkdownContainer"],.stApp [data-testid="stCaptionContainer"],.stApp [data-testid="stWidgetLabel"],
.stApp label,.stApp input,.stApp textarea,.stApp button,.stApp [data-baseweb="select"],.stApp [data-testid="stMetric"],
.stApp [data-testid="stText"]{font-family:var(--body)}
.stApp h1,.stApp h2,.stApp h3,.stApp h4{font-family:var(--display);font-weight:500;letter-spacing:-.03em;color:var(--ink)}
.stApp h1{font-size:2.5rem;line-height:1.06;letter-spacing:-.035em}
.stApp h2{font-size:1.7rem}
.stApp h3{font-size:1.45rem}
[data-testid="stCaptionContainer"]{color:var(--ink-3)}
[data-testid="stMarkdownContainer"]{overflow-wrap:anywhere}
.stApp a{color:var(--accent)}
.stApp code,.stApp [data-testid="stText"]{font-family:var(--mono);font-size:.82rem}

/* Buttons: pills. Dark ink for the one main action, white with a hairline for the rest. */
.stApp button[kind="primary"],.stApp button[kind="primaryFormSubmit"],
[data-testid="stLinkButton"] a:is([kind="primary"],[data-testid$="LinkButton-primary"]){background:var(--ink);border:1px solid var(--ink);
  color:#fff;border-radius:999px;min-height:2.7rem;font-weight:500;letter-spacing:-.005em;box-shadow:none}
.stApp button[kind="primary"]:hover,.stApp button[kind="primaryFormSubmit"]:hover,
[data-testid="stLinkButton"] a:is([kind="primary"],[data-testid$="LinkButton-primary"]):hover{background:var(--night);border-color:var(--night);color:#fff}
.stApp button[kind="primary"] p,.stApp button[kind="primaryFormSubmit"] p,
[data-testid="stLinkButton"] a:is([kind="primary"],[data-testid$="LinkButton-primary"]) p{color:#fff}
.stApp button[kind="secondary"],.stApp button[kind="secondaryFormSubmit"],
[data-testid="stLinkButton"] a:is([kind="secondary"],[data-testid$="LinkButton-secondary"]){background:#fff;border:1px solid var(--line-2);
  color:var(--ink);border-radius:999px;font-weight:500;min-height:2.5rem;box-shadow:none}
.stApp button[kind="secondary"]:hover,.stApp button[kind="secondaryFormSubmit"]:hover,
[data-testid="stLinkButton"] a:is([kind="secondary"],[data-testid$="LinkButton-secondary"]):hover{border-color:var(--ink);color:var(--ink);background:var(--tint)}
.stApp button[kind]:focus-visible,[data-testid="stLinkButton"] a:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
[data-testid="stLinkButton"]{max-width:100%;overflow:hidden}
[data-testid="stLinkButton"] a{width:100%;max-width:100%;min-width:0;box-sizing:border-box;padding:.25rem .6rem;overflow:hidden;text-decoration:none}
[data-testid="stLinkButton"] a [data-testid="stMarkdownContainer"]{min-width:0;max-width:100%;overflow:hidden}
[data-testid="stLinkButton"] a p{font-size:.84rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}

/* Inputs */
.stApp [data-baseweb="input"],.stApp [data-baseweb="select"]>div{background:#fff;border-radius:12px;border-color:var(--line-2)}
.stApp [data-baseweb="base-input"]{background:#fff}
.stApp [data-baseweb="input"]:focus-within,.stApp [data-baseweb="select"]>div:focus-within{border-color:var(--accent)}
[data-testid="stWidgetLabel"] p{font-weight:500;color:var(--ink-2);font-size:.86rem}

/* Surfaces */
[data-testid="stForm"]{background:#fff;border:1px solid var(--line);border-radius:22px;padding:1.35rem 1.5rem 1rem;box-shadow:var(--shadow-sm)}
[data-testid="stExpander"] details{background:#fff;border:1px solid var(--line);border-radius:16px}
[data-testid="stExpander"] summary{font-weight:500}
[data-testid="stExpander"] summary:hover{color:var(--accent)}
[data-testid="stAlert"],[data-testid="stAlert"]>div{border-radius:16px}
/* Notes take the page palette; warnings and errors keep their own colours. */
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]){background:var(--tint);border:1px solid var(--tint-line)}
[data-testid="stAlertContentInfo"],[data-testid="stAlertContentInfo"] p{color:var(--ink)}
/* Cards: the innermost bordered block that holds a result title or a panel heading. */
[data-testid="stVerticalBlockBorderWrapper"]:has(.cm-title,.cm-panel):not(:has([data-testid="stVerticalBlockBorderWrapper"] :is(.cm-title,.cm-panel))){background:#fff;border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow-sm)}
[data-testid="stVerticalBlock"]:has(> [data-testid="stElementContainer"] :is(.cm-title,.cm-panel)){background:#fff;border:1px solid var(--line);border-radius:22px;box-shadow:var(--shadow-sm)}
.stApp .cm-panel,.cm-panel{font-family:var(--display);font-size:1.22rem !important;font-weight:500;letter-spacing:-.025em;margin:.1rem 0 .2rem;padding:0}
[data-testid="stMetric"]{background:#fff;border:1px solid var(--line);border-radius:18px;padding:1rem 1.2rem;box-shadow:var(--shadow-sm)}
[data-testid="stMetricLabel"] p{font-family:var(--mono);font-size:.72rem;letter-spacing:.04em;text-transform:uppercase;color:var(--ink-3)}
[data-testid="stMetricValue"]{font-family:var(--display);font-weight:500;letter-spacing:-.03em;color:var(--ink)}
[data-testid="stVegaLiteChart"],[data-testid="stDeckGlJsonChart"],[data-testid="stArrowVegaLiteChart"]{background:#fff;border:1px solid var(--line);
  border-radius:22px;overflow:hidden;box-shadow:var(--shadow-sm)}
[data-testid="stVegaLiteChart"],[data-testid="stArrowVegaLiteChart"]{padding:.8rem;background:var(--paper)}
blockquote{border-left:3px solid var(--accent);background:var(--tint);padding:.65rem 1rem;border-radius:0 12px 12px 0}

/* Sidebar: the night panel */
[data-testid="stSidebar"]{background:var(--ink)}
[data-testid="stSidebar"]>div{background:var(--ink)}
[data-testid="stSidebar"] p,[data-testid="stSidebar"] span,[data-testid="stSidebar"] label,[data-testid="stSidebar"] strong{color:#EEF2F8}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#AEB9CC}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong{font-family:var(--mono);font-size:.7rem;font-weight:500;
  letter-spacing:.14em;text-transform:uppercase;color:#AEB9CC}
[data-testid="stSidebarNav"] a{border-radius:999px;margin:.1rem .35rem;padding-left:.9rem}
[data-testid="stSidebarNav"] a:hover{background:rgba(255,255,255,.08)}
[data-testid="stSidebarNav"] a[aria-current="page"]{background:rgba(255,255,255,.14)}
[data-testid="stSidebarNav"] a span{color:#EEF2F8;font-weight:500}
[data-testid="stSidebar"] button[kind] svg,[data-testid="stSidebar"] [data-testid="stIconMaterial"]{color:#EEF2F8;fill:#EEF2F8}

/* Brand bar and hero */
.cm-bar{display:flex;align-items:center;justify-content:space-between;gap:1rem;background:var(--ink);border-radius:999px;
  padding:.55rem 1.3rem .55rem 1.1rem;margin:0 0 1rem;box-shadow:var(--shadow-sm)}
.cm-brand{font-family:var(--display);color:#fff;font-size:1.22rem;font-weight:600;letter-spacing:-.04em;white-space:nowrap}
.cm-brand i{font-style:normal;color:var(--coral);margin-right:.4rem}
.cm-brand span{font-family:var(--mono);font-size:.62rem;font-weight:500;letter-spacing:.2em;margin-left:.6rem;color:#AEB9CC}
.cm-bar small{color:#CBD5E4;font-size:.82rem;text-align:right}
.cm-hero{position:relative;overflow:hidden;border-radius:28px;padding:1.5rem 2.4rem 2.5rem;margin:0 0 1.3rem;color:#fff;
  background:radial-gradient(900px 420px at 88% -10%,rgba(235,104,52,.40),transparent 62%),
             radial-gradient(700px 480px at 62% 120%,rgba(36,104,200,.55),transparent 64%),
             linear-gradient(135deg,#0F1B33 0%,#1B2F57 100%);box-shadow:var(--shadow)}
.cm-hero .cm-brand{display:block;margin-bottom:2.6rem}
.cm-hero h1,.stApp .cm-hero h1{color:#fff;font-family:var(--display);font-weight:500;font-size:clamp(2.3rem,4.6vw,3.5rem);
  line-height:1.03;letter-spacing:-.04em;margin:0 0 .9rem;padding:0;max-width:16ch}
.cm-hero p.lead{color:#DCE5F2;font-size:1.08rem;line-height:1.5;max-width:46ch;margin:0 0 1.5rem}
.cm-steps{display:flex;flex-wrap:wrap;gap:.6rem}
.cm-steps span{display:inline-flex;align-items:center;gap:.55rem;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.16);
  border-radius:999px;padding:.38rem .95rem .38rem .42rem;font-size:.86rem;color:#fff;backdrop-filter:blur(6px)}
.cm-steps b{display:inline-flex;align-items:center;justify-content:center;width:1.45rem;height:1.45rem;border-radius:50%;
  background:#fff;color:var(--ink);font-family:var(--mono);font-size:.72rem;font-weight:500}
.cm-eyebrow{font-family:var(--mono);font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);margin:0 0 .3rem}

/* Result components */
.cm-status{display:inline-block;font-family:var(--mono);font-size:.76rem;line-height:1.5;color:var(--ink-2);background:var(--cream);
  border-radius:12px;padding:.42rem .85rem;margin:.1rem 0 .5rem}
.stApp .cm-title,.cm-title{display:flex;align-items:center;gap:.6rem;font-family:var(--display);font-size:1.22rem !important;font-weight:500;
  letter-spacing:-.025em;margin:.1rem 0 .4rem;line-height:1.25;padding:0}
/* Newer Streamlit wraps heading content in one span; keep the pin and the name spaced inside it too. */
.cm-title>span:first-child{display:inline-flex;align-items:center;gap:.6rem}
.cm-pin{display:inline-flex;align-items:center;justify-content:center;min-width:1.75rem;height:1.75rem;border-radius:50%;
        background:var(--ink);color:#fff;font-family:var(--mono);font-weight:500;font-size:.8rem;letter-spacing:0;flex:none}
.cm-pin.extra{background:var(--ink-3)}
.cm-meta{color:var(--ink-3);font-size:.88rem;margin:.12rem 0}
.cm-chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:.1rem .65rem;font-size:.78rem;font-weight:500;
         margin:0 .35rem .3rem 0;color:var(--ink-2);background:var(--cream);white-space:nowrap}
.cm-chip.strong{border-color:transparent;color:var(--good);background:var(--good-bg)}
.cm-chip.moderate{border-color:transparent;color:var(--coral-d);background:var(--peach)}
.cm-chip.weak{border-color:var(--line-2);color:var(--ink-3);background:transparent}
.cm-quote{border-left:3px solid var(--accent);background:var(--tint);border-radius:0 12px 12px 0;padding:.5rem .8rem;color:var(--ink);
          margin:.45rem 0;font-size:.93rem;line-height:1.45}
.cm-quote small{font-family:var(--mono);font-size:.7rem;letter-spacing:.02em;color:var(--ink-3)}
.cm-price{font-size:.9rem;margin:.25rem 0;color:var(--ink)}
.cm-warn{font-size:.86rem;color:var(--coral-d);margin:.15rem 0}

@media (max-width:760px){
  [data-testid="stMainBlockContainer"],[data-testid="stAppViewBlockContainer"]{padding:3.4rem 1rem 1.5rem}
  [data-testid="stHorizontalBlock"]{flex-direction:column;gap:1rem}
  [data-testid="stColumn"],[data-testid="column"]{width:100% !important;flex:1 1 100% !important;min-width:0 !important}
  .cm-hero{padding:1.2rem 1.3rem 1.6rem;border-radius:22px}
  .cm-hero .cm-brand{margin-bottom:1.6rem}
  .cm-bar{border-radius:18px}
  .cm-bar small{display:none}
}
</style>
"""

BRAND = '<span class="cm-brand"><i>✚</i>carematch<span>INDIA</span></span>'


def apply():
    """Inject the shared stylesheet. Call once per page, after st.set_page_config."""
    st.markdown(CSS, unsafe_allow_html=True)


def bar(note=''):
    """Compact brand bar for result and planner pages."""
    st.markdown(f'<div class="cm-bar">{BRAND}<small>{note}</small></div>', unsafe_allow_html=True)


def hero(title, lead, steps=()):
    """The landing panel: brand, one headline, one sentence, and the steps a visitor takes."""
    chips = ''.join(f'<span><b>{i}</b>{text}</span>' for i, text in enumerate(steps, 1))
    st.markdown(f'<div class="cm-hero">{BRAND}<h1>{title}</h1><p class="lead">{lead}</p>'
                f'<div class="cm-steps">{chips}</div></div>', unsafe_allow_html=True)
