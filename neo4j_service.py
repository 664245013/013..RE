from __future__ import annotations

from typing import Any

import streamlit as st
from neo4j import GraphDatabase, RoutingControl

# ------------------------------------------------------------------ sample data
PERSONS = ["U", "Mark", "Pond", "Bonus", "JDK", "Phat", "Poom", "Top", "Yo", "Nava"]
HOTELS = [f"Hotel {c}" for c in "ABCDEFGHIJ"]
LIKES = [  # ข้อมูลตัวอย่าง แก้ได้
    ["U", "Hotel A"], ["U", "Hotel B"], ["U", "Hotel D"],
    ["Mark", "Hotel A"], ["Mark", "Hotel C"], ["Mark", "Hotel E"],
    ["Pond", "Hotel A"], ["Pond", "Hotel F"],
    ["Bonus", "Hotel B"], ["Bonus", "Hotel C"], ["Bonus", "Hotel G"],
    ["JDK", "Hotel A"], ["JDK", "Hotel D"], ["JDK", "Hotel H"],
    ["Phat", "Hotel F"], ["Phat", "Hotel I"], ["Phat", "Hotel E"],
    ["Poom", "Hotel C"], ["Poom", "Hotel J"], ["Poom", "Hotel G"],
    ["Top", "Hotel A"], ["Top", "Hotel F"], ["Top", "Hotel I"],
    ["Yo", "Hotel B"], ["Yo", "Hotel H"], ["Yo", "Hotel J"],
    ["Nava", "Hotel D"], ["Nava", "Hotel E"], ["Nava", "Hotel I"],
]

# Collaborative Filtering: คนที่ชอบโรงแรมร่วมกัน -> โรงแรมอื่นที่เขาชอบ -> ตัดที่เราชอบแล้ว
RECOMMEND_CYPHER = """
MATCH (t:Person {name: $name})-[:LIKES]->(common:Hotel)<-[:LIKES]-(o:Person)
WHERE o <> t
WITH t, o, count(common) AS shared
MATCH (o)-[:LIKES]->(rec:Hotel)
WHERE NOT (t)-[:LIKES]->(rec)
WITH rec,
     count(DISTINCT o) AS voters,
     sum(shared) AS score,
     collect(DISTINCT {person: o.name, shared: shared}) AS recommended_by
RETURN rec.name AS hotel, voters, score,
       COUNT { (rec)<-[:LIKES]-() } AS popularity,
       recommended_by
ORDER BY score DESC, voters DESC, popularity DESC, hotel
LIMIT $limit
"""


# ------------------------------------------------------------------ connection
def _config() -> tuple[str, str, str, str | None]:
    cfg = st.secrets["neo4j"]
    return cfg["uri"], cfg["username"], cfg["password"], cfg.get("database") or None


@st.cache_resource(show_spinner=False)
def get_driver():
    uri, username, password, _ = _config()
    driver = GraphDatabase.driver(uri, auth=(username, password))
    driver.verify_connectivity()
    return driver


def query(cypher: str, parameters: dict[str, Any] | None = None, *, write: bool = False) -> list[dict[str, Any]]:
    _, _, _, database = _config()
    records, _, _ = get_driver().execute_query(
        cypher,
        parameters_=parameters or {},
        database_=database,
        routing_=RoutingControl.WRITE if write else RoutingControl.READ,
    )
    return [r.data() for r in records]


def ping() -> bool:
    rows = query("RETURN 1 AS ok")
    return bool(rows and rows[0]["ok"] == 1)


# ------------------------------------------------------------------ setup
def create_schema() -> None:
    for stmt in (
        "CREATE CONSTRAINT person_name_unique IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE",
        "CREATE CONSTRAINT hotel_name_unique IF NOT EXISTS FOR (h:Hotel) REQUIRE h.name IS UNIQUE",
    ):
        query(stmt, write=True)


def seed_demo_data() -> None:
    """Idempotent (MERGE) — กดซ้ำได้ ไม่ลบข้อมูลเดิม"""
    create_schema()
    query("UNWIND $rows AS n MERGE (:Person {name: n})", {"rows": PERSONS}, write=True)
    query("UNWIND $rows AS n MERGE (:Hotel {name: n})", {"rows": HOTELS}, write=True)
    query(
        """
        UNWIND $rows AS row
        MATCH (p:Person {name: row[0]}), (h:Hotel {name: row[1]})
        MERGE (p)-[:LIKES]->(h)
        """,
        {"rows": LIKES},
        write=True,
    )


def clear_graph_data() -> None:
    """ลบเฉพาะ node :Person / :Hotel (และ relationship ของมัน) ไม่ลบทั้งฐานข้อมูล"""
    query("MATCH (n) WHERE n:Person OR n:Hotel DETACH DELETE n", write=True)


