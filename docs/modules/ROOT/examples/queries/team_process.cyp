// tag::experts_for_module[]
MATCH (dev:Developer)-[:AUTHORED]->(commit:Commit)-[:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f:File)
WHERE f.path CONTAINS $module
WITH dev, f, count(DISTINCT commit) as commits_to_file
WHERE commits_to_file >= 3
RETURN dev.name, dev.email,
       count(DISTINCT f) as files_touched,
       sum(commits_to_file) as total_commits
ORDER BY total_commits DESC
LIMIT 10
// end::experts_for_module[]

// tag::cochange_pairs_simple[]
MATCH (f1:File)-[cc:CO_CHANGED]->(f2:File)
WHERE cc.support > 5 AND cc.confidence > 0.6
RETURN f1.path, f2.path, cc.support, cc.confidence
ORDER BY cc.confidence DESC
LIMIT 25
// end::cochange_pairs_simple[]
