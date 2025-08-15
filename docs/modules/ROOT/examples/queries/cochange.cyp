// tag::frequent[]
MATCH (f1:File)-[cc:CO_CHANGED]->(f2:File)
WHERE cc.support >= coalesce($min_support, 5) AND cc.confidence >= coalesce($min_confidence, 0.6)
RETURN f1.path AS f1, f2.path AS f2, cc.support AS support, cc.confidence AS confidence
ORDER BY confidence DESC
LIMIT 25
// end::frequent[]