def add_person(name: str) -> None:
    query("MERGE (:Person {name: $name})", {"name": name}, write=True)


def add_hotel(name: str) -> None:
    query("MERGE (:Hotel {name: $name})", {"name": name}, write=True)


# ------------------------------------------------------------------ reads
def get_people() -> list[str]:
    return [r["name"] for r in query("MATCH (p:Person) RETURN p.name AS name ORDER BY name")]


def get_hotels() -> list[str]:
    return [r["name"] for r in query("MATCH (h:Hotel) RETURN h.name AS name ORDER BY name")]


def get_metrics() -> dict[str, int]:
    rows = query(
        """
        RETURN COUNT { (:Person) } AS persons,
               COUNT { (:Hotel) } AS hotels,
               COUNT { (:Person)-[:LIKES]->(:Hotel) } AS likes
        """
    )
    return rows[0] if rows else {"persons": 0, "hotels": 0, "likes": 0}


def top_hotels(limit: int = 10) -> list[dict[str, Any]]:
    return query(
        """
        MATCH (h:Hotel)
        RETURN h.name AS hotel, COUNT { (h)<-[:LIKES]-() } AS likes
        ORDER BY likes DESC, hotel
        LIMIT $limit
        """,
        {"limit": int(limit)},
    )


def get_liked(name: str) -> list[str]:
    rows = query(
        "MATCH (:Person {name: $name})-[:LIKES]->(h:Hotel) RETURN h.name AS hotel ORDER BY hotel",
        {"name": name},
    )
    return [r["hotel"] for r in rows]


def similar_people(name: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = query(
        """
        MATCH (t:Person {name: $name})-[:LIKES]->(h:Hotel)<-[:LIKES]-(o:Person)
        WHERE o <> t
        RETURN o.name AS person, count(h) AS shared, collect(h.name) AS shared_hotels
        ORDER BY shared DESC, person
        LIMIT $limit
        """,
        {"name": name, "limit": int(limit)},
    )
    for r in rows:
        r["shared_hotels"] = sorted(r["shared_hotels"])
    return rows


def recommend_hotels(name: str, limit: int = 5) -> list[dict[str, Any]]:
    rows = query(RECOMMEND_CYPHER, {"name": name, "limit": int(limit)})
    for r in rows:
        r["recommended_by"] = sorted(r["recommended_by"], key=lambda x: (-x["shared"], x["person"]))
    return rows


def popular_fallback(name: str, limit: int = 5) -> list[dict[str, Any]]:
    """Cold start: ผู้ใช้ที่ยังไม่มี LIKES ร่วมกับใครเลย -> แนะนำโรงแรมยอดนิยมที่ยังไม่ได้ชอบ"""
    return query(
        """
        MATCH (h:Hotel)
        WHERE NOT EXISTS { MATCH (:Person {name: $name})-[:LIKES]->(h) }
        RETURN h.name AS hotel, COUNT { (h)<-[:LIKES]-() } AS likes
        ORDER BY likes DESC, hotel
        LIMIT $limit
        """,
        {"name": name, "limit": int(limit)},
    )


def graph_edges(name: str) -> list[dict[str, Any]]:
    """LIKES ของผู้ใช้เป้าหมาย + ของผู้ใช้ที่คล้ายกัน (ใช้วาดกราฟ)"""
    return query(
        """
        MATCH (t:Person {name: $name})
        OPTIONAL MATCH (t)-[:LIKES]->(:Hotel)<-[:LIKES]-(o:Person)
        WHERE o <> t
        WITH t, collect(DISTINCT o) AS similar
        UNWIND ([t] + similar) AS p
        MATCH (p)-[:LIKES]->(h:Hotel)
        RETURN DISTINCT p.name AS person, h.name AS hotel
        """,
        {"name": name},
    )


# ------------------------------------------------------------------ writes
def set_likes(name: str, hotels: list[str]) -> None:
    """ซิงค์ LIKES ของผู้ใช้ให้ตรงกับรายการที่เลือก (เพิ่มที่ขาด ลบที่เกิน)"""
    query(
        """
        MATCH (p:Person {name: $name})-[r:LIKES]->(h:Hotel)
        WHERE NOT h.name IN $hotels
        DELETE r
        """,
        {"name": name, "hotels": hotels},
        write=True,
    )
    query(
        """
        MATCH (p:Person {name: $name})
        UNWIND $hotels AS hn
        MATCH (h:Hotel {name: hn})
        MERGE (p)-[:LIKES]->(h)
        """,
        {"name": name, "hotels": hotels},
        write=True,
    )
