# Legacy Bloom assets

Demo-era visualization assets, kept for reference but **not maintained**:

- `CodeGraph.json` — a Neo4j Bloom perspective (categories, palette, saved
  search phrases) for visually exploring the graph in Bloom.
- `cypher_templates_for_bloom.cypher` — saved-Cypher search phrases for
  Bloom's "Saved Cypher" feature. Some templates use `betweenness_score`,
  which is only populated when betweenness centrality is enabled.

The maintained, schema-validated query catalog lives in
`docs/modules/ROOT/examples/queries/` and is EXPLAIN-checked against a live
Neo4j in docs CI. Prefer it over these assets.
