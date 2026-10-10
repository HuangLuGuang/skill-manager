import json, shutil, tempfile, unittest
from pathlib import Path
from validate_agent_evidence import validate

class AgentEvidenceTest(unittest.TestCase):
    def fixture(self, mutate=None):
        d=Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree,d); protected=str(d/"protected.txt")
        rows=[
          {"event":"attribution","transition":"exec","pid":10,"pidversion":1,"kind":"direct","root_id":1},
          {"event":"attribution","transition":"exec","pid":10,"pidversion":2,"kind":"direct","root_id":1,"agent_entry_match":True,"path":"/agent"},
          {"event":"attribution","transition":"fork","pid":11,"pidversion":1,"kind":"inherited","root_id":1},
          {"event":"auth_open","pid":11,"pidversion":1,"path":protected,"response":0,"cache":False,"deadline_remaining_ticks":2,"attribution":"inherited","root_id":1},
        ]
        if mutate: mutate(rows)
        p=d/"events"; p.write_text("".join(json.dumps(x)+"\n" for x in rows)); return p,protected,"/agent"
    def test_valid(self): validate(*self.fixture())
    def test_concurrent_root_rejected(self):
        def m(r): r.append({"event":"attribution","kind":"direct","root_id":2})
        with self.assertRaisesRegex(ValueError,"one registered"): validate(*self.fixture(m))
    def test_unknown_denial_rejected(self):
        def m(r): r[3].update(attribution="unknown",root_id=0)
        with self.assertRaisesRegex(ValueError,"trusted root"): validate(*self.fixture(m))
    def test_pid_reuse_wrong_root_rejected(self):
        def m(r): r[3].update(root_id=2)
        with self.assertRaisesRegex(ValueError,"trusted root"): validate(*self.fixture(m))
    def test_launcher_argument_without_agent_exec_rejected(self):
        def m(r): r[1].update(path="/launcher",agent_entry_match=False)
        with self.assertRaisesRegex(ValueError,"matched agent entry"): validate(*self.fixture(m))

if __name__=="__main__": unittest.main()
