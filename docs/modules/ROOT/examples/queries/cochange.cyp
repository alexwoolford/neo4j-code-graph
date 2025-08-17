// tag::cochange_pairs[]
MATCH (f1:File)-[cc:CO_CHANGED]->(f2:File)
WHERE cc.support >= 5 AND cc.confidence >= 0.6
RETURN f1.path AS f1, f2.path AS f2, cc.support AS support, cc.confidence AS confidence
ORDER BY confidence DESC, support DESC
LIMIT 25
// end::cochange_pairs[]
