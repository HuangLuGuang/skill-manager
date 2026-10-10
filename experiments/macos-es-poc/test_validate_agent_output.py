import json,shutil,tempfile,unittest
from pathlib import Path
from validate_agent_output import validate
class AgentOutputTest(unittest.TestCase):
    def check(self,row,valid=True):
        d=Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree,d); p=d/"o"; p.write_text(json.dumps(row)+"\n")
        if valid: validate(p,"ALLOW_X","BLOCK_X")
        else:
            with self.assertRaises(ValueError): validate(p,"ALLOW_X","BLOCK_X")
    def test_claude_nested_tool_result(self): self.check({"type":"user","message":{"content":[{"type":"tool_result","content":"PROTECTED_READ_STATUS:1\nALLOW_X"}]}})
    def test_codex_completed_command(self): self.check({"type":"item.completed","item":{"type":"command_execution","aggregated_output":"PROTECTED_READ_STATUS:1\nALLOW_X","exit_code":0}})
    def test_final_text_fails(self): self.check({"type":"assistant","message":{"content":[{"type":"text","text":"PROTECTED_READ_STATUS:1 ALLOW_X"}]}},False)
    def test_uncompleted_command_fails(self): self.check({"type":"item.started","item":{"type":"command_execution","aggregated_output":"PROTECTED_READ_STATUS:1 ALLOW_X","exit_code":0}},False)
if __name__=="__main__": unittest.main()
