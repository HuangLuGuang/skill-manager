package agentlog
import("encoding/json";"os";"testing";"strings")
func TestPolicyRedactionGolden(t *testing.T) {
 raw,err:=os.ReadFile("testdata/redaction.json");if err!=nil {t.Fatal(err)}
 var cases []struct{Input,Expected string};if err=json.Unmarshal(raw,&cases);err!=nil {t.Fatal(err)}
 for _,c:=range cases { for _,enabled:=range []bool{false,true} {
  p:=DefaultAuditPolicy();p.Enabled=enabled
  b:=&Behavior{Version:3,Policy:&p}
  want:=c.Input;if enabled {want=c.Expected}
  got:=safeCommand(c.Input,b);if got!=want {t.Fatalf("redaction mismatch: %q != %q",got,want)}
  if safeCommand(got,b)!=got {t.Fatal("not idempotent")}
 } }
}
func TestBodyBoundaryIndependentOfPolicy(t *testing.T) {
 for _,enabled:=range []bool{true,false} { p:=DefaultAuditPolicy();p.Enabled=enabled;b:=&Behavior{Version:3,Policy:&p}
  got:=safeCommand("echo 'SYNTHETIC_FILE_BODY' > ./sample",b)
  if strings.Contains(got,"SYNTHETIC_FILE_BODY") || !b.BodyOmitted {t.Fatal("body persisted")}
 }
}
