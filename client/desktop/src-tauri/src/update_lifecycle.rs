use std::future::Future;

fn failure(code: &str, detail: String, recovery: Option<String>) -> String {
    serde_json::json!({"error_code": code, "detail": detail, "recovery_detail": recovery})
        .to_string()
}

// Download includes signature verification. Backend preparation and installation
// only run after that succeeds. Recovery uses the preserved worker executable.
pub async fn apply<D, P, I, R>(
    download: D,
    prepare: P,
    install: I,
    mut reconcile: R,
) -> Result<(), String>
where
    D: Future<Output = Result<Vec<u8>, String>>,
    P: FnOnce() -> Result<Option<String>, String>,
    I: FnOnce(&[u8]) -> Result<(), String>,
    R: FnMut(Option<&str>) -> Result<(), String>,
{
    let bytes = download
        .await
        .map_err(|e| failure("client_update.download_failed", e, None))?;
    let recovery = prepare().map_err(|e| failure("client_update.prepare_failed", e, None))?;
    if let Err(error) = install(&bytes) {
        return match reconcile(recovery.as_deref()) {
            Ok(()) => Err(failure(
                "client_update.install_failed_service_restored",
                error,
                None,
            )),
            Err(recovery) => Err(failure(
                "client_update.install_failed_service_unverified",
                error,
                Some(recovery),
            )),
        };
    }
    if let Err(error) = reconcile(None) {
        return match reconcile(recovery.as_deref()) {
            Ok(()) => Err(failure("client_update.service_rolled_back", error, None)),
            Err(recovery) => Err(failure(
                "client_update.service_unverified",
                error,
                Some(recovery),
            )),
        };
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;

    #[test]
    fn download_or_signature_failure_never_touches_services() {
        let result = tauri::async_runtime::block_on(apply(
            async { Err("invalid signature".into()) },
            || panic!("prepared before verification"),
            |_| panic!("installed before verification"),
            |_| panic!("restarted on download failure"),
        ));
        assert!(result
            .unwrap_err()
            .contains("client_update.download_failed"));
    }

    #[test]
    fn failed_install_recovers_using_preserved_worker_and_reports_real_result() {
        for recovered in [true, false] {
            let order = RefCell::new(Vec::new());
            let result = tauri::async_runtime::block_on(apply(
                async {
                    order.borrow_mut().push("verified");
                    Ok(vec![1])
                },
                || {
                    order.borrow_mut().push("prepared");
                    Ok(Some("private-worker".into()))
                },
                |bytes| {
                    assert_eq!(bytes, &[1]);
                    order.borrow_mut().push("install");
                    Err("disk error".into())
                },
                |path| {
                    assert_eq!(path, Some("private-worker"));
                    order.borrow_mut().push("recover");
                    if recovered {
                        Ok(())
                    } else {
                        Err("not ready".into())
                    }
                },
            ));
            assert_eq!(
                *order.borrow(),
                ["verified", "prepared", "install", "recover"]
            );
            assert!(result.unwrap_err().contains(if recovered {
                "install_failed_service_restored"
            } else {
                "install_failed_service_unverified"
            }));
        }
    }

    #[test]
    fn successful_install_checks_new_worker_before_restart() {
        let result = tauri::async_runtime::block_on(apply(
            async { Ok(vec![1]) },
            || Ok(Some("old-worker".into())),
            |_| Ok(()),
            |_| Err("worker not ready".into()),
        ));
        assert!(result
            .unwrap_err()
            .contains("client_update.service_unverified"));
    }

    #[test]
    fn failed_new_worker_recovers_even_after_successful_desktop_install() {
        let result = tauri::async_runtime::block_on(apply(
            async { Ok(vec![1]) },
            || Ok(Some("preserved-worker".into())),
            |_| Ok(()),
            |path| match path {
                None => Err("new worker crashed".into()),
                Some("preserved-worker") => Ok(()),
                _ => panic!("wrong recovery worker"),
            },
        ));
        assert!(result
            .unwrap_err()
            .contains("client_update.service_rolled_back"));
    }
}
