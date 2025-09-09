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

// tag::top_changed_files_by_churn[]
// Most changed files by total line churn (additions + deletions)
MATCH (c:Commit)-[r:CHANGED]->(fv:FileVer)-[:OF_FILE]->(f:File)
WITH f.path AS path,
     count(*) AS changes,
     sum(coalesce(r.additions, 0)) AS adds,
     sum(coalesce(r.deletions, 0)) AS dels,
     sum(coalesce(r.additions, 0) + coalesce(r.deletions, 0)) AS churn
RETURN path, changes, adds, dels, churn
ORDER BY churn DESC
LIMIT 25
// end::top_changed_files_by_churn[]
