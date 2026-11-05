package privatefs

import (
	"golang.org/x/sys/windows"
	"os"
	"path/filepath"
	"testing"
)

func TestWindowsPrivateACL(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "private")
	if err := PrepareDirectory(dir); err != nil {
		t.Fatal(err)
	}
	file := filepath.Join(dir, "state.json")
	if err := os.WriteFile(file, []byte("{}"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := Check(file); err != nil {
		t.Fatal("child did not inherit private ACL", err)
	}
	sid, _ := UserSID()
	sd, err := windows.SecurityDescriptorFromString("D:P(A;;FA;;;" + sid + ")(A;;GR;;;WD)")
	if err != nil {
		t.Fatal(err)
	}
	acl, _, _ := sd.DACL()
	if err := windows.SetNamedSecurityInfo(file, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, acl, nil); err != nil {
		t.Fatal(err)
	}
	if Check(file) == nil {
		t.Fatal("Everyone ACL accepted")
	}
}
