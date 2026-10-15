from apitest.clients import Context
from apitest.scenarios import Scenario
from apitest.support import Checks, Operation


def run(context: Context, checks: Checks) -> None:
    s = Scenario(context, checks)
    own, peer, beta, retired = (
        s.skill(),
        s.skill("teacher.alpha.other"),
        s.skill("teacher.beta"),
        s.skill(),
    )
    s.call("DELETE", f"/api/skills/{retired['id']}")
    values = s.call("GET", "/api/skills")
    ids = [item["id"] for item in values]
    checks.require(
        own["id"] in ids
        and not {peer["id"], beta["id"], retired["id"]}.intersection(ids)
        and len(ids) == len(set(ids)),
        "auth.private_fields",
    )
    for item in values:
        s.verify_resource(item, "skills")
    s.call("GET", "/api/skills", account="student.alpha", status=403)
    s.call("GET", "/api/skills", account=None, status=401)


OPERATION = Operation("GET", "/api/skills", run)
