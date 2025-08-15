// Minimal dataset to validate example queries
// Clean
MATCH (n) DETACH DELETE n;

// Files
CREATE (f1:File {path: 'src/app/service/UserService.java', total_lines: 800, method_count: 25, class_count: 2})
CREATE (f2:File {path: 'src/app/controller/UserController.java', total_lines: 350, method_count: 8, class_count: 1});

// Methods
CREATE (m1:Method {name: 'getUsers', class_name: 'UserService', is_public: true, estimated_lines: 120, pagerank_score: 0.005});
CREATE (m2:Method {name: 'list', class_name: 'UserController', is_public: true, estimated_lines: 40, pagerank_score: 0.002});

// Declarations
MATCH (f1:File {path: 'src/app/service/UserService.java'}), (m1:Method {name:'getUsers'})
CREATE (f1)-[:DECLARES]->(m1);
MATCH (f2:File {path: 'src/app/controller/UserController.java'}), (m2:Method {name:'list'})
CREATE (f2)-[:DECLARES]->(m2);

// External dependency and CVE
CREATE (dep:ExternalDependency {package: 'org.example:legacy-lib', version: '1.2.3'});
CREATE (cve:CVE {id: 'CVE-2024-0001', cvss_score: 9.1});
CREATE (i1:Import {name:'legacy-lib'})
WITH dep, cve, i1
MATCH (f1:File {path: 'src/app/service/UserService.java'})
CREATE (f1)-[:IMPORTS]->(i1)-[:DEPENDS_ON]->(dep);
CREATE (cve)-[:AFFECTS]->(dep);

// Git history shape
CREATE (dev:Developer {name: 'Alice', email: 'alice@example.com'});
CREATE (c:Commit {sha: 'abc123', date: datetime()});
CREATE (fv1:FileVer {path: 'src/app/service/UserService.java'});
CREATE (fv2:FileVer {path: 'src/app/controller/UserController.java'});
MATCH (dev),(c),(fv1),(fv2),(f1:File {path:'src/app/service/UserService.java'}),(f2:File {path:'src/app/controller/UserController.java'})
CREATE (dev)-[:AUTHORED]->(c)-[:CHANGED]->(fv1)-[:OF_FILE]->(f1)
CREATE (c)-[:CHANGED]->(fv2)-[:OF_FILE]->(f2);

// Co-change
MATCH (f1:File {path:'src/app/service/UserService.java'}), (f2:File {path:'src/app/controller/UserController.java'})
CREATE (f1)-[:CO_CHANGED {support: 10, confidence: 0.8}]->(f2);

RETURN 'ok' as status;
