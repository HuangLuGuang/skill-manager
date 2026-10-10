use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::ptr;

use windows_sys::Win32::System::Com::{
    CoInitializeEx, CoTaskMemFree, CoUninitialize, COINIT_APARTMENTTHREADED, COINIT_DISABLE_OLE1DDE,
};
use windows_sys::Win32::UI::Shell::{
    SHOpenFolderAndSelectItems, SHParseDisplayName, ShellExecuteW,
};
use windows_sys::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

struct ComApartment;

impl Drop for ComApartment {
    fn drop(&mut self) {
        // Balance each successful CoInitializeEx, including S_FALSE.
        unsafe { CoUninitialize() };
    }
}

pub(super) fn reveal(path: &Path) -> Result<(), String> {
    let wide: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    // The caller runs on a blocking worker; Shell operations require COM there.
    let initialized = unsafe {
        CoInitializeEx(
            ptr::null(),
            (COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE) as u32,
        )
    };
    if initialized < 0 {
        return Err(format!(
            "folder_open_com_failed: HRESULT 0x{:08X}",
            initialized as u32
        ));
    }
    let _apartment = ComApartment;

    if path.is_dir() {
        let verb: Vec<u16> = "open".encode_utf16().chain(Some(0)).collect();
        // ShellExecute reports request acceptance independently of Explorer's lifetime.
        let result = unsafe {
            ShellExecuteW(
                ptr::null_mut(),
                verb.as_ptr(),
                wide.as_ptr(),
                ptr::null(),
                ptr::null(),
                SW_SHOWNORMAL,
            )
        } as isize;
        if result > 32 {
            Ok(())
        } else {
            Err(format!("folder_open_shell_failed: ShellExecuteW {result}"))
        }
    } else {
        let mut item = ptr::null_mut();
        let parsed = unsafe {
            SHParseDisplayName(
                wide.as_ptr(),
                ptr::null_mut(),
                &mut item,
                0,
                ptr::null_mut(),
            )
        };
        if parsed < 0 {
            return Err(format!(
                "folder_open_parse_failed: HRESULT 0x{:08X}",
                parsed as u32
            ));
        }
        // A zero item count opens the parent and selects this absolute item.
        let result = unsafe { SHOpenFolderAndSelectItems(item, 0, ptr::null(), 0) };
        unsafe { CoTaskMemFree(item.cast()) };
        if result < 0 {
            Err(format!(
                "folder_open_select_failed: HRESULT 0x{:08X}",
                result as u32
            ))
        } else {
            Ok(())
        }
    }
}
