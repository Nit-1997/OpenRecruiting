"""Throwaway: audit Neo4j graph state for the test source_ids."""
import asyncio, os
from src.config.database import neo4j_driver

TEST_SOURCES = {
    'feedback_debrief_available': [
        '71d5179e-3cd9-4ce7-b8e8-a12f6f79ed04',
        '2905ac19-b671-47e3-99a1-c5d298f03c48',
        '3e444126-4a42-426c-952e-0356fb8acd72',
    ],
    'interview_transcript_available': [
        '71d5179e-3cd9-4ce7-b8e8-a12f6f79ed04',
        '2905ac19-b671-47e3-99a1-c5d298f03c48',
        '3e444126-4a42-426c-952e-0356fb8acd72',
    ],
    'intake_transcript_available': [
        '621606ea-f17d-4701-a42f-d72337e482be',
        'ebfede15-ea4a-4033-a6d2-e7b758cada24',
    ],
    'decision_made': [
        'a395f028-1f2a-41d0-9785-0394016fd5d5',
        '7eaa0163-0006-4d50-9d6a-65292539f1b4',
        'fe23a04e-1f97-43f4-963c-3bc83188cf1c',
    ],
}


async def main():
    await neo4j_driver.connect(uri=os.environ['NEO4J_URI'], user=os.environ['NEO4J_USER'], password=os.environ['NEO4J_PASSWORD'])

    print('=== EDGE COUNTS PER (event_type, source_id) ===')
    print(f'{"event_type":<35} {"source_id":<40} {"alive":>6} {"tombstoned":>12} {"distinct_ingested_at":>22}')
    for et, sids in TEST_SOURCES.items():
        for sid in sids:
            rows = await neo4j_driver.execute_read(
                'MATCH ()-[e]->() WHERE e._source_event_type=$et AND e._source_id=$sid '
                'RETURN COUNT(e) AS total, '
                '       SUM(CASE WHEN e.invalid_at IS NULL THEN 1 ELSE 0 END) AS alive, '
                '       SUM(CASE WHEN e.invalid_at IS NOT NULL THEN 1 ELSE 0 END) AS tombstoned, '
                '       COUNT(DISTINCT e._ingested_at) AS distinct_ingested',
                {'et': et, 'sid': sid},
            )
            r = rows[0] if rows else {}
            print(f'{et:<35} {sid:<40} {r.get("alive", 0):>6} {r.get("tombstoned", 0):>12} {r.get("distinct_ingested", 0):>22}')

    print('\n=== GLOBAL GRAPH STATS ===')
    n = await neo4j_driver.execute_read('MATCH (n) RETURN COUNT(n) AS c')
    e = await neo4j_driver.execute_read('MATCH ()-[r]->() RETURN COUNT(r) AS c')
    e_prov = await neo4j_driver.execute_read('MATCH ()-[r]->() WHERE r._source_event_type IS NOT NULL RETURN COUNT(r) AS c')
    e_dead = await neo4j_driver.execute_read('MATCH ()-[r]->() WHERE r.invalid_at IS NOT NULL RETURN COUNT(r) AS c')
    print(f'  total nodes: {n[0]["c"]}')
    print(f'  total edges: {e[0]["c"]}')
    print(f'  edges with provenance: {e_prov[0]["c"]}')
    print(f'  edges tombstoned (invalid_at set): {e_dead[0]["c"]}')

    print('\n=== EDGE TYPES BY EVENT_TYPE ===')
    rows = await neo4j_driver.execute_read(
        'MATCH ()-[r]->() WHERE r._source_event_type IS NOT NULL '
        'RETURN r._source_event_type AS et, r.name AS rel_name, COUNT(*) AS cnt '
        'ORDER BY et, cnt DESC'
    )
    for r in rows:
        print(f'  {r["et"]:<35} {r["rel_name"]:<25} {r["cnt"]}')

    print('\n=== NODE TYPES TOUCHED ===')
    rows = await neo4j_driver.execute_read(
        'MATCH (n) WHERE NOT (n:Episodic) '
        'WITH labels(n) AS lbls, COUNT(*) AS cnt UNWIND lbls AS lbl '
        'RETURN lbl, SUM(cnt) AS total ORDER BY total DESC LIMIT 20'
    )
    for r in rows:
        print(f'  {r["lbl"]:<30} {r["total"]}')

    await neo4j_driver.disconnect()


if __name__ == '__main__':
    asyncio.run(main())
