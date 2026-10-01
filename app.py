from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from neo4j_service import (
    RECOMMEND_CYPHER,
    add_hotel,
    add_person,
    clear_graph_data,
    get_hotels,
    get_liked,
    get_metrics,
    get_people,
    graph_edges,
    ping,
    popular_fallback,
    recommend_hotels,
    seed_demo_data,
    set_likes,
    similar_people,
    top_hotels,
)

st.set_page_config(page_title="Hotel Recommender", page_icon="🏨", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.3rem; padding-bottom: 2rem;}
      .hero {padding: 1.4rem 1.6rem; border-radius: 22px; margin-bottom: 1rem; color: white;
             background: linear-gradient(120deg, #111827 0%, #1f2937 55%, #b45309 100%);}
      .hero h1 {margin:0; font-size:2.1rem;}
      .hero p {opacity:.88; margin:.35rem 0 0 0;}
      .card {padding: 1rem 1.1rem; border: 1px solid rgba(128,128,128,.25); border-radius: 16px; margin-bottom: .75rem;}
      .pill {display:inline-block; padding:.2rem .55rem; border-radius:999px; background:#b45309;
             color:white; font-size:.8rem; font-weight:700;}
      .muted {opacity:.72; font-size:.9rem;}
    </style>
    """,
    unsafe_allow_html=True,
)


def require_connection() -> None:
    try:
        if not ping():
            raise RuntimeError("Neo4j did not return a healthy response")
    except Exception as exc:
        st.error("ยังเชื่อมต่อ Neo4j Aura ไม่สำเร็จ")
        st.code(
            '[neo4j]\nuri = "neo4j+s://YOUR_INSTANCE.databases.neo4j.io"\n'
            'username = "neo4j"\npassword = "YOUR_PASSWORD"',
            language="toml",
        )
        st.caption("นำค่าไปใส่ใน Streamlit Secrets และห้าม commit password ลง GitHub")
        st.exception(exc)
        st.stop()


def person_selector(key: str) -> str:
    people = get_people()
    if not people:
        st.info("ยังไม่มีข้อมูลผู้ใช้ ไปที่หน้า Admin / Setup แล้วสร้างข้อมูลตัวอย่างก่อน")
        st.stop()
    default = people.index("Pond") if "Pond" in people else 0
    return st.selectbox("ผู้ใช้เป้าหมาย", people, index=default, key=key)


def explain(row: dict) -> str:
    by = ", ".join(f"{x['person']} (ชอบร่วม {x['shared']})" for x in row["recommended_by"])
    return f"แนะนำจาก {row['voters']} คนที่รสนิยมคล้ายกัน: {by} · มีคนชอบทั้งหมด {row['popularity']} คน"


require_connection()

with st.sidebar:
    st.markdown("## 🏨 Hotel Recommender")
    st.caption("Neo4j Aura + Streamlit")
    page = st.radio("เมนู", ["Dashboard", "Recommendations", "Like / Unlike", "Graph Explorer", "Admin / Setup"])
    st.divider()
    st.caption("(Person)-[:LIKES]->(Hotel) · Collaborative Filtering")

st.markdown(
    """
    <div class="hero">
      <h1>🏨 Hotel Recommendation System</h1>
      <p>แนะนำโรงแรมจากความชอบของผู้ใช้ที่คล้ายกัน ด้วย Graph Database</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------ Dashboard
if page == "Dashboard":
    m = get_metrics()
    c1, c2, c3 = st.columns(3)
    c1.metric("Persons", m["persons"])
    c2.metric("Hotels", m["hotels"])
    c3.metric("LIKES relationships", m["likes"])

    st.divider()
    left, right = st.columns([3, 2])
    with left:
        st.subheader("โรงแรมยอดนิยม")
        tops = top_hotels(10)
        if tops:
            st.bar_chart(pd.DataFrame(tops).set_index("hotel")["likes"])
        else:
            st.info("ยังไม่มีข้อมูล")
    with right:
        st.subheader("โปรไฟล์ผู้ใช้")
        person = person_selector("dash_person")
        liked = get_liked(person)
        st.write("**ชอบ:** " + (", ".join(liked) if liked else "ยังไม่มี"))
        sims = similar_people(person)
        if sims:
            df = pd.DataFrame(sims)
            df["shared_hotels"] = df["shared_hotels"].apply(", ".join)
            st.caption("ผู้ใช้ที่คล้ายกัน")
            st.dataframe(df, width="stretch", hide_index=True)
        else:
            st.caption("ยังไม่มีผู้ใช้ที่ชอบโรงแรมร่วมกัน")

# ------------------------------------------------------------------ Recommendations
elif page == "Recommendations":
    st.subheader("✨ โรงแรมที่แนะนำ")
    person = person_selector("rec_person")
    top_n = st.slider("จำนวนคำแนะนำ", 1, 10, 5)
    liked = get_liked(person)
    st.write(f"**{person} ชอบ:** " + (", ".join(liked) if liked else "ยังไม่มี"))

    rows = recommend_hotels(person, top_n)
    if rows:
        st.caption("score = ผลรวมจำนวนโรงแรมที่ชอบร่วมกันของผู้ใช้ที่แนะนำโรงแรมนั้น")
        for i, r in enumerate(rows, start=1):
            st.markdown(
                f"""
                <div class="card">
                  <span class="pill">#{i} · score {r['score']}</span>
                  <h3 style="margin:.55rem 0 .2rem 0">{html.escape(r['hotel'])}</h3>
                  <p class="muted">{html.escape(explain(r))}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.warning("ยังไม่มีผู้ใช้ที่ชอบโรงแรมร่วมกับคนนี้ จึงแนะนำจากความนิยมแทน")
        for r in popular_fallback(person, top_n):
            st.write(f"- **{r['hotel']}** — มีคนชอบ {r['likes']} คน")
    with st.expander("ดู Cypher Query"):
        st.code(RECOMMEND_CYPHER.strip(), language="cypher")

# ------------------------------------------------------------------ Like / Unlike
elif page == "Like / Unlike":
    st.subheader("❤️ แก้ไขโรงแรมที่ชอบ")
    st.caption("เลือกโรงแรมที่ผู้ใช้ชอบ แล้วกดบันทึก จากนั้นดูว่าคำแนะนำเปลี่ยนอย่างไร")
    person = person_selector("like_person")
    hotels = get_hotels()
    current = get_liked(person)
    chosen = st.multiselect("โรงแรมที่ชอบ", hotels, default=current, key=f"likes_{person}")
    if st.button("บันทึก", type="primary", width="stretch"):
        set_likes(person, chosen)
        st.success(f"บันทึก LIKES ของ {person} แล้ว ({len(chosen)} แห่ง)")
        st.rerun()

# ------------------------------------------------------------------ Graph Explorer
elif page == "Graph Explorer":
    st.subheader("🕸️ Graph Explorer")
    person = person_selector("graph_person")
    edges = graph_edges(person)
    if not edges:
        st.info("ผู้ใช้นี้ยังไม่มี LIKES")
    else:
        recs = {r["hotel"] for r in recommend_hotels(person, 10)}
        mine = {e["hotel"] for e in edges if e["person"] == person}
        st.caption("ส้ม = ผู้ใช้เป้าหมาย · เขียว = โรงแรมที่แนะนำ · ฟ้า = โรงแรมที่ผู้ใช้เป้าหมายชอบ")
        dot = ["digraph G {", "rankdir=LR;", 'node [fontname="Helvetica", style=filled];']
        for p in sorted({e["person"] for e in edges}):
            color = "#fbbf24" if p == person else "#bfdbfe"
            dot.append(f'"{p}" [shape=ellipse, fillcolor="{color}"];')
        for h in sorted({e["hotel"] for e in edges}):
            color = "#86efac" if h in recs else ("#93c5fd" if h in mine else "#e5e7eb")
            dot.append(f'"{h}" [shape=box, fillcolor="{color}"];')
        for e in edges:
            dot.append(f'"{e["person"]}" -> "{e["hotel"]}" [label="LIKES", fontsize=9];')
        dot.append("}")
        st.graphviz_chart("\n".join(dot), width="stretch")
        with st.expander("ข้อมูล edge"):
            st.dataframe(pd.DataFrame(edges), width="stretch", hide_index=True)

# ------------------------------------------------------------------ Admin / Setup
elif page == "Admin / Setup":
    st.subheader("⚙️ Setup")
    st.markdown(
        """
        **Graph schema:** `(:Person {name})-[:LIKES]->(:Hotel {name})`
        """
    )
    st.warning("ปุ่มสร้างข้อมูลตัวอย่างใช้ MERGE จึงกดซ้ำได้และไม่ลบข้อมูลเดิม")
    if st.button("สร้าง Constraint + Demo Data", type="primary", width="stretch"):
        with st.spinner("กำลังสร้างข้อมูล..."):
            seed_demo_data()
        st.success("สร้างข้อมูลตัวอย่างเรียบร้อยแล้ว")
        st.rerun()

    st.divider()
    c1, c2 = st.columns(2)
    new_person = c1.text_input("เพิ่ม Person ใหม่")
    if c1.button("เพิ่มผู้ใช้") and new_person.strip():
        add_person(new_person.strip())
        st.success(f"เพิ่ม {new_person.strip()} แล้ว")
    new_hotel = c2.text_input("เพิ่ม Hotel ใหม่")
    if c2.button("เพิ่มโรงแรม") and new_hotel.strip():
        add_hotel(new_hotel.strip())
        st.success(f"เพิ่ม {new_hotel.strip()} แล้ว")

    st.divider()
    with st.expander("Danger zone"):
        st.caption("ลบเฉพาะ node :Person และ :Hotel พร้อม LIKES ทั้งหมด (ไม่ลบข้อมูลอื่นในฐานข้อมูล)")
        if st.checkbox("ฉันเข้าใจและต้องการลบ") and st.button("ลบข้อมูล Person / Hotel"):
            clear_graph_data()
            st.success("ลบแล้ว")
            st.rerun()
