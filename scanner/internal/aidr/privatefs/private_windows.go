package privatefs

import (
	"errors"
	"os"
	"path/filepath"
	"unsafe"

	"golang.org/x/sys/windows"
)

var securityAPI = windows.NewLazySystemDLL("advapi32.dll")
var getACLInformation = securityAPI.NewProc("GetAclInformation")
var getACE = securityAPI.NewProc("GetAce")

type aclSize struct{ Count, Used, Free uint32 }
type allowedACE struct {
	Kind, Flags byte
	Size        uint16
	Mask, SID   uint32
}

func UserSID() (string, error) {
	u, err := windows.GetCurrentProcessToken().GetTokenUser()
	if err != nil {
		return "", err
	}
	return u.User.Sid.String(), nil
}

// Check the Windows ACL, never the emulated POSIX permission bits.
func Check(path string) error {
	p, err := windows.UTF16PtrFromString(path)
	if err != nil {
		return err
	}
	a, err := windows.GetFileAttributes(p)
	if err != nil {
		return err
	}
	if a&windows.FILE_ATTRIBUTE_REPARSE_POINT != 0 {
		return errors.New("aidr_private_path_invalid")
	}
	sid, err := UserSID()
	if err != nil {
		return err
	}
	sd, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION|windows.DACL_SECURITY_INFORMATION)
	if err != nil {
		return err
	}
	owner, _, err := sd.Owner()
	if err != nil || !trustedOwner(owner, sid) {
		return errors.New("aidr_private_path_invalid")
	}
	acl, _, err := sd.DACL()
	if err != nil || acl == nil {
		return errors.New("aidr_private_path_invalid")
	}
	var size aclSize
	if ok, _, err := getACLInformation.Call(uintptr(unsafe.Pointer(acl)), uintptr(unsafe.Pointer(&size)), unsafe.Sizeof(size), 2); ok == 0 {
		return err
	}
	for n := uint32(0); n < size.Count; n++ {
		var ace *allowedACE
		if ok, _, err := getACE.Call(uintptr(unsafe.Pointer(acl)), uintptr(n), uintptr(unsafe.Pointer(&ace))); ok == 0 {
			return err
		}
		if ace == nil || ace.Kind != 0 || ace.Size < 12 {
			return errors.New("aidr_private_path_invalid")
		}
		who := (*windows.SID)(unsafe.Pointer(&ace.SID)).String()
		if who != sid && who != "S-1-5-18" {
			return errors.New("aidr_private_path_invalid")
		}
	}
	return nil
}

func PrepareDirectory(path string) error {
	if Check(path) == nil {
		return nil
	}
	// Reject junctions in the entire parent chain before creating or securing it.
	for p := path; ; p = filepath.Dir(p) {
		i, err := os.Lstat(p)
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		if err == nil && (!i.IsDir() || i.Mode()&os.ModeSymlink != 0) {
			return errors.New("aidr_private_path_invalid")
		}
		if filepath.Dir(p) == p {
			break
		}
	}
	if err := os.MkdirAll(path, 0700); err != nil {
		return err
	}
	return protect(path)
}

// SecureFile upgrades existing client-owned files whose POSIX mode was ignored
// on Windows; never follow a link or change an unrelated owner's file.
func SecureFile(path string) error {
	i, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !i.Mode().IsRegular() {
		return errors.New("aidr_private_path_invalid")
	}
	if err := PrepareDirectory(filepath.Dir(path)); err != nil {
		return err
	}
	if Check(path) == nil {
		return nil
	}
	return protect(path)
}

func protect(path string) error {
	sid, err := UserSID()
	if err != nil {
		return err
	}
	current, err := windows.GetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.OWNER_SECURITY_INFORMATION)
	if err != nil {
		return err
	}
	owner, _, err := current.Owner()
	if err != nil || !trustedOwner(owner, sid) {
		return errors.New("aidr_private_path_invalid")
	}
	sd, err := windows.SecurityDescriptorFromString("D:P(A;OICI;FA;;;" + sid + ")(A;OICI;FA;;;SY)")
	if err != nil {
		return err
	}
	acl, _, err := sd.DACL()
	if err != nil {
		return err
	}
	if err := windows.SetNamedSecurityInfo(path, windows.SE_FILE_OBJECT, windows.DACL_SECURITY_INFORMATION|windows.PROTECTED_DACL_SECURITY_INFORMATION, nil, nil, acl, nil); err != nil {
		return err
	}
	return Check(path)
}

// Elevated Windows processes can create files owned by Administrators. The
// protected DACL still grants access only to this user and LocalSystem.
func trustedOwner(owner *windows.SID, sid string) bool {
	return owner != nil && (owner.String() == sid || owner.String() == "S-1-5-32-544" || owner.String() == "S-1-5-18")
}
